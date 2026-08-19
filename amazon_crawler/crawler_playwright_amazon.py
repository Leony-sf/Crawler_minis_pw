from __future__ import annotations

from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus, urljoin
import re
from typing import Any

from playwright.sync_api import BrowserContext, Page, sync_playwright

from .base_anatel import BaseAnatel
from .extracao import DadosProduto, analisar_situacao_anatel, classificar_produto, _modelo_decisivo_capturado
from .extracao_amazon import extrair_produto_amazon, fechar_modais_amazon, analisar_mini_celular_amazon
from .seller_amazon import analisar_vendedor_amazon
from .utils import bloco, criar_pastas_saida, gerar_id, log, secao, salvar_parquet_incremental, metadados_captura

# ============================================================
# FORMATAÇÃO DO TERMINAL (PADRÃO ML)
# ============================================================

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
    valores = [v for v in valores if v]
    return " x ".join(valores) + " cm" if valores else "NÃO LOCALIZADAS"

def _log_auditoria_dimensoes(analise: dict[str, Any]) -> None:
    produto = _dimensoes_terminal(analise)
    resultado = str(analise.get("dentro_limite_dimensional") or "NAO_VERIFICADO").upper()

    if resultado == "SIM":
        situacao = "DENTRO DO LIMITE"
    elif resultado == "NAO":
        situacao = "ACIMA DO LIMITE"
    else:
        situacao = "NÃO FOI POSSÍVEL VERIFICAR"

    print("")
    log("dimensões", "Limite adotado : 12,0 x 5,5 cm")
    log("dimensões", f"Produto        : {produto}")
    log("dimensões", "Origem         : " + _valor_terminal(analise.get("origem_dimensoes"), "não localizada"))
    log("dimensões", f"Resultado      : {situacao}")

def _log_auditoria_anatel(dados: DadosProduto, anatel: dict[str, Any], modelo_anuncio: str) -> None:
    log("anatel", "Código         : anúncio=" + _valor_terminal(dados.codigo_anatel_principal) + " | base=" + _valor_terminal(anatel.get("codigo_base")) + " | confere=" + _sim_nao_terminal(anatel.get("codigo_confere_base")))
    log("anatel", "Situação Req.  : " + _valor_terminal(anatel.get("situacao_requerimento_base"), "NÃO LOCALIZADA") + " | emitida=" + _sim_nao_terminal(anatel.get("requerimento_emitido")))
    log("anatel", "Marca          : anúncio=" + _valor_terminal(dados.marca) + " | base=" + _valor_terminal(anatel.get("fabricante_base")) + " | confere=" + _sim_nao_terminal(anatel.get("marca_confere_base")))
    log("anatel", "Modelo         : anúncio=" + _valor_terminal(modelo_anuncio) + " | base=" + _valor_terminal(anatel.get("modelo_base")) + " | confere=" + _sim_nao_terminal(anatel.get("modelo_confere_base")))
    log("anatel", "Resultado      : " + _valor_terminal(anatel.get("situacao_anatel"), "NAO_INFORMADO") + " — " + _valor_terminal(anatel.get("motivo_anatel"), "sem motivo"))

def _log_auditoria_classificacao(linha: dict[str, Any]) -> None:
    log("classificação", "Destino        : " + _valor_terminal(linha.get("classificacao"), "NÃO DEFINIDO"))
    log("classificação", "Motivo         : " + _valor_terminal(linha.get("motivo_validacao"), "sem motivo registrado"))


# ============================================================
# URL / NAVEGADOR
# ============================================================

def _url_busca(query: str) -> str:
    termo = quote_plus(query or "smartphone")
    return f"https://www.amazon.com.br/s?k={termo}"

def _conectar_chrome_existente(playwright, porta: int = 9225) -> BrowserContext:
    endereco = f"http://127.0.0.1:{porta}"
    log("chrome", f"Conectando ao Chrome já aberto em {endereco}...")
    try:
        navegador = playwright.chromium.connect_over_cdp(endereco, timeout=20000)
    except Exception as exc:
        raise RuntimeError(
            "Não foi possível conectar ao Chrome. Abra o Chrome antes "
            f"com --remote-debugging-port={porta}. Detalhe: {exc}"
        ) from exc

    if not navegador.contexts:
        raise RuntimeError("Nenhum contexto de navegador foi encontrado via CDP.")
    
    log("chrome", "Chrome conectado via CDP: OK")
    return navegador.contexts[0]

