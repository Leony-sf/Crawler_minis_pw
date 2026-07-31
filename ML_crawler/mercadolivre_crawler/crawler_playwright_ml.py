from __future__ import annotations

from pathlib import Path
from urllib.parse import quote_plus
import time
from typing import Any

import pandas as pd
from playwright.sync_api import sync_playwright, Page, BrowserContext

from .base_anatel import BaseAnatel
from .extracao import (
    analisar_mini_celular,
    capturar_comentarios,
    dados_para_linha,
    extrair_produto,
    fechar_modais_leves,
    validar_produto,
)
from .utils import arquivo_seguro, bloco, criar_pastas_saida, gerar_id, log, secao


# ============================================================
# URL / INÍCIO
# ============================================================

def _url_busca(query: str, somente_internacional: bool = False) -> str:
    termo = quote_plus(query or "celular").replace("+", "-")
    url = f"https://lista.mercadolivre.com.br/{termo}"
    if somente_internacional:
        url += "_Filters_OMNI*COMPRA*INTERNACIONAL_NoIndex_True"
    return url


def _inicio_lento(page: Page, query: str, url: str | None, somente_internacional: bool = False) -> None:
    page.goto("https://www.mercadolivre.com.br/", wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(2500)
    fechar_modais_leves(page)
    _fechar_cookies_se_aparecer(page)
    page.wait_for_timeout(1200)

    destino = url or _url_busca(query, somente_internacional)
    log("busca", f"Abrindo listagem: {destino}")

    page.goto(destino, wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(3500)
    fechar_modais_leves(page)
    _fechar_cookies_se_aparecer(page)

    try:
        page.wait_for_load_state("networkidle", timeout=15000)
    except Exception:
        pass

    page.wait_for_timeout(1500)


# ============================================================
# LISTAGEM / LINKS
# ============================================================

def _coletar_links_produtos(page: Page, max_scrolls: int = 16, alvo_minimo: int = 35) -> list[str]:
    script = r"""
    () => {
      const out = new Set();
      const anchors = Array.from(document.querySelectorAll('a[href]'));

      for (const a of anchors) {
        const href = (a.href || '').split('#')[0].trim();
        if (!href) continue;
        if (!href.includes('mercadolivre.com.br')) continue;
        if (href.includes('/questions') || href.includes('/reviews')) continue;

        const texto = [a.innerText, a.textContent, a.getAttribute('title'), a.getAttribute('aria-label')]
          .join(' ')
          .replace(/\s+/g, ' ')
          .trim()
          .toLowerCase();

        const pareceProduto = href.includes('/p/')
          || href.includes('/up/')
          || /\/MLB-?\d+/i.test(href)
          || /\bMLBU?\d+\b/i.test(href);

        const parecePaginacao = texto.includes('seguinte')
          || texto.includes('próxima')
          || texto.includes('proxima')
          || texto.includes('siguiente')
          || texto.includes('next')
          || href.includes('_Desde_');

        if (pareceProduto && !parecePaginacao) {
          out.add(href);
        }
      }

      return Array.from(out);
    }
    """

    links: list[str] = []
    sem_novos = 0
    ultima_qtd = 0

    try:
        page.evaluate("() => window.scrollTo(0, 0)")
        page.wait_for_timeout(600)
    except Exception:
        pass

    for tentativa in range(1, max_scrolls + 1):
        try:
            novos = page.evaluate(script) or []
            for href in novos:
                href = str(href or "").split("#")[0].strip()
                if href and href not in links:
                    links.append(href)
        except Exception:
            pass

        log("listagem", f"Coleta {tentativa}/{max_scrolls}: {len(links)} links de produto")

        if len(links) >= alvo_minimo and len(links) == ultima_qtd:
            break

        if len(links) == ultima_qtd:
            sem_novos += 1
        else:
            sem_novos = 0
            ultima_qtd = len(links)

        if sem_novos >= 4:
            break

        try:
            page.mouse.wheel(0, 950)
            page.wait_for_timeout(650)
        except Exception:
            break

    return links


# ============================================================
# PAGINAÇÃO
# ============================================================

def _fechar_cookies_se_aparecer(page: Page) -> None:
    candidatos = ["Aceitar cookies", "Aceitar todos", "Entendi", "Concordo"]

    for texto in candidatos:
        try:
            botao = page.get_by_role("button", name=texto, exact=False).first
            if botao.count() and botao.is_visible(timeout=800):
                botao.click(timeout=1500)
                page.wait_for_timeout(700)
                log("cookies", f"Banner fechado com: {texto}")
                return
        except Exception:
            pass

def _clicar_seguinte_visivel(page: Page, url_antes: str) -> bool:
    seletores_seguinte = [
        "li.andes-pagination__button--next a",
        "li.andes-pagination__button--next button",
        "a.andes-pagination__link:has-text('Seguinte')",
        "a:has-text('Seguinte')",
        "button:has-text('Seguinte')",
        "a[title*='Seguinte']",
        "a[aria-label*='Seguinte']",
        "[class*='pagination'] a:has-text('Seguinte')",
        "[class*='pagination'] button:has-text('Seguinte')",
        "a:has-text('Próxima')",
        "a:has-text('Proxima')",
        "a:has-text('Siguiente')",
    ]

    for seletor in seletores_seguinte:
        try:
            loc = page.locator(seletor)
            total = loc.count()
        except Exception:
            total = 0

        for i in range(total):
            try:
                item = loc.nth(i)
                if not item.is_visible(timeout=800):
                    continue

                classe = " ".join([item.get_attribute("class") or "", item.evaluate("el => el.parentElement ? el.parentElement.className || '' : ''")]).lower()
                aria_disabled = (item.get_attribute("aria-disabled") or "").lower()
                href = (item.get_attribute("href") or "").strip()

                if "disabled" in classe or aria_disabled == "true":
                    log("paginação", "Botão 'Seguinte' encontrado, mas está desabilitado.")
                    return False

                item.scroll_into_view_if_needed(timeout=3000)
                page.wait_for_timeout(500)
                log("paginação", f"Botão 'Seguinte' encontrado pelo seletor: {seletor}")

                try:
                    item.click(timeout=4000)
                except Exception:
                    handle = item.element_handle()
                    if handle:
                        page.evaluate("(el) => el.click()", handle)
                    else:
                        raise

                try:
                    page.wait_for_url(lambda url: str(url) != str(url_antes), timeout=20000)
                except Exception:
                    if href:
                        log("paginação", "Clique não mudou URL rapidamente. Abrindo href diretamente.")
                        page.goto(href, wait_until="domcontentloaded", timeout=45000)

                try:
                    page.wait_for_load_state("domcontentloaded", timeout=20000)
                except Exception:
                    pass

                try:
                    page.wait_for_load_state("networkidle", timeout=12000)
                except Exception:
                    pass

                page.wait_for_timeout(2500)
                fechar_modais_leves(page)
                _fechar_cookies_se_aparecer(page)

                mudou = page.url.split("#")[0].rstrip("/") != str(url_antes or "").split("#")[0].rstrip("/")
                if mudou:
                    log("paginação", f"Próxima página carregada: {page.url}")
                    return True
            except Exception:
                continue

    return False


def _ir_proxima_pagina(page: Page, pagina_atual: int | None = None) -> bool:
    bloco("paginação")
    if pagina_atual is not None:
        log("paginação", f"Procurando botão 'Seguinte' após finalizar a página {pagina_atual}.")
    else:
        log("paginação", "Procurando botão 'Seguinte' da paginação.")

    _fechar_cookies_se_aparecer(page)
    url_antes = page.url

    if _clicar_seguinte_visivel(page, url_antes):
        return True

    for tentativa in range(1, 13):
        log("paginação", f"Descendo para localizar paginação. Tentativa {tentativa}/12")
        try:
            page.mouse.wheel(0, 850)
        except Exception:
            try:
                page.evaluate("() => window.scrollBy(0, 850)")
            except Exception:
                pass

        page.wait_for_timeout(750)
        _fechar_cookies_se_aparecer(page)

        if _clicar_seguinte_visivel(page, url_antes):
            return True

    log("paginação", "Não encontrei o botão 'Seguinte'. Encerrando paginação.")
    return False


# ============================================================
# ARQUIVOS / PARQUET / PRINTS
# ============================================================

MINI_COLUNAS_NUMERICAS = [
    "mini_maior_cm", "mini_largura_cm", "mini_espessura_cm",
    "mini_limite_maior_cm", "mini_limite_largura_cm",
]

def _preparar_dataframe_parquet(linhas: list[dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(linhas)
    if df.empty:
        return df
    for col in MINI_COLUNAS_NUMERICAS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col].replace("", None), errors="coerce").astype("float64")
    for col in df.columns:
        if col not in MINI_COLUNAS_NUMERICAS:
            df[col] = df[col].where(pd.notna(df[col]), "").astype(str)
    return df

def _salvar_print(page: Page, saida_base: Path, linha: dict[str, Any]) -> None:
    pid = linha.get("pid") or gerar_id(linha.get("titulo"), linha.get("url"))
    status = str(linha.get("status_validacao") or linha.get("status") or "").upper()
    pasta = "irregulares" if status == "IRREGULAR" else "regulares"
    nome = arquivo_seguro(f"{pid}_{linha.get('titulo', 'produto')}", 100)
    caminho = saida_base / "prints" / pasta / f"{nome}.png"

    try:
        page.screenshot(path=str(caminho), full_page=True)
        log("arquivos", f"Print salvo em: {caminho}")
    except Exception as exc:
        log("arquivos", f"Falha ao salvar print: {exc}")

def _salvar_resultados(
    saida: Path,
    linhas: list[dict[str, Any]],
    comentarios: list[dict[str, Any]],
    descartados_mini: list[dict[str, Any]] | None = None,
    suspeitos_mini: list[dict[str, Any]] | None = None,
) -> None:
    df = _preparar_dataframe_parquet(linhas)
    df.to_parquet(saida / "products.parquet", index=False)
    df.to_parquet(saida / "resultados.parquet", index=False)

    dfc = _preparar_dataframe_parquet(comentarios)
    dfc.to_parquet(saida / "comments.parquet", index=False)

    if descartados_mini is not None:
        dfd = _preparar_dataframe_parquet(descartados_mini)
        dfd.to_parquet(saida / "products_descartados_mini.parquet", index=False)

    if suspeitos_mini is not None:
        dfs = _preparar_dataframe_parquet(suspeitos_mini)
        dfs.to_parquet(saida / "products_suspeitos_mini.parquet", index=False)


# ============================================================
# CONTEXTO / NAVEGADOR
# ============================================================

def _abrir_contexto_chrome_persistente(p, headless: bool = False) -> BrowserContext:
    profile_dir = Path("chrome_profiles") / "mercadolivre_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)
    return p.chromium.launch_persistent_context(
        user_data_dir=str(profile_dir),
        headless=headless,
        viewport={"width": 1366, "height": 900},
        locale="pt-BR",
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        args=["--start-maximized", "--disable-blink-features=AutomationControlled"],
        slow_mo=140,
    )

def _clicar_ver_mais_resultados_se_existir(page: Page) -> None:
    candidatos = ["Ver mais resultados", "Mostrar mais resultados", "Ver mais", "Mais resultados"]
    for texto in candidatos:
        try:
            loc = page.get_by_text(texto, exact=False).first
            if loc.count() and loc.is_visible(timeout=1200):
                loc.scroll_into_view_if_needed(timeout=2500)
                page.wait_for_timeout(800)
                loc.click(timeout=3000)
                page.wait_for_load_state("domcontentloaded", timeout=20000)
                try:
                    page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass
                page.wait_for_timeout(2000)
                log("listagem", f"Cliquei em: {texto}")
                return
        except Exception:
            continue
    log("listagem", "Botão 'Ver mais resultados' não apareceu.")

def _sem_limite(valor: int | None) -> bool:
    try:
        return int(valor or 0) <= 0
    except Exception:
        return True

def _conectar_chrome_real_ml(p) -> BrowserContext:
    log("chrome", "Conectando ao Chrome real na porta 9225...")
    browser = p.chromium.connect_over_cdp("http://127.0.0.1:9225")
    if browser.contexts:
        context = browser.contexts[0]
    else:
        context = browser.new_context(viewport={"width": 1366, "height": 900}, locale="pt-BR")
    log("chrome", "Conectado ao Chrome real com sucesso.")
    return context


# ============================================================
# FLUXO PRINCIPAL
# ============================================================

def rodar_playwright_mercadolivre(
    query: str = "smartphone",
    queries: list[str] | None = None,
    limite: int = 5,
    limite_por_query: int = 0,
    base_anatel: BaseAnatel | None = None,
    headless: bool = False,
    url: str | None = None,
    saida: str | Path | None = None,
    max_paginas: int = 0,
    mini_celulares: bool = False,
    mini_maior_cm: float = 12.0,
    mini_largura_cm: float = 5.5,
    mini_manter_sem_medida: bool = False,
    somente_internacional: bool = False, # <-- NOVA FLAG DE IMPORTAÇÃO
) -> dict[str, Any]:
    
    saida_base = criar_pastas_saida(saida)
    linhas: list[dict[str, Any]] = []
    comentarios_linhas: list[dict[str, Any]] = []
    descartados_mini: list[dict[str, Any]] = []
    suspeitos_mini: list[dict[str, Any]] = []

    if url:
        consultas_busca = [(query or "URL direta", url)]
    else:
        consultas_raw = queries or [query]
        consultas_busca = []
        vistos_consultas: set[str] = set()
        for q in consultas_raw:
            q = str(q or "").strip()
            if not q:
                continue
            chave = q.lower()
            if chave in vistos_consultas:
                continue
            vistos_consultas.add(chave)
            consultas_busca.append((q, _url_busca(q, somente_internacional)))
        if not consultas_busca:
            consultas_busca = [("celular", _url_busca("celular", somente_internacional))]

    url_busca = consultas_busca[0][1]
    urls_processadas: set[str] = set()
    total_processados = 0

    sem_limite_produtos = _sem_limite(limite)
    sem_limite_paginas = _sem_limite(max_paginas)
    limite_txt = "sem limite" if sem_limite_produtos else str(limite)
    max_paginas_txt = "sem limite" if sem_limite_paginas else str(max_paginas)

    secao("Mercado Livre Playwright")
    log("crawler", f"URL inicial: {url_busca}")
    log("crawler", f"Filtro Internacional: {'ATIVADO' if somente_internacional else 'DESATIVADO'}")
    log("crawler", f"Total de buscas engatilhadas: {len(consultas_busca)}")
    log("crawler", f"Limite total geral: {limite_txt}")
    if limite_por_query > 0:
        log("crawler", f"Limite rotativo por pesquisa: {limite_por_query} anúncios")
    log("crawler", f"Máximo de páginas: {max_paginas_txt}")

    with sync_playwright() as p:
        context = _conectar_chrome_real_ml(p)
        page = context.pages[0] if context.pages else context.new_page()
        page.set_default_timeout(12000)
        page.set_default_navigation_timeout(45000)

        try:
            _inicio_lento(page, query=consultas_busca[0][0], url=consultas_busca[0][1], somente_internacional=somente_internacional)

            secao("Pausa manual Mercado Livre")
            log("login", "Use o Chrome real aberto para resolver login/captcha se necessário.")
            log("login", "Deixe o navegador exatamente na listagem de celulares.")
            input("[login] Quando estiver pronto, pressione ENTER para iniciar a coleta... ")

            fechar_modais_leves(page)
            _fechar_cookies_se_aparecer(page)
            _clicar_ver_mais_resultados_se_existir(page)


            for consulta_indice, (consulta_query, consulta_url) in enumerate(consultas_busca, start=1):
                if not sem_limite_produtos and total_processados >= int(limite):
                    log("busca", f"Limite geral de {limite} atingido.")
                    break

                processados_nesta_query = 0 

                secao(f"BUSCA {consulta_indice}/{len(consultas_busca)}")
                log("busca", f"Termo atual: {consulta_query}")
                log("busca", f"URL da busca: {consulta_url}")

                if consulta_indice > 1:
                    page.goto(consulta_url, wait_until="domcontentloaded", timeout=45000)
                    page.wait_for_timeout(2500)
                    try:
                        page.wait_for_load_state("networkidle", timeout=12000)
                    except Exception:
                        pass
                    fechar_modais_leves(page)
                    _fechar_cookies_se_aparecer(page)
                    _clicar_ver_mais_resultados_se_existir(page)

                pagina_atual = 1
                paginas_sem_links_novos = 0

                while True:
                    if limite_por_query > 0 and processados_nesta_query >= limite_por_query:
                        break

                    if not sem_limite_produtos and total_processados >= int(limite):
                        break

                    if not sem_limite_paginas and pagina_atual > int(max_paginas):
                        break

                    secao(f"PÁGINA {pagina_atual}")
                    bloco("listagem")
                    log("listagem", f"URL atual: {page.url}")
                    log("listagem", "Coletando links dos produtos da página atual.")

                    links_pagina = _coletar_links_produtos(page)

                    try:
                        page.evaluate("() => window.scrollTo(0, 0)")
                        page.wait_for_timeout(500)
                    except Exception:
                        pass

                    links_novos: list[str] = []
                    vistos_pagina: set[str] = set()

                    for href in links_pagina:
                        href_limpo = str(href or "").split("#")[0].strip()
                        if not href_limpo or href_limpo in vistos_pagina or href_limpo in urls_processadas:
                            continue
                        vistos_pagina.add(href_limpo)
                        links_novos.append(href_limpo)

                    log("listagem", f"Links novos para processar: {len(links_novos)}")

                    if not links_novos:
                        paginas_sem_links_novos += 1
                        log("paginação", f"Nenhum produto novo. Tentativas: {paginas_sem_links_novos}/3")
                        if paginas_sem_links_novos >= 3:
                            break
                        if not _ir_proxima_pagina(page, pagina_atual=pagina_atual):
                            break
                        pagina_atual += 1
                        continue

                    paginas_sem_links_novos = 0

                    for indice_pagina, href in enumerate(links_novos, start=1):
                        
                        if limite_por_query > 0 and processados_nesta_query >= limite_por_query:
                            log("busca", f"Limite rotativo de {limite_por_query} anúncios por pesquisa atingido! Pulando termo.")
                            break
                            
                        if not sem_limite_produtos and total_processados >= int(limite):
                            break

                        urls_processadas.add(href)
                        total_processados += 1
                        processados_nesta_query += 1

                        secao(f"PÁGINA {pagina_atual} | PRODUTO {indice_pagina}/{len(links_novos)}")
                        bloco("navegação")
                        log("navegação", f"Abrindo anúncio: {href}")

                        prod_page = context.new_page()
                        prod_page.set_default_timeout(12000)
                        prod_page.set_default_navigation_timeout(45000)

                        try:
                            prod_page.goto(href, wait_until="domcontentloaded", timeout=45000)
                            prod_page.wait_for_timeout(2200)

                            try:
                                prod_page.wait_for_load_state("networkidle", timeout=10000)
                            except Exception:
                                pass

                            dados = extrair_produto(prod_page, capturar_reviews=not mini_celulares)

                            mini_info: dict[str, Any] = {}
                            if mini_celulares:
                                mini_info = analisar_mini_celular(
                                    dados,
                                    maior_max_cm=mini_maior_cm,
                                    largura_max_cm=mini_largura_cm,
                                )

                                mini_status = str(mini_info.get("mini_status") or "")
                                manter_por_medida = mini_status == "MANTER"
                                manter_sem_medida = mini_manter_sem_medida and mini_status == "REVISAR_SEM_MEDIDA"
                                eh_suspeito_manual = mini_status == "SUSPEITO_MANUAL" or str(mini_info.get("mini_suspeito_manual") or "").upper() == "SIM"

                                log("mini celular", f"Status: {mini_status}")
                                log("mini celular", f"Motivo: {mini_info.get('mini_motivo')}")

                                if not (manter_por_medida or manter_sem_medida):
                                    destino_suspeito = eh_suspeito_manual
                                    linha_destino = dados_para_linha(
                                        dados,
                                        {
                                            "status_validacao": "SUSPEITO_MANUAL" if destino_suspeito else "FORA_ESCOPO_MINI",
                                            "motivo_validacao": mini_info.get("mini_motivo", "Fora do recorte"),
                                            "irregularity_reasons": "",
                                            "warnings": mini_info.get("mini_motivo", ""),
                                            "modo_match_base": "mini_suspeito_manual" if destino_suspeito else "mini_descartado",
                                        },
                                    )
                                    linha_destino.update(mini_info)
                                    linha_destino["created_at"] = time.strftime("%Y-%m-%d")
                                    linha_destino["query_busca"] = consulta_query
                                    if destino_suspeito:
                                        suspeitos_mini.append(linha_destino)
                                    else:
                                        descartados_mini.append(linha_destino)
                                    _salvar_resultados(saida_base, linhas, comentarios_linhas, descartados_mini, suspeitos_mini)
                                    continue

                                dados.comentarios = capturar_comentarios(prod_page, limite=10)

                            validacao = validar_produto(dados, base_anatel)
                            linha_produto = dados_para_linha(dados, validacao)
                            if mini_info:
                                linha_produto.update(mini_info)
                            linha_produto["created_at"] = time.strftime("%Y-%m-%d")
                            linha_produto["query_busca"] = consulta_query
                            linhas.append(linha_produto)

                            if mini_celulares and str(linha_produto.get("mini_suspeito_manual") or "").upper() == "SIM":
                                suspeitos_mini.append(dict(linha_produto))

                            for i, comentario in enumerate(dados.comentarios or [], start=1):
                                comentarios_linhas.append(
                                    {
                                        "pid": linha_produto["pid"],
                                        "marketplace_id": "2",
                                        "url": linha_produto["url"],
                                        "comentario_ordem": i,
                                        "comment": comentario,
                                        "created_at": linha_produto["created_at"],
                                        "query_busca": consulta_query,
                                    }
                                )

                            log("resultado", f"Situação: {linha_produto.get('status') or linha_produto.get('status_validacao')}")
                            _salvar_print(prod_page, saida_base, linha_produto)
                            _salvar_resultados(saida_base, linhas, comentarios_linhas, descartados_mini, suspeitos_mini)

                        except Exception as exc:
                            log("erro", f"Falha ao processar produto: {exc}")
                        finally:
                            try:
                                prod_page.close()
                            except Exception:
                                pass
    
                    if limite_por_query > 0 and processados_nesta_query >= limite_por_query:
                        break

                    if not sem_limite_produtos and total_processados >= int(limite):
                        break

                    if not sem_limite_paginas and pagina_atual >= int(max_paginas):
                        break

                    if not _ir_proxima_pagina(page, pagina_atual=pagina_atual):
                        break

                    pagina_atual += 1

        finally:
            try:
                context.close()
            except Exception:
                pass

    _salvar_resultados(saida_base, linhas, comentarios_linhas, descartados_mini, suspeitos_mini)

    resumo = {
        "saida": str(saida_base.resolve()),
        "total_produtos": len(linhas),
        "mini_mantidos": sum(1 for l in linhas if str(l.get("mini_status") or "") == "MANTER"),
        "mini_descartados": len(descartados_mini),
        "mini_suspeitos_manual": len(suspeitos_mini),
        "buscas_total": len(consultas_busca),
    }

    secao("Resumo Playwright")
    for chave, valor in resumo.items():
        log("resumo", f"{chave}: {valor}")

    return resumo