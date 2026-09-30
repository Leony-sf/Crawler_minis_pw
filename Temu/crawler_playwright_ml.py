from __future__ import annotations

from datetime import datetime
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from playwright.sync_api import BrowserContext, Page, sync_playwright

from base_anatel import BaseAnatel, analisar_situacao_anatel
from classificacao_ml import (
    analisar_dimensoes_produto,
    classificar_produto,
)
from extracao import extrair_produto, fechar_modais_leves
from utils import (
    arquivo_seguro,
    bloco,
    criar_pastas_saida,
    gerar_id,
    log,
    metadados_captura,
    salvar_parquet_incremental,
    secao,
)


def _url_busca(query: str, somente_internacional: bool = False) -> str:
    termo = quote_plus(query or "celular").replace("+", "-")
    url = f"https://lista.mercadolivre.com.br/{termo}"
    if somente_internacional:
        url += "_Filters_OMNI*COMPRA*INTERNACIONAL_NoIndex_True"
    return url


def _fechar_cookies(page: Page) -> None:
    for texto in ["Aceitar cookies", "Aceitar todos", "Entendi", "Concordo"]:
        try:
            botao = page.get_by_role(
                "button",
                name=texto,
                exact=False,
            ).first
            if botao.count() and botao.is_visible(timeout=700):
                botao.click(timeout=1500)
                page.wait_for_timeout(500)
                return
        except Exception:
            continue