def _detectar_bloqueio_amazon(page: Page) -> bool:
    try:
        url = (page.url or "").lower()
        if any(sinal in url for sinal in ["captcha", "validatecaptcha", "robot"]):
            return True
        txt = page.locator("body").inner_text(timeout=1800).lower()
        sinais_texto = ["digite os caracteres", "insira os caracteres", "não somos robôs", "robot check"]
        return any(sinal in txt for sinal in sinais_texto)
    except Exception:
        return False

def _tratar_bloqueio_se_preciso(page: Page) -> bool:
    if not _detectar_bloqueio_amazon(page):
        return True

    bloco("bloqueio amazon")
    log("bloqueio amazon", "Possível CAPTCHA/bloqueio detectado.")
    try:
        input("[amazon] Resolva o CAPTCHA no navegador aberto e pressione Enter para continuar...")
    except Exception:
        return False

    try:
        page.wait_for_load_state("domcontentloaded", timeout=15000)
    except Exception:
        pass
    page.wait_for_timeout(1500)

    liberado = not _detectar_bloqueio_amazon(page)
    log("bloqueio amazon", "Página liberada." if liberado else "Ainda parece bloqueada.")
    return liberado

def _inicio_lento(page: Page, query: str, url: str | None) -> None:
    page.goto("https://www.amazon.com.br/", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2500)
    fechar_modais_amazon(page)
    _tratar_bloqueio_se_preciso(page)

    destino = url or _url_busca(query)
    log("busca", f"Abrindo listagem Amazon: {destino}")
    page.goto(destino, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3500)
    fechar_modais_amazon(page)
    _tratar_bloqueio_se_preciso(page)

    try:
        page.wait_for_load_state("networkidle", timeout=12000)
    except Exception:
        pass
    page.wait_for_timeout(1500)

# ============================================================
# LISTAGEM / LINKS
# ============================================================

def _normalizar_link_amazon(href: str, base_url: str = "https://www.amazon.com.br") -> str:
    href = (href or "").split("#")[0].strip()
    if not href:
        return ""
    href_abs = urljoin(base_url, href)
    if "amazon.com.br" not in href_abs.lower():
        return ""
    m = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})(?:[/?]|$)", href_abs, flags=re.IGNORECASE)
    if m:
        return f"https://www.amazon.com.br/dp/{m.group(1).upper()}"
    if "/dp/" in href_abs or "/gp/product/" in href_abs:
        return href_abs.split("?")[0]
    return ""

