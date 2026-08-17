# -*- coding: utf-8 -*-
"""Crawler Carrefour com Playwright."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from playwright.async_api import async_playwright, BrowserContext, Page, TimeoutError as PlaywrightTimeoutError

from classificacao_carrefour import classificar_produto
from extracao_carrefour import coletar_links_resultados, esperar_carregamento, extrair_produto, fechar_popups_basicos
from utils_carrefour import agora_iso, carregar_termos_busca, escrever_resumo_txt, montar_url_busca, preparar_saida, slugify


@dataclass
class ConfigCarrefour:
    txt: str = "buscar_carrefour.txt"
    saida: Path = Path("saidas_carrefour")
    limit: int = 100
    max_paginas: int = 2
    headless: bool = False
    slow_mo: int = 0
    timeout_ms: int = 30000
    salvar_descartados: bool = False
    limpar_prints: bool = False
    pausar_inicio: bool = False


async def executar_crawler_carrefour(config: ConfigCarrefour) -> List[Dict[str, Any]]:
    termos = carregar_termos_busca(config.txt)
    preparar_saida(config.saida, limpar_prints=config.limpar_prints)

    resultados: List[Dict[str, Any]] = []
    visitados: set[str] = set()
    total_cards = 0
    total_descartados = 0
    total_erros = 0
    total_analisados = 0

    _imprimir_cabecalho(config, termos)

    async with async_playwright() as p:
        contexto = await _criar_contexto(p, config)
        page = await _obter_pagina_principal(contexto)
        page.set_default_timeout(config.timeout_ms)

        if config.pausar_inicio:
            await _abrir_pagina_para_pausa(page, config, termos[0])
            print("\n[LOGIN] Resolva CEP/login/captcha/verificação no navegador, se aparecer.")
            input("        Pressione ENTER aqui no terminal para iniciar a coleta...")

        # Ordem correta: página 1 linha 1 -> página 1 linha 2 -> página 1 linha 3...
        # Depois página 2 linha 1, se --max-paginas for maior que 1.
        for pagina in range(1, config.max_paginas + 1):
            if total_analisados >= config.limit:
                break

            _imprimir_secao(f"RODADA DE BUSCA | PÁGINA {pagina}/{config.max_paginas}")

            for idx_termo, termo in enumerate(termos, start=1):
                if total_analisados >= config.limit:
                    break

                print(f"\n[BUSCA] Página {pagina}/{config.max_paginas} | Linha {idx_termo}/{len(termos)} do TXT")
                print(f"        Termo: {termo}")

                cards = await _abrir_busca_e_coletar(page, config, termo, pagina)
                total_cards += len(cards)
                print(f"        Links candidatos: {len(cards)}")

                if not cards:
                    continue

                for indice, card in enumerate(cards, start=1):
                    if total_analisados >= config.limit:
                        break

                    url_produto = card.get("url", "")
                    if not url_produto or url_produto in visitados:
                        continue
                    visitados.add(url_produto)

                    numero_atual = total_analisados + 1
                    total_analisados += 1

                    registro = await _processar_produto(
                        contexto=contexto,
                        url_produto=url_produto,
                        card=card,
                        config=config,
                        termo=termo,
                        pagina=pagina,
                        indice_item=indice,
                        total_itens=len(cards),
                        numero_processado=numero_atual,
                    )
                    if not registro:
                        total_erros += 1
                        continue

                    if registro.get("status") == "DESCARTADO":
                        total_descartados += 1
                        if not config.salvar_descartados:
                            continue

                    resultados.append(registro)
                    _salvar_parquets_incrementais(resultados, config.saida)

        await contexto.close()

    _salvar_parquets_incrementais(resultados, config.saida)
    _salvar_resumo(resultados, config, termos, total_cards, total_descartados, total_erros, total_analisados)
    _imprimir_final(resultados, config, total_descartados, total_erros, total_analisados)
    return resultados


async def _abrir_busca_e_coletar(page: Page, config: ConfigCarrefour, termo: str, pagina: int) -> List[Dict[str, Any]]:
    # Tenta formatos diferentes, porque a Carrefour varia a renderização da busca.
    for modo in ["s", "busca", "query"]:
        try:
            url_busca = montar_url_busca(termo, pagina, modo=modo)
            await page.goto(url_busca, wait_until="domcontentloaded", timeout=config.timeout_ms)
            await esperar_carregamento(page, timeout_ms=config.timeout_ms)
            await fechar_popups_basicos(page)
            cards = await coletar_links_resultados(page)
            if cards:
                return cards
        except PlaywrightTimeoutError:
            print("        Aviso: timeout na busca. Tentando aproveitar o que carregou.")
            try:
                cards = await coletar_links_resultados(page)
                if cards:
                    return cards
            except Exception:
                pass
        except Exception as exc:
            print(f"        Erro ao abrir busca ({modo}): {_texto_curto(str(exc), 120)}")
    return []


async def _obter_pagina_principal(contexto: BrowserContext) -> Page:
    if contexto.pages:
        page = contexto.pages[0]
        for extra in contexto.pages[1:]:
            try:
                if extra.url == "about:blank":
                    await extra.close()
            except Exception:
                pass
        return page
    return await contexto.new_page()


async def _abrir_pagina_para_pausa(page: Page, config: ConfigCarrefour, primeiro_termo: str) -> None:
    url_inicial = montar_url_busca(primeiro_termo, 1)
    print("[INÍCIO] Abrindo Carrefour para verificação inicial...")
    try:
        await page.goto(url_inicial, wait_until="domcontentloaded", timeout=config.timeout_ms)
        await esperar_carregamento(page, timeout_ms=config.timeout_ms)
        await fechar_popups_basicos(page)
    except PlaywrightTimeoutError:
        print("        Aviso: timeout ao abrir Carrefour antes da pausa. A página pode ainda estar carregando.")
    except Exception as exc:
        print(f"        Aviso: não foi possível abrir a página inicial: {_texto_curto(str(exc), 120)}")
        print("        Acesse manualmente https://www.carrefour.com.br nessa janela e depois pressione ENTER.")


async def _criar_contexto(p: Any, config: ConfigCarrefour) -> BrowserContext:
    perfil = Path("perfil_carrefour").resolve()
    perfil.mkdir(parents=True, exist_ok=True)
    contexto = await p.chromium.launch_persistent_context(
        user_data_dir=str(perfil),
        headless=config.headless,
        slow_mo=config.slow_mo,
        viewport={"width": 1366, "height": 900},
        locale="pt-BR",
        args=["--disable-blink-features=AutomationControlled", "--start-maximized"],
    )
    return contexto


async def _processar_produto(
    contexto: BrowserContext,
    url_produto: str,
    card: Dict[str, Any],
    config: ConfigCarrefour,
    termo: str,
    pagina: int,
    indice_item: int,
    total_itens: int,
    numero_processado: int,
) -> Optional[Dict[str, Any]]:
    page: Optional[Page] = None
    try:
        page = await contexto.new_page()
        page.set_default_timeout(config.timeout_ms)
        await page.goto(url_produto, wait_until="domcontentloaded", timeout=config.timeout_ms)
        produto = await extrair_produto(page, url_produto, card)
        classificacao = classificar_produto(produto)

        registro: Dict[str, Any] = {
            "data_coleta": agora_iso(),
            "marketplace": "Carrefour",
            "termo_busca": termo,
            "pagina_busca": pagina,
            "item_busca": indice_item,
            "status": classificacao.status,
            **classificacao.as_dict(),
            "titulo": produto.get("titulo", ""),
            "preco": produto.get("preco", ""),
            "fornecedor": produto.get("fornecedor", ""),
            "moq": produto.get("moq", ""),
            "vendidos_pedidos": produto.get("vendidos_pedidos", ""),
            "url": produto.get("url", url_produto),
            "url_canonica": produto.get("url_canonica", url_produto),
            "imagem": produto.get("imagem", ""),
            "detalhes": produto.get("detalhes", "")[:6000],
            "ficha_tecnica": produto.get("ficha_tecnica", "")[:6000],
            "texto_card": produto.get("texto_card", "")[:2000],
            "print_comprovante": "",
        }

        if classificacao.status != "DESCARTADO" and classificacao.categoria_print:
            registro["print_comprovante"] = await _tirar_print_produto(page, config.saida, registro, classificacao.categoria_print)

        _imprimir_produto(registro, numero_processado, config.limit, indice_item, total_itens)
        return registro
    except PlaywrightTimeoutError:
        registro_erro = _registro_erro_timeout(url_produto, card, termo, pagina, indice_item)
        _imprimir_produto(registro_erro, numero_processado, config.limit, indice_item, total_itens)
        return registro_erro
    except Exception as exc:
        print(f"[{numero_processado:03d}] ERRO | {_texto_curto(str(exc), 110)}")
        return None
    finally:
        if page:
            try:
                await page.close()
            except Exception:
                pass


def _registro_erro_timeout(url_produto: str, card: Dict[str, Any], termo: str, pagina: int, indice_item: int) -> Dict[str, Any]:
    return {
        "data_coleta": agora_iso(),
        "marketplace": "Carrefour",
        "termo_busca": termo,
        "pagina_busca": pagina,
        "item_busca": indice_item,
        "status": "ERRO",
        "categoria_print": "",
        "motivo": "Timeout ao abrir/coletar produto.",
        "evidencias": "",
        "codigo_anatel": "",
        "tela_extraida": "",
        "tela_polegadas": None,
        "tela_mini": False,
        "tela_suspeita": False,
        "tela_grande": False,
        "eh_mini_celular": False,
        "eh_acessorio": False,
        "sem_tela": False,
        "regra_classificacao": "timeout",
        "medidas_extraidas": "",
        "altura_cm": None,
        "largura_cm": None,
        "medida_proxima_ou_menor": False,
        "sem_medidas": False,
        "maior_dimensao_mm": None,
        "altura_mm": None,
        "largura_mm": None,
        "comprimento_mm": None,
        "titulo": card.get("titulo_busca", ""),
        "preco": "",
        "fornecedor": "",
        "moq": "",
        "vendidos_pedidos": "",
        "url": url_produto,
        "url_canonica": url_produto,
        "imagem": "",
        "detalhes": "",
        "ficha_tecnica": "",
        "texto_card": card.get("texto_card", ""),
        "print_comprovante": "",
    }


async def _tirar_print_produto(page: Page, saida: Path, registro: Dict[str, Any], categoria: str) -> str:
    pasta = saida / "prints" / categoria
    pasta.mkdir(parents=True, exist_ok=True)
    titulo = slugify(registro.get("titulo") or registro.get("url_canonica", "produto"), max_len=70)
    indice = abs(hash(registro.get("url_canonica", ""))) % 10_000_000
    caminho = pasta / f"{indice}_{titulo}.png"
    try:
        await page.screenshot(path=str(caminho), full_page=True)
        return str(caminho)
    except Exception as exc:
        print(f"        Aviso: não foi possível tirar print: {_texto_curto(str(exc), 100)}")
        return ""


def _salvar_parquets_incrementais(resultados: List[Dict[str, Any]], saida: Path) -> None:
    if not resultados:
        return
    df = pd.DataFrame(resultados)
    df.to_parquet(saida / "products.parquet", index=False)
    suspeitos = pd.DataFrame()
    if "status" in df.columns:
        suspeitos = df[df["status"].isin(["SUSPEITO", "REVISAR"])].copy()
    pasta_suspeitos = saida / "suspeitos"
    pasta_suspeitos.mkdir(parents=True, exist_ok=True)
    caminho_suspeitos = pasta_suspeitos / "suspeitos.parquet"
    if not suspeitos.empty:
        suspeitos.to_parquet(caminho_suspeitos, index=False)
    elif caminho_suspeitos.exists():
        caminho_suspeitos.unlink()


def _salvar_resumo(resultados: List[Dict[str, Any]], config: ConfigCarrefour, termos: List[str], total_cards: int, total_descartados: int, total_erros: int, total_analisados: int) -> None:
    df = pd.DataFrame(resultados)
    qtd_sem_medidas = 0
    qtd_irregulares_dimensao = 0
    qtd_suspeitos_dimensao = 0
    if not df.empty:
        if "sem_medidas" in df.columns:
            qtd_sem_medidas = int(((df["sem_medidas"] == True) & (df["status"].isin(["SUSPEITO", "REVISAR"]))).sum())  # noqa: E712
        if "status" in df.columns:
            qtd_irregulares_dimensao = int((df["status"] == "IRREGULAR").sum())
            qtd_suspeitos_dimensao = int((df["status"] == "SUSPEITO").sum())

    linhas = [
        "Resumo da coleta Carrefour",
        "===============================",
        f"Data/hora: {agora_iso()}",
        "Regra aplicada: celular com maior dimensão física <= 80 mm = IRREGULAR; acima de 80 até 90 mm = SUSPEITO",
        f"Termos de busca: {', '.join(termos)}",
        f"Páginas por termo: {config.max_paginas}",
        f"Limite configurado: {config.limit}",
        f"Produtos analisados nesta execução: {total_analisados}",
        f"Links candidatos em páginas de busca: {total_cards}",
        f"Registros salvos no products.parquet: {len(resultados)}",
        f"Irregulares por dimensão <= 80 mm: {qtd_irregulares_dimensao}",
        f"Suspeitos por dimensão próxima (>80 até 90 mm): {qtd_suspeitos_dimensao}",
        f"Sem medida mantidos como suspeitos/revisão: {qtd_sem_medidas}",
        f"Descartados não salvos: {total_descartados if not config.salvar_descartados else 0}",
        f"Erros/timeout: {total_erros}",
        "",
        "Contagem por status:",
    ]
    if df.empty:
        linhas.append("- Nenhum registro salvo.")
    else:
        for status, qtd in df["status"].value_counts(dropna=False).items():
            linhas.append(f"- {status}: {qtd}")
        if "categoria_print" in df.columns:
            linhas.extend(["", "Contagem por categoria de print:"])
            for cat, qtd in df["categoria_print"].fillna("").value_counts().items():
                if cat:
                    linhas.append(f"- {cat}: {qtd}")

    linhas.extend([
        "",
        "Arquivos gerados:",
        "- products.parquet",
        "- suspeitos/suspeitos.parquet, quando houver",
        "- resumo.txt",
        "- prints/irregulares/menor_80mm/",
        "- prints/suspeitos/",
        "",
        "Observação:",
        "- CSV, JSON e comentários não são gerados nesta versão.",
        "- Celulares com maior dimensão física acima de 90 mm são descartados.",
        "- Termo 'mini' sozinho não classifica como irregular; a decisão principal é a maior dimensão física do aparelho.",
    ])
    escrever_resumo_txt(config.saida, linhas)


def _imprimir_cabecalho(config: ConfigCarrefour, termos: List[str]) -> None:
    _imprimir_secao("CRAWLER CARREFOUR.COM | MINI CELULARES")
    print(f"Termos: {len(termos)} | Páginas/termo: {config.max_paginas} | Limite: {config.limit}")
    print(f"Saída: {config.saida.resolve()}")
    print("Arquivos: products.parquet + suspeitos/suspeitos.parquet")
    print("Filtro : dimensão <= 80 mm = IRREGULAR; > 80 até 90 mm = SUSPEITO; > 90 mm = DESCARTADO")


def _imprimir_secao(titulo: str) -> None:
    print("\n" + "=" * 72)
    print(titulo)
    print("=" * 72)


def _imprimir_produto(registro: Dict[str, Any], numero: int, limite: int, item: int, total_itens: int) -> None:
    status = registro.get("status", "")
    categoria = registro.get("categoria_print", "") or "sem_print"
    categoria_curta = categoria.split("/")[-1] if categoria else "sem_print"
    titulo = _texto_curto(registro.get("titulo") or registro.get("url_canonica", ""), 86)
    motivo = _texto_curto(registro.get("motivo", ""), 110)
    maior_dim = registro.get("maior_dimensao_mm", None)
    print(f"[{numero:03d}/{limite}] {status:<10} | {categoria_curta:<18} | item {item}/{total_itens}")
    if titulo:
        print(f"        Título   : {titulo}")
    if maior_dim not in (None, ""):
        print(f"        Dimensão : maior dimensão {maior_dim} mm")
    else:
        print("        Dimensão : não localizada")
    if motivo and status != "DESCARTADO":
        print(f"        Motivo   : {motivo}")


def _imprimir_final(resultados: List[Dict[str, Any]], config: ConfigCarrefour, total_descartados: int, total_erros: int, total_analisados: int) -> None:
    df = pd.DataFrame(resultados)
    qtd_sem_medidas = 0
    qtd_irregulares = 0
    qtd_suspeitos = 0
    if not df.empty:
        if "sem_medidas" in df.columns:
            qtd_sem_medidas = int(((df["sem_medidas"] == True) & (df["status"].isin(["SUSPEITO", "REVISAR"]))).sum())  # noqa: E712
        if "status" in df.columns:
            qtd_irregulares = int((df["status"] == "IRREGULAR").sum())
            qtd_suspeitos = int((df["status"] == "SUSPEITO").sum())
    _imprimir_secao("FINALIZADO")
    print(f"Produtos analisados: {total_analisados}/{config.limit}")
    print(f"Registros no products.parquet: {len(resultados)}")
    print(f"Irregulares por dimensão <= 80 mm: {qtd_irregulares}")
    print(f"Suspeitos por dimensão > 80 e <= 90 mm: {qtd_suspeitos}")
    print(f"Sem medida mantidos como suspeitos/revisão: {qtd_sem_medidas}")
    print(f"Descartados não salvos: {total_descartados if not config.salvar_descartados else 0}")
    print(f"Erros/timeout: {total_erros}")
    print(f"Pasta de saída: {config.saida.resolve()}")


def _texto_curto(texto: str, limite: int = 90) -> str:
    texto = " ".join(str(texto or "").split())
    return texto if len(texto) <= limite else texto[: limite - 3] + "..."