def _abrir_busca(page: Page, url: str) -> None:
    page.goto(url, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(2500)
    fechar_modais_leves(page)
    _fechar_cookies(page)

    try:
        page.wait_for_load_state("networkidle", timeout=12000)
    except Exception:
        pass


def _coletar_links_produtos(
    page: Page,
    max_scrolls: int = 16,
) -> list[str]:
    script = r"""
    () => {
      const saida = new Set();

      for (const ancora of document.querySelectorAll('a[href]')) {
        const href = (ancora.href || '').split('#')[0].trim();
        if (!href || !href.includes('mercadolivre.com.br')) continue;
        if (href.includes('/questions') || href.includes('/reviews')) continue;

        const pareceProduto =
          href.includes('/p/') ||
          href.includes('/up/') ||
          /\/MLB-?\d+/i.test(href) ||
          /\bMLBU?\d+\b/i.test(href);

        const parecePaginacao =
          href.includes('_Desde_') ||
          /seguinte|proxima|próxima|siguiente|next/i.test(
            ancora.innerText || ancora.textContent || ''
          );

        if (pareceProduto && !parecePaginacao) saida.add(href);
      }

      return Array.from(saida);
    }
    """

    links: list[str] = []
    vistos: set[str] = set()
    repeticoes = 0
    quantidade_anterior = -1

    try:
        page.evaluate("() => window.scrollTo(0, 0)")
    except Exception:
        pass

    for tentativa in range(1, max_scrolls + 1):
        try:
            encontrados = page.evaluate(script) or []
        except Exception:
            encontrados = []

        for href in encontrados:
            href = str(href or "").strip()
            if href and href not in vistos:
                vistos.add(href)
                links.append(href)

        log(
            "listagem",
            f"Rolagem {tentativa}/{max_scrolls}: {len(links)} anúncios.",
        )

        if len(links) == quantidade_anterior:
            repeticoes += 1
        else:
            repeticoes = 0
            quantidade_anterior = len(links)

        if repeticoes >= 4:
            break

        try:
            page.mouse.wheel(0, 950)
            page.wait_for_timeout(650)
        except Exception:
            break

    return links


def _ir_proxima_pagina(page: Page) -> bool:
    seletores = [
        "li.andes-pagination__button--next a",
        "li.andes-pagination__button--next button",
        "a.andes-pagination__link:has-text('Seguinte')",
        "a:has-text('Seguinte')",
        "button:has-text('Seguinte')",
        "a:has-text('Próxima')",
        "a:has-text('Proxima')",
        "a:has-text('Siguiente')",
    ]

    for _ in range(12):
        for seletor in seletores:
            try:
                item = page.locator(seletor).first
                if not item.count() or not item.is_visible(timeout=600):
                    continue

                classe = (item.get_attribute("class") or "").lower()
                desabilitado = (
                    item.get_attribute("aria-disabled") or ""
                ).lower() == "true"

                if "disabled" in classe or desabilitado:
                    return False

                url_antes = page.url
                href = item.get_attribute("href") or ""
                item.scroll_into_view_if_needed(timeout=2500)

                try:
                    item.click(timeout=3500)
                except Exception:
                    if href:
                        page.goto(
                            href,
                            wait_until="domcontentloaded",
                            timeout=45000,
                        )
                    else:
                        continue

                try:
                    page.wait_for_url(
                        lambda atual: str(atual) != str(url_antes),
                        timeout=18000,
                    )
                except Exception:
                    if href and page.url == url_antes:
                        page.goto(
                            href,
                            wait_until="domcontentloaded",
                            timeout=45000,
                        )

                page.wait_for_timeout(2200)
                fechar_modais_leves(page)
                _fechar_cookies(page)
                return page.url != url_antes

            except Exception:
                continue

        try:
            page.mouse.wheel(0, 850)
            page.wait_for_timeout(650)
        except Exception:
            break

    return False


def _conectar_chrome_existente(
    playwright,
    porta: int = 9225,
) -> BrowserContext:
    endereco = f"http://127.0.0.1:{porta}"

    log("chrome", f"Conectando ao Chrome já aberto em {endereco}...")

    try:
        navegador = playwright.chromium.connect_over_cdp(
            endereco,
            timeout=20000,
        )
    except Exception as exc:
        raise RuntimeError(
            "Não foi possível conectar ao Chrome. Abra o Chrome antes "
            f"com --remote-debugging-port={porta} e tente novamente. "
            f"Detalhe: {exc}"
        ) from exc

    if not navegador.contexts:
        raise RuntimeError(
            "O Chrome respondeu na porta de depuração, mas nenhum contexto "
            "de navegador foi encontrado."
        )

    contexto = navegador.contexts[0]

    log("chrome", "Chrome conectado via CDP: OK")
    log("chrome", "Navegador será mantido aberto ao final da execução.")
    return contexto



def _salvar_print(
    page: Page,
    pasta_saida: Path,
    linha: dict[str, Any],
) -> str:
    classificacao = str(linha.get("classificacao") or "").upper()
    if classificacao not in {"IRREGULAR", "SUSPEITO", "NAO_CLASSIFICADO"}:
        return ""

    if classificacao == "IRREGULAR":
        subpasta = "irregulares"
    elif classificacao == "SUSPEITO":
        subpasta = "suspeitos"
    else:
        subpasta = "nao_classificados"

    pasta = pasta_saida / "prints" / subpasta
    pasta.mkdir(parents=True, exist_ok=True)

    identificador = linha.get("id_produto") or gerar_id(
        linha.get("titulo"),
        linha.get("url"),
    )
    nome = arquivo_seguro(
        f"{identificador}_{linha.get('titulo') or 'produto'}"
    )
    caminho = pasta / f"{nome}.png"

    try:
        page.screenshot(path=str(caminho), full_page=True)
        return str(caminho.resolve())
    except Exception as exc:
        log("print", f"Falha ao salvar evidência: {exc}", nivel="AVISO")
        return ""


def _modelos_capturados(
    dados: dict[str, Any],
) -> list[str]:
    modelos: list[str] = []

    for campo in [
        "modelo",
        "modelo_detalhado",
        "modelo_alfanumerico",
        "numero_modelo",
    ]:
        valor = str(
            dados.get(campo) or ""
        ).strip()

        if valor and valor not in modelos:
            modelos.append(valor)

    return modelos


def _modelo_decisivo(
    dados: dict[str, Any],
) -> tuple[str, str]:
    prioridades = [
        (
            "modelo_alfanumerico",
            "Modelo alfanumérico",
        ),
        ("modelo_detalhado", "Modelo detalhado"),
        ("numero_modelo", "Número do modelo"),
        ("modelo", "Modelo"),
    ]

    for campo, rotulo in prioridades:
        valor = str(
            dados.get(campo) or ""
        ).strip()

        if valor:
            return rotulo, valor

    return "", ""


def _valor_terminal(valor: Any, vazio: str = "NÃO LOCALIZADO") -> str:
    texto = str(valor or "").strip()
    return texto if texto else vazio


def _sim_nao_terminal(valor: Any) -> str:
    texto = str(valor or "").strip().upper()
    if texto == "SIM":
        return "SIM"
    if texto == "NAO_VERIFICADO":
        return "NÃO VERIFICADO"
    return "NÃO"


def _formatar_numero_cm(valor: Any) -> str:
    if valor in (None, ""):
        return ""
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return str(valor)
    texto = f"{numero:.2f}".rstrip("0").rstrip(".")
    return texto.replace(".", ",")


def _dimensoes_terminal(analise: dict[str, Any]) -> str:
    if analise.get("dimensoes_confiaveis") != "SIM":
        return "NÃO LOCALIZADAS"

    valores = [
        _formatar_numero_cm(analise.get("altura_cm")),
        _formatar_numero_cm(analise.get("largura_cm")),
        _formatar_numero_cm(analise.get("espessura_cm")),
    ]
    valores = [valor for valor in valores if valor]
    return " x ".join(valores) + " cm" if valores else "NÃO LOCALIZADAS"


def _log_auditoria_dimensoes(analise: dict[str, Any]) -> None:
    produto = _dimensoes_terminal(analise)
    resultado = str(
        analise.get("dentro_limite_dimensional") or "NAO_VERIFICADO"
    ).upper()

    if resultado == "SIM":
        situacao = "DENTRO DO LIMITE"
    elif resultado == "NAO":
        situacao = "ACIMA DO LIMITE"
    else:
        situacao = "NÃO FOI POSSÍVEL VERIFICAR"

    log("dimensões", "Limite adotado : 12,0 x 5,5 cm")
    log("dimensões", f"Produto        : {produto}")
    log(
        "dimensões",
        "Origem         : "
        + _valor_terminal(
            analise.get("origem_dimensoes"),
            "não localizada",
        ),
    )
    log("dimensões", f"Resultado      : {situacao}")


def _log_auditoria_anatel(
    dados: dict[str, Any],
    anatel: dict[str, Any],
    modelo_label: str,
    modelo_anuncio: str,
    nome_comercial_anuncio: str,
) -> None:
    log(
        "anatel",
        "Código         : anúncio="
        + _valor_terminal(dados.get("codigo_anatel_principal"))
        + " | base="
        + _valor_terminal(anatel.get("codigo_base"))
        + " | confere="
        + _sim_nao_terminal(anatel.get("codigo_confere_base")),
    )
    log(
        "anatel",
        "Situação Req.  : "
        + _valor_terminal(
            anatel.get("situacao_requerimento_base"),
            "NÃO LOCALIZADA",
        )
        + " | emitida="
        + _sim_nao_terminal(anatel.get("requerimento_emitido")),
    )
    log(
        "anatel",
        "Marca          : anúncio="
        + _valor_terminal(dados.get("marca"))
        + " | base="
        + _valor_terminal(anatel.get("fabricante_base"))
        + " | confere="
        + _sim_nao_terminal(anatel.get("marca_confere_base")),
    )
    log(
        "anatel",
        "Modelo         : anúncio="
        + _valor_terminal(modelo_anuncio)
        + f" ({modelo_label or 'campo não identificado'})"
        + " | base="
        + _valor_terminal(anatel.get("modelo_base"))
        + " | confere="
        + _sim_nao_terminal(anatel.get("modelo_confere_base")),
    )
    log(
        "anatel",
        "Nome Com.      : anúncio="
        + _valor_terminal(nome_comercial_anuncio)
        + " | base="
        + _valor_terminal(anatel.get("nome_comercial_base"))
        + " | confere="
        + _sim_nao_terminal(anatel.get("nome_comercial_confere_base")),
    )
    log(
        "anatel",
        "Resultado      : "
        + _valor_terminal(anatel.get("situacao_anatel"), "NÃO VERIFICADO")
        + " — "
        + _valor_terminal(anatel.get("motivo_anatel"), "sem motivo"),
    )


def _log_auditoria_classificacao(linha: dict[str, Any]) -> None:
    log(
        "classificação",
        "Destino        : "
        + _valor_terminal(linha.get("classificacao"), "NÃO DEFINIDO"),
    )
    log(
        "classificação",
        "Motivo         : "
        + _valor_terminal(
            linha.get("motivo_classificacao"),
            "sem motivo registrado",
        ),
    )


def _formatar_dimensoes_encontradas(
    classificacao: dict[str, Any],
) -> str:
    if classificacao.get("dimensoes_confiaveis") != "SIM":
        return "NAO ENCONTRADAS"

    valores: list[str] = []

    for campo in [
        "altura_cm",
        "largura_cm",
        "espessura_cm",
    ]:
        valor = classificacao.get(campo)
        if valor in (None, ""):
            continue

        try:
            numero = float(valor)
        except (TypeError, ValueError):
            continue

        texto = f"{numero:.2f}".rstrip("0").rstrip(".")
        valores.append(texto.replace(".", ","))

    if len(valores) < 2:
        return "ENCONTRADAS, MAS INCOMPLETAS"

    return " x ".join(valores) + " cm"


def _linha_produto(
    dados: dict[str, Any],
    classificacao: dict[str, Any],
    anatel: dict[str, str],
    pasta_saida: Path,
    consulta: str,
    momento: datetime,
) -> dict[str, Any]:
    pid = gerar_id(
        dados.get("titulo"),
        dados.get("marca"),
        anatel.get(
            "codigo_anatel_normalizado"
        ),
        dados.get("url"),
    )

    modelos = _modelos_capturados(dados)
    modelo_label, modelo_valor = _modelo_decisivo(
        dados
    )

    classificacao_final = str(
        classificacao.get("classificacao") or ""
    ).upper()

    motivo_final = str(
        classificacao.get(
            "motivo_classificacao"
        ) or ""
    )

    if classificacao_final == "IRREGULAR":
        status_legado = "Irregular"
    elif classificacao_final == "SUSPEITO":
        status_legado = "Suspeito"
    elif classificacao_final == "NAO_CLASSIFICADO":
        status_legado = "Não Classificado"
    else:
        status_legado = "Descartado"

    linha: dict[str, Any] = {
        "pid": pid,
        "marketplace_id": "2",
        "name": dados.get("titulo", ""),
        "titulo": dados.get("titulo", ""),
        "link": dados.get("url", ""),
        "url": dados.get("url", ""),
        "anatel_number": anatel.get(
            "codigo_anatel_normalizado",
            "",
        ),
        "codigo_anatel_principal": dados.get(
            "codigo_anatel_principal",
            "",
        ),
        "brand": dados.get("marca", ""),
        "marca": dados.get("marca", ""),
        "price": dados.get("preco", ""),
        "preco": dados.get("preco", ""),
        "reviewers": "",
        "status": status_legado,
        "status_validacao": classificacao_final,
        "irregularity_reasons": (
            motivo_final
            if classificacao_final == "IRREGULAR"
            else ""
        ),
        "motivo_validacao": motivo_final,
        "warnings": (
            motivo_final
            if classificacao_final == "SUSPEITO"
            else anatel.get("motivo_anatel", "")
        ),
        "created_at": momento.strftime("%Y-%m-%d"),
        "modelo": dados.get("modelo", ""),
        "modelo_detalhado": dados.get(
            "modelo_detalhado",
            "",
        ),
        "modelo_alfanumerico": dados.get(
            "modelo_alfanumerico",
            "",
        ),
        "numero_modelo": dados.get(
            "numero_modelo",
            "",
        ),
        "modelo_decisivo_label": modelo_label,
        "modelo_decisivo": modelo_valor,
        "modelo_decisivo_partes_json": json.dumps(
            [
                parte
                for parte in re.split(
                    r"[\s/|,;:_-]+",
                    modelo_valor,
                )
                if parte
            ],
            ensure_ascii=False,
        ),
        "modelos_capturados_json": json.dumps(
            modelos,
            ensure_ascii=False,
        ),
        "fabricante": dados.get(
            "fabricante",
            "",
        ),
        "modo_match_base": anatel.get(
            "situacao_anatel",
            "",
        ),
        "query_busca": consulta,
        "descricao": dados.get("descricao", ""),
        "texto_pagina": dados.get(
            "texto_pagina",
            "",
        ),
        "atributos_json": json.dumps(
            dados.get("atributos") or {},
            ensure_ascii=False,
            sort_keys=True,
        ),
        "total_comentarios": len(
            dados.get("comentarios") or []
        ),
        "print_path": "",
    }

    linha.update(classificacao)
    linha.update(anatel)
    linha.update(
        metadados_captura(
            pasta_saida,
            momento,
        )
    )

    linha["codigo_anatel"] = (
        anatel.get("codigo_anatel_normalizado")
        or dados.get("codigo_anatel_principal")
        or ""
    )
    linha["motivo_irregularidade"] = (
        motivo_final
        if classificacao_final == "IRREGULAR"
        else ""
    )
    linha["warning"] = (
        motivo_final
        if classificacao_final == "SUSPEITO"
        else ""
    )
    linha["dimensoes_encontradas"] = (
        _formatar_dimensoes_encontradas(classificacao)
    )

    return linha


def _comentarios_para_linhas(
    produto: dict[str, Any],
    comentarios: list[str],
) -> list[dict[str, Any]]:
    linhas: list[dict[str, Any]] = []

    for ordem, comentario in enumerate(
        comentarios,
        start=1,
    ):
        linhas.append({
            "pid": produto.get("pid", ""),
            "marketplace_id": "2",
            "url": produto.get("url", ""),
            "link": produto.get("link", ""),
            "titulo": produto.get(
                "titulo",
                "",
            ),
            "name": produto.get("name", ""),
            "comentario_ordem": ordem,
            "comment": comentario,
            "comentario": comentario,
            "created_at": produto.get(
                "created_at",
                "",
            ),
            "query_busca": produto.get(
                "query_busca",
                "",
            ),
            "classificacao": produto.get(
                "classificacao",
                "",
            ),
            "status": produto.get("status", ""),
            "status_validacao": produto.get(
                "status_validacao",
                "",
            ),
            "codigo_anatel_principal": produto.get(
                "codigo_anatel_principal",
                "",
            ),
            "anatel_number": produto.get(
                "anatel_number",
                "",
            ),
            "marca": produto.get("marca", ""),
            "brand": produto.get("brand", ""),
            "modelo": produto.get("modelo", ""),
            "data_hora_captura": produto.get(
                "data_hora_captura",
                "",
            ),
            "data_hora_captura_iso": produto.get(
                "data_hora_captura_iso",
                "",
            ),
            "referencia_captura": produto.get(
                "referencia_captura",
                "",
            ),
            "pasta_saida_execucao": produto.get(
                "pasta_saida_execucao",
                "",
            ),
            "caminho_saida_execucao": produto.get(
                "caminho_saida_execucao",
                "",
            ),
        })

    return linhas


def rodar_playwright_mercadolivre(
    query: str = "celular",
    queries: list[str] | None = None,
    limite: int = 0,
    limite_por_query: int = 0,
    base_anatel: BaseAnatel | None = None,
    url: str | None = None,
    saida: str | Path | None = None,
    max_paginas: int = 0,
    somente_internacional: bool = False,
    capturar_comentarios: bool = True,
    pausar_inicio: bool = True,
    porta_chrome: int = 9225,
) -> dict[str, Any]:
    pasta_saida = criar_pastas_saida(saida)
    log("arquivos", f"Pasta desta execução: {pasta_saida}")

    produtos: list[dict[str, Any]] = []
    comentarios: list[dict[str, Any]] = []

    salvar_parquet_incremental(
        pasta_saida,
        produtos,
        comentarios,
    )

    consultas_raw = queries or [query]
    consultas: list[tuple[str, str]] = []
    vistos_consultas: set[str] = set()

    if url:
        consultas = [(query or "URL direta", url)]
    else:
        for termo in consultas_raw:
            termo = str(termo or "").strip()
            chave = termo.lower()
            if not termo or chave in vistos_consultas:
                continue
            vistos_consultas.add(chave)
            consultas.append((
                termo,
                _url_busca(termo, somente_internacional),
            ))

    if not consultas:
        consultas = [("celular", _url_busca("celular", somente_internacional))]

    total_visitados = 0
    total_descartados = 0
    urls_processadas: set[str] = set()

    def limite_atingido() -> bool:
        return limite > 0 and total_visitados >= limite

    secao("Mercado Livre — crawler de referência")

    with sync_playwright() as playwright:
        contexto = _conectar_chrome_existente(
            playwright,
            porta=porta_chrome,
        )
        pagina_busca = (
            contexto.pages[0] if contexto.pages else contexto.new_page()
        )
        pagina_busca.set_default_timeout(12000)
        pagina_busca.set_default_navigation_timeout(45000)

        try:
            _abrir_busca(pagina_busca, consultas[0][1])

            if pausar_inicio:
                secao("Pausa manual")
                print(
                    "Resolva login ou captcha no Chrome e deixe a listagem "
                    "aberta."
                )
                input("Pressione ENTER para iniciar a coleta... ")

            for indice_consulta, (consulta, url_consulta) in enumerate(
                consultas,
                start=1,
            ):
                if limite_atingido():
                    break

                secao(f"Busca {indice_consulta}/{len(consultas)} — {consulta}")
                if indice_consulta > 1:
                    _abrir_busca(pagina_busca, url_consulta)

                pagina_atual = 1
                processados_consulta = 0

                while True:
                    if limite_atingido():
                        break
                    if max_paginas > 0 and pagina_atual > max_paginas:
                        break
                    if (
                        limite_por_query > 0 and
                        processados_consulta >= limite_por_query
                    ):
                        break

                    bloco(f"Página {pagina_atual}")
                    links = _coletar_links_produtos(pagina_busca)
                    links_novos = [
                        link for link in links
                        if link not in urls_processadas
                    ]

                    if not links_novos:
                        log("listagem", "Nenhum anúncio novo nesta página.")
                        if not _ir_proxima_pagina(pagina_busca):
                            break
                        pagina_atual += 1
                        continue

                    for indice_produto, link in enumerate(links_novos, start=1):
                        if limite_atingido():
                            break
                        if (
                            limite_por_query > 0 and
                            processados_consulta >= limite_por_query
                        ):
                            break

                        urls_processadas.add(link)
                        total_visitados += 1
                        processados_consulta += 1

                        bloco(
                            f"Produto {indice_produto}/{len(links_novos)}"
                        )
                        log("produto", link)

                        pagina_produto = contexto.new_page()
                        pagina_produto.set_default_timeout(12000)
                        pagina_produto.set_default_navigation_timeout(45000)

                        try:
                            pagina_produto.goto(
                                link,
                                wait_until="domcontentloaded",
                                timeout=45000,
                            )
                            pagina_produto.wait_for_timeout(1800)
                            try:
                                pagina_produto.wait_for_load_state(
                                    "networkidle",
                                    timeout=10000,
                                )
                            except Exception:
                                pass

                            dados = extrair_produto(
                                pagina_produto,
                                capturar_reviews=capturar_comentarios,
                            )
                            momento = datetime.now().astimezone()

                            analise_dimensional = analisar_dimensoes_produto(
                                dados
                            )
                            _log_auditoria_dimensoes(analise_dimensional)

                            modelo_label_anatel, modelo_anatel = _modelo_decisivo(
                                dados
                            )
                            nome_comercial_anatel = str(dados.get("modelo") or "")
                            
                            anatel = analisar_situacao_anatel(
                                codigo=dados.get("codigo_anatel_principal", ""),
                                marca=dados.get("marca", ""),
                                modelo_tecnico=modelo_anatel,
                                nome_comercial=nome_comercial_anatel,
                                base=base_anatel,
                            )
                            
                            _log_auditoria_anatel(
                                dados,
                                anatel,
                                modelo_label_anatel,
                                modelo_anatel,
                                nome_comercial_anatel,
                            )

                            classificacao = classificar_produto(
                                dados,
                                analise_dimensional,
                                anatel,
                            )
                            classificacao.update(analise_dimensional)

                            linha = _linha_produto(
                                dados,
                                classificacao,
                                anatel,
                                pasta_saida,
                                consulta,
                                momento,
                            )

                            status = linha["classificacao"]
                            _log_auditoria_classificacao(linha)

                            if status == "DESCARTADO":
                                total_descartados += 1
                                continue

                            linha["print_path"] = _salvar_print(
                                pagina_produto,
                                pasta_saida,
                                linha,
                            )
                            produtos.append(linha)

                            comentarios.extend(
                                _comentarios_para_linhas(
                                    linha,
                                    dados.get("comentarios") or [],
                                )
                            )

                            salvar_parquet_incremental(
                                pasta_saida,
                                produtos,
                                comentarios,
                            )

                        except Exception as exc:
                            log(
                                "erro produto",
                                f"Falha ao processar anúncio: {exc}",
                                nivel="ERRO",
                            )
                        finally:
                            try:
                                pagina_produto.close()
                            except Exception:
                                pass

                    if limite_atingido():
                        break
                    if (
                        limite_por_query > 0 and
                        processados_consulta >= limite_por_query
                    ):
                        break
                    if max_paginas > 0 and pagina_atual >= max_paginas:
                        break
                    if not _ir_proxima_pagina(pagina_busca):
                        break

                    pagina_atual += 1

        finally:
            salvar_parquet_incremental(
                pasta_saida,
                produtos,
                comentarios,
            )

            log(
                "chrome",
                "Execução finalizada; Chrome mantido aberto.",
            )

    resumo = {
        "pasta_saida": str(pasta_saida),
        "total_visitados": total_visitados,
        "total_irregulares": sum(
            1 for item in produtos
            if item.get("classificacao") == "IRREGULAR"
        ),
        "total_suspeitos": sum(
            1
            for item in produtos
            if item.get("classificacao") == "SUSPEITO"
        ),
        "total_nao_classificados": sum(
            1
            for item in produtos
            if item.get("classificacao") == "NAO_CLASSIFICADO"
        ),
        "total_descartados": total_descartados,
        "total_produtos_no_parquet": len(produtos),
        "total_comentarios": len(comentarios),
        "criterio_dimensional": "120 x 55 mm",
        "data_hora_finalizacao": datetime.now().astimezone().strftime(
            "%d/%m/%Y %H:%M:%S"
        ),
    }
    secao("Resumo")
    for chave, valor in resumo.items():
        log("resumo", f"{chave}: {valor}")

    return resumo