def _clicar_ver_todos_resultados_se_existir(page: Page) -> None:
    seletores = [
        "a#apb-desktop-browse-search-see-all[href]",
        "a:has-text('Ver todos os resultados')",
        "a:has-text('Ver mais resultados')",
    ]
    for seletor in seletores:
        try:
            loc = page.locator(seletor).first
            if loc.count() and loc.is_visible(timeout=1200):
                href = (loc.get_attribute("href") or "").strip()
                loc.scroll_into_view_if_needed(timeout=2500)
                try:
                    loc.click(timeout=3500)
                except Exception:
                    if href:
                        page.goto(urljoin(page.url, href), wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(2200)
                fechar_modais_amazon(page)
                _tratar_bloqueio_se_preciso(page)
                return
        except Exception:
            continue

def _coletar_links_produtos(page: Page, max_scrolls: int = 14) -> list[str]:
    script = r"""
    () => {
      const out = new Set();
      const anchors = Array.from(document.querySelectorAll('a[href]'));
      for (const a of anchors) {
        const href = (a.href || '').split('#')[0].trim();
        if (!href || !href.includes('amazon.com.br')) continue;
        if (!(/\/dp\/[A-Z0-9]{10}/i.test(href) || /\/gp\/product\/[A-Z0-9]{10}/i.test(href))) continue;

        const txt = (a.innerText || a.textContent || '').replace(/\s+/g, ' ').trim().toLowerCase();
        if (txt.includes('próximo') || txt.includes('proximo')) continue;
        out.add(href);
      }
      return Array.from(out);
    }
    """
    links: list[str] = []
    try:
        novos = page.evaluate(script) or []
        for href in novos:
            link = _normalizar_link_amazon(str(href or ""), base_url=page.url)
            if link and link not in links:
                links.append(link)
    except Exception:
        pass
    return links

# ============================================================
# PAGINAÇÃO
# ============================================================

def _clicar_proxima_visivel(page: Page, url_antes: str) -> bool:
    seletores = [
        "a.s-pagination-next[href]",
        "a[aria-label*='próxima página'][href]",
        "a[aria-label*='proxima pagina'][href]",
        "a:has-text('Próximo')",
        "a:has-text('Proximo')",
    ]
    for seletor in seletores:
        try:
            loc = page.locator(seletor).first
            if not loc.count() or not loc.is_visible(timeout=900):
                continue
            classe = (loc.get_attribute("class") or "").lower()
            if "disabled" in classe:
                return False
            href = (loc.get_attribute("href") or "").strip()
            loc.scroll_into_view_if_needed(timeout=3000)
            try:
                loc.click(timeout=4500)
            except Exception:
                if href:
                    page.goto(urljoin(page.url, href), wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2500)
            fechar_modais_amazon(page)
            _tratar_bloqueio_se_preciso(page)
            return page.url.split("#")[0].rstrip("/") != str(url_antes or "").split("#")[0].rstrip("/")
        except Exception:
            continue
    return False

def _ir_proxima_pagina(page: Page) -> bool:
    url_antes = page.url
    fechar_modais_amazon(page)
    if _clicar_proxima_visivel(page, url_antes):
        return True
    
    for _ in range(10):
        try:
            page.mouse.wheel(0, 1000)
        except Exception:
            pass
        page.wait_for_timeout(800)
        if _clicar_proxima_visivel(page, url_antes):
            return True
    return False

# ============================================================
# FLUXO PRINCIPAL
# ============================================================

def rodar_playwright_amazon(
    query: str = "smartphone",
    queries: list[str] | None = None,
    limite: int = 0,
    base_anatel: BaseAnatel | None = None,
    url: str | None = None,
    saida: str | Path | None = None,
    max_paginas: int = 0,
    analisar_vendedor: bool = True,
    pausar_inicio: bool = True,
    porta_chrome: int = 9225,
) -> dict[str, Any]:

    pasta_saida = criar_pastas_saida(saida)
    linhas: list[dict[str, Any]] = []
    comentarios_linhas: list[dict[str, Any]] = []
    vendedores_linhas: list[dict[str, Any]] = []

    buscas = queries or [query]
    urls_processadas: set[str] = set()
    total_processados = 0
    total_descartados = 0

    with sync_playwright() as p:
        context = _conectar_chrome_existente(p, porta=porta_chrome)
        page = context.pages[0] if context.pages else context.new_page()
        page.set_default_timeout(12000)
        page.set_default_navigation_timeout(60000)

        try:
            primeira_busca = buscas[0]
            _inicio_lento(page, query=primeira_busca, url=url)
            _clicar_ver_todos_resultados_se_existir(page)

            if pausar_inicio:
                secao("Pausa manual")
                print("Resolva login ou captcha no Chrome e deixe a listagem aberta.")
                input("Pressione ENTER para iniciar a coleta... ")

            for indice_busca, consulta_atual in enumerate(buscas, start=1):
                if limite > 0 and total_processados >= limite:
                    break
                
                if not url and indice_busca > 1:
                    destino = _url_busca(consulta_atual)
                    page.goto(destino, wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_timeout(3000)
                    _tratar_bloqueio_se_preciso(page)
                    _clicar_ver_todos_resultados_se_existir(page)

                pagina_atual = 1
                while True:
                    if limite > 0 and total_processados >= limite:
                        break
                    if max_paginas > 0 and pagina_atual > max_paginas:
                        break

                    links_pagina = _coletar_links_produtos(page)
                    links_novos = [l for l in links_pagina if l not in urls_processadas]
                    
                    if not links_novos:
                        if not _ir_proxima_pagina(page):
                            break
                        pagina_atual += 1
                        continue

                    for href in links_novos:
                        if limite > 0 and total_processados >= limite:
                            break
                        
                        urls_processadas.add(href)
                        total_processados += 1
                        
                        bloco(f"PRODUTO {total_processados}/{limite if limite > 0 else '∞'}")
                        log("produto", href)
                        
                        prod_page = context.new_page()
                        prod_page.set_default_timeout(12000)
                        
                        try:
                            prod_page.goto(href, wait_until="domcontentloaded", timeout=60000)
                            prod_page.wait_for_timeout(2600)
                            fechar_modais_amazon(prod_page)
                            _tratar_bloqueio_se_preciso(prod_page)
                            
                            dados = extrair_produto_amazon(prod_page)
                            momento = datetime.now().astimezone()

                            log("comentários", f"Capturados: {len(dados.comentarios or [])}")

                            mini_info = analisar_mini_celular_amazon(dados, maior_max_cm=12.0, largura_max_cm=5.5)
                            
                            analise_dimensional = {
                                "dimensoes_confiaveis": "SIM" if mini_info.get("mini_maior_cm") else "NAO",
                                "dentro_limite_dimensional": "SIM" if mini_info.get("mini_status") == "MANTER" else "NAO",
                                "altura_cm": mini_info.get("mini_maior_cm"),
                                "largura_cm": mini_info.get("mini_largura_cm"),
                                "espessura_cm": mini_info.get("mini_espessura_cm"),
                                "origem_dimensoes": str(mini_info.get("mini_evidencia") or "")[:50] if mini_info.get("mini_evidencia") else "não localizada"
                            }

                            label_anatel, modelo_anatel = _modelo_decisivo_capturado(dados)
                            anatel = analisar_situacao_anatel(dados.codigo_anatel_principal, dados.marca, modelo_anatel, base_anatel)

                            classificacao = classificar_produto(dados, analise_dimensional, anatel)
                            classificacao_final = classificacao.get("classificacao", "DESCARTADO")

                            linha = {
                                "pid": gerar_id(dados.titulo, dados.url),
                                "marketplace_id": "1",
                                "marketplace": "amazon",
                                "titulo": dados.titulo,
                                "link": dados.url,
                                "codigo_anatel_principal": dados.codigo_anatel_principal,
                                "marca": dados.marca,
                                "preco": dados.preco,
                                "modelo": dados.modelo,
                                "modelo_decisivo": modelo_anatel,
                                "classificacao": classificacao_final,
                                "status_validacao": classificacao_final,
                                "motivo_validacao": classificacao.get("motivo_classificacao", ""),
                                "dimensoes_encontradas": f"{mini_info.get('mini_maior_cm', 'N/A')} x {mini_info.get('mini_largura_cm', 'N/A')} cm" if mini_info.get('mini_maior_cm') else "NAO ENCONTRADAS",
                            }
                            linha.update(metadados_captura(pasta_saida, momento))

                            # Auditoria no Terminal 
                            _log_auditoria_dimensoes(analise_dimensional)
                            _log_auditoria_anatel(dados, anatel, modelo_anatel)
                            _log_auditoria_classificacao(linha)
                            
                            # TRAVA DE SALVAMENTO: Descartados não devem poluir o arquivo!
                            if classificacao_final == "DESCARTADO":
                                total_descartados += 1
                                continue
                            
                            if analisar_vendedor:
                                print("")
                                vendedor = analisar_vendedor_amazon(prod_page, context=context, saida_base=pasta_saida, pid=linha["pid"])
                                sellers_lista = vendedor.pop("__sellers_list", [])
                                linha.update(vendedor)
                                for seller_item in sellers_lista:
                                    vendedores_linhas.append({"pid": linha["pid"], "url": linha["link"], **seller_item})

                            linhas.append(linha)
                            
                            for i, comentario in enumerate(dados.comentarios or [], start=1):
                                comentarios_linhas.append({
                                    "pid": linha["pid"],
                                    "marketplace_id": "1",
                                    "url": linha["link"],
                                    "comentario_ordem": i,
                                    "comment": comentario,
                                    "created_at": linha.get("created_at", "")
                                })

                            salvar_parquet_incremental(pasta_saida, linhas, comentarios_linhas, vendedores_linhas)

                        except Exception as exc:
                            log("erro", f"Falha ao processar anúncio: {exc}")
                        finally:
                            prod_page.close()
                    
                    if not _ir_proxima_pagina(page):
                        break
                    pagina_atual += 1
                
                if url:
                    break
        finally:
            log("chrome", "Execução finalizada. O Chrome continuará aberto.")

    return {
        "pasta_saida": str(pasta_saida.resolve()), 
        "total_visitados": total_processados,
        "total_descartados": total_descartados,
        "total_produtos_no_parquet": len(linhas)
    }