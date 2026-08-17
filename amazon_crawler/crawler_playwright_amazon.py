from __future__ import annotations

from datetime import datetime
from pathlib import Path
from urllib.parse import quote_plus, urljoin
import re
import time
from typing import Any

import pandas as pd
from playwright.sync_api import BrowserContext, Page, sync_playwright

from .base_anatel import BaseAnatel
from .extracao import dados_para_linha, validar_produto
from .extracao_amazon import analisar_mini_celular_amazon, capturar_comentarios_amazon, extrair_produto_amazon, fechar_modais_amazon
from .seller_amazon import analisar_vendedor_amazon
from .utils import arquivo_seguro, bloco, criar_pastas_saida, gerar_id, log, secao


# ============================================================
# URL / NAVEGADOR
# ============================================================


def _url_busca(query: str) -> str:
    termo = quote_plus(query or "smartphone")
    return f"https://www.amazon.com.br/s?k={termo}"


def _saida_padrao_amazon(saida: str | Path | None) -> Path:
    # Quando saida=None, utils.criar_pastas_saida cria dentro de amazon_crawler/saidas.
    return criar_pastas_saida(saida)


def _abrir_contexto_chrome_persistente(p, headless: bool = False) -> BrowserContext:
    profile_dir = Path("chrome_profiles") / "amazon_profile"
    profile_dir.mkdir(parents=True, exist_ok=True)

    return p.chromium.launch_persistent_context(
        user_data_dir=str(profile_dir),
        headless=headless,
        viewport={"width": 1366, "height": 900},
        locale="pt-BR",
        timezone_id="America/Sao_Paulo",
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        args=[
            "--start-maximized",
            "--disable-blink-features=AutomationControlled",
        ],
        slow_mo=130,
    )


def _detectar_bloqueio_amazon(page: Page) -> bool:
    try:
        url = (page.url or "").lower()
    except Exception:
        url = ""

    sinais_url = ["captcha", "validatecaptcha", "errors/validatecaptcha", "robot"]
    if any(sinal in url for sinal in sinais_url):
        return True

    try:
        txt = page.locator("body").inner_text(timeout=1800).lower()
    except Exception:
        txt = ""

    sinais_texto = [
        "digite os caracteres",
        "insira os caracteres",
        "enter the characters",
        "não somos robôs",
        "nao somos robos",
        "robot check",
        "desculpe, precisamos ter certeza",
    ]
    return any(sinal in txt for sinal in sinais_texto)


def _tratar_bloqueio_se_preciso(page: Page, headless: bool) -> bool:
    if not _detectar_bloqueio_amazon(page):
        return True

    bloco("bloqueio amazon")
    log("bloqueio amazon", "Possível CAPTCHA/bloqueio detectado.")

    if headless:
        log("bloqueio amazon", "Execução headless não permite liberação manual. Produto/página será tratado como erro.")
        return False

    try:
        input("[amazon] Resolva o CAPTCHA/bloqueio no navegador aberto e pressione Enter para continuar...")
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


def _inicio_lento(page: Page, query: str, url: str | None, headless: bool) -> None:
    page.goto("https://www.amazon.com.br/", wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2500)
    fechar_modais_amazon(page)
    _tratar_bloqueio_se_preciso(page, headless=headless)

    destino = url or _url_busca(query)
    log("busca", f"Abrindo listagem Amazon: {destino}")
    page.goto(destino, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(3500)
    fechar_modais_amazon(page)
    _tratar_bloqueio_se_preciso(page, headless=headless)

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


def _clicar_ver_todos_resultados_se_existir(page: Page, headless: bool) -> None:
    """Algumas categorias da Amazon mostram uma vitrine antes da listagem real."""
    bloco("listagem")
    log("listagem", "Verificando botão 'Ver todos os resultados' / 'Ver mais resultados'.")

    try:
        ultima_altura = 0
        for _ in range(8):
            page.evaluate("() => window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(700)
            altura = page.evaluate("() => document.body.scrollHeight")
            if altura == ultima_altura:
                break
            ultima_altura = altura
    except Exception:
        pass

    seletores = [
        "a#apb-desktop-browse-search-see-all[href]",
        "a:has-text('Ver todos os resultados')",
        "a:has-text('Ver mais resultados')",
        "a:has-text('See all results')",
        "a:has-text('See more results')",
    ]

    for seletor in seletores:
        try:
            loc = page.locator(seletor).first
            if loc.count() and loc.is_visible(timeout=1200):
                href = (loc.get_attribute("href") or "").strip()
                loc.scroll_into_view_if_needed(timeout=2500)
                page.wait_for_timeout(700)
                log("listagem", f"Clicando em botão de listagem real pelo seletor: {seletor}")
                try:
                    loc.click(timeout=3500)
                except Exception:
                    if href:
                        page.goto(urljoin(page.url, href), wait_until="domcontentloaded", timeout=60000)
                    else:
                        raise

                try:
                    page.wait_for_load_state("domcontentloaded", timeout=20000)
                except Exception:
                    pass
                try:
                    page.wait_for_load_state("networkidle", timeout=12000)
                except Exception:
                    pass
                page.wait_for_timeout(2200)
                fechar_modais_amazon(page)
                _tratar_bloqueio_se_preciso(page, headless=headless)
                log("listagem", "Listagem real carregada.")
                return
        except Exception:
            continue

    log("listagem", "Botão de listagem real não apareceu. Continuando na página atual.")


def _coletar_links_produtos(page: Page, max_scrolls: int = 14, alvo_minimo: int = 24) -> list[str]:
    script = r"""
    () => {
      const out = new Set();
      const anchors = Array.from(document.querySelectorAll('a[href]'));
      for (const a of anchors) {
        const href = (a.href || '').split('#')[0].trim();
        if (!href || !href.includes('amazon.com.br')) continue;
        if (!(/\/dp\/[A-Z0-9]{10}/i.test(href) || /\/gp\/product\/[A-Z0-9]{10}/i.test(href))) continue;

        const card = a.closest("div[data-component-type='s-search-result'], div.s-result-item, div[data-asin]");
        const txt = (a.innerText || a.textContent || '').replace(/\s+/g, ' ').trim().toLowerCase();
        const parecePaginacao = txt.includes('próximo') || txt.includes('proximo') || txt.includes('previous') || txt.includes('next');
        if (parecePaginacao) continue;

        // Prioriza links dentro de card, mas aceita links de produto em página de categoria.
        if (card || href.includes('/dp/') || href.includes('/gp/product/')) out.add(href);
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
                link = _normalizar_link_amazon(str(href or ""), base_url=page.url)
                if link and link not in links:
                    links.append(link)
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
            page.wait_for_timeout(750)
        except Exception:
            break

    return links


# ============================================================
# PAGINAÇÃO
# ============================================================


def _clicar_proxima_visivel(page: Page, url_antes: str, headless: bool) -> bool:
    seletores = [
        "a.s-pagination-item.s-pagination-next.s-pagination-button.s-pagination-separator[href]",
        "a.s-pagination-item.s-pagination-next.s-pagination-button[href]",
        "a.s-pagination-next[href]",
        "a[aria-label*='próxima página'][href]",
        "a[aria-label*='proxima pagina'][href]",
        "a[aria-label*='Next page'][href]",
        "a:has-text('Próximo')",
        "a:has-text('Proximo')",
        "a:has-text('Next')",
    ]

    for seletor in seletores:
        try:
            loc = page.locator(seletor)
            total = loc.count()
        except Exception:
            total = 0

        for i in range(total):
            try:
                item = loc.nth(i)
                if not item.is_visible(timeout=900):
                    continue

                classe = (item.get_attribute("class") or "").lower()
                aria_disabled = (item.get_attribute("aria-disabled") or "").lower()
                href = (item.get_attribute("href") or "").strip()

                if "disabled" in classe or "s-pagination-disabled" in classe or aria_disabled == "true":
                    log("paginação", "Botão Próximo encontrado, mas está desabilitado.")
                    return False

                if not href and "href" in seletor:
                    continue

                item.scroll_into_view_if_needed(timeout=3000)
                page.wait_for_timeout(600)
                log("paginação", f"Botão Próximo encontrado pelo seletor: {seletor}")

                try:
                    item.click(timeout=4500)
                except Exception:
                    if href:
                        page.goto(urljoin(page.url, href), wait_until="domcontentloaded", timeout=60000)
                    else:
                        handle = item.element_handle()
                        if handle:
                            page.evaluate("(el) => el.click()", handle)
                        else:
                            raise

                try:
                    page.wait_for_load_state("domcontentloaded", timeout=20000)
                except Exception:
                    pass

                try:
                    page.wait_for_url(lambda url: str(url).split('#')[0] != str(url_antes).split('#')[0], timeout=15000)
                except Exception:
                    if href and str(page.url).split('#')[0] == str(url_antes).split('#')[0]:
                        log("paginação", "URL não mudou após clique. Abrindo href diretamente.")
                        page.goto(urljoin(page.url, href), wait_until="domcontentloaded", timeout=60000)

                try:
                    page.wait_for_load_state("networkidle", timeout=12000)
                except Exception:
                    pass

                page.wait_for_timeout(2500)
                fechar_modais_amazon(page)
                _tratar_bloqueio_se_preciso(page, headless=headless)

                mudou = page.url.split("#")[0].rstrip("/") != str(url_antes or "").split("#")[0].rstrip("/")
                if mudou:
                    log("paginação", f"Próxima página carregada: {page.url}")
                    return True

            except Exception:
                continue

    return False


def _ir_proxima_pagina(page: Page, pagina_atual: int | None = None, headless: bool = False) -> bool:
    bloco("paginação")
    if pagina_atual is not None:
        log("paginação", f"Procurando botão Próximo após finalizar a página {pagina_atual}.")
    else:
        log("paginação", "Procurando botão Próximo.")

    url_antes = page.url
    fechar_modais_amazon(page)

    if _clicar_proxima_visivel(page, url_antes, headless=headless):
        return True

    for tentativa in range(1, 11):
        log("paginação", f"Descendo para localizar paginação. Tentativa {tentativa}/10")
        try:
            page.mouse.wheel(0, 1000)
        except Exception:
            try:
                page.evaluate("() => window.scrollBy(0, 1000)")
            except Exception:
                pass

        page.wait_for_timeout(800)
        fechar_modais_amazon(page)

        if _clicar_proxima_visivel(page, url_antes, headless=headless):
            return True

    log("paginação", "Não encontrei botão Próximo. Encerrando paginação.")
    return False


# ============================================================
# ARQUIVOS
# ============================================================


def _categorias_print(linha: dict[str, Any]) -> list[str]:
    """Retorna categorias de print do PRODUTO.

    Prints de CPF não são feitos aqui, porque precisam ser da tela individual
    do vendedor. Essa rotina salva apenas evidência do produto/ANATEL.
    """
    status_produto = str(linha.get("status_validacao") or linha.get("status") or "").upper()

    if status_produto == "IRREGULAR":
        return ["irregulares/anatel"]
    if status_produto == "REGULAR":
        return ["regulares/anatel"]
    if status_produto == "ERRO":
        return ["irregulares/anatel"]

    return ["regulares/anatel"]


def _salvar_print(page: Page, saida_base: Path, linha: dict[str, Any]) -> None:
    pid = linha.get("pid") or gerar_id(linha.get("titulo"), linha.get("url"))
    nome = arquivo_seguro(f"{pid}_{linha.get('titulo') or linha.get('name') or 'produto_amazon'}", 110)

    for categoria in _categorias_print(linha):
        caminho = saida_base / "prints" / categoria / f"{nome}.png"
        try:
            caminho.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(caminho), full_page=True)
            log("arquivos", f"Print salvo em: {caminho}")
        except Exception as exc:
            log("arquivos", f"Falha ao salvar print em {categoria}: {exc}")


def _valor_seguro_parquet(valor: Any) -> Any:
    """Converte valores problemáticos para tipos aceitos pelo Parquet.

    O erro que acontecia após vários produtos vinha de colunas como
    seller_count/seller_index misturando número com string vazia.
    Essa função também protege contra listas/dicionários vindos do vendedor.
    """
    if valor is None:
        return ""

    try:
        if pd.isna(valor):
            return ""
    except Exception:
        pass

    if isinstance(valor, (dict, list, tuple, set)):
        try:
            import json
            return json.dumps(valor, ensure_ascii=False)
        except Exception:
            return str(valor)

    return valor


def _df_parquet_seguro(
    registros: list[dict[str, Any]],
    colunas_inteiras: set[str] | None = None,
    colunas_float: set[str] | None = None,
) -> pd.DataFrame:
    """Garante tipos estáveis antes de salvar em Parquet.

    As colunas mini_*_cm precisam continuar como número decimal.
    As demais colunas ficam como texto para evitar erro do PyArrow quando há
    mistura de string vazia, bool, inteiro e dicionários.
    """
    colunas_inteiras = colunas_inteiras or set()
    colunas_float = colunas_float or set()

    df = pd.DataFrame(registros)
    if df.empty:
        return df

    for col in df.columns:
        df[col] = df[col].map(_valor_seguro_parquet)

    for col in colunas_inteiras:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0).astype("int64")

    for col in colunas_float:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    for col in df.columns:
        if col not in colunas_inteiras and col not in colunas_float:
            df[col] = df[col].fillna("").astype(str)

    return df


def _salvar_resultados(
    saida: Path,
    linhas: list[dict[str, Any]],
    comentarios: list[dict[str, Any]],
    vendedores: list[dict[str, Any]],
    descartados_mini: list[dict[str, Any]] | None = None,
    suspeitos_mini: list[dict[str, Any]] | None = None,
) -> None:
    saida.mkdir(parents=True, exist_ok=True)

    inteiras_produtos = {
        "seller_count",
        "seller_cpf_count",
        "seller_cnpj_count",
        "seller_sem_doc_count",
    }
    floats_mini = {
        "mini_maior_cm",
        "mini_largura_cm",
        "mini_espessura_cm",
        "mini_limite_maior_cm",
        "mini_limite_largura_cm",
    }
    inteiras_comentarios = {"comentario_ordem"}
    inteiras_vendedores = {"seller_index"}

    df = _df_parquet_seguro(linhas, inteiras_produtos, floats_mini)
    df.to_parquet(saida / "products.parquet", index=False)
    df.to_parquet(saida / "resultados.parquet", index=False)

    dfc = _df_parquet_seguro(comentarios, inteiras_comentarios)
    dfc.to_parquet(saida / "comments.parquet", index=False)

    dfs = _df_parquet_seguro(vendedores, inteiras_vendedores)
    dfs.to_parquet(saida / "sellers.parquet", index=False)

    if descartados_mini is not None:
        dfd = _df_parquet_seguro(descartados_mini, set(), floats_mini)
        dfd.to_parquet(saida / "products_descartados_mini.parquet", index=False)

    if suspeitos_mini is not None:
        dfsusp = _df_parquet_seguro(suspeitos_mini, set(), floats_mini)
        dfsusp.to_parquet(saida / "products_suspeitos_mini.parquet", index=False)

def _sem_limite(valor: int | None) -> bool:
    try:
        return int(valor or 0) <= 0
    except Exception:
        return True


# ============================================================
# FLUXO PRINCIPAL
# ============================================================


def rodar_playwright_amazon(
    query: str = "smartphone",
    queries: list[str] | None = None,
    limite: int = 5,
    base_anatel: BaseAnatel | None = None,
    headless: bool = False,
    url: str | None = None,
    saida: str | Path | None = None,
    max_paginas: int = 0,
    analisar_vendedor: bool = True,
    mini_celulares: bool = False,
    mini_maior_cm: float = 12.0,
    mini_largura_cm: float = 5.5,
    mini_manter_sem_medida: bool = False,
) -> dict[str, Any]:
    """Crawler Amazon Playwright.

    Novidades do modo mini celulares:
    - aceita lista de buscas vinda de .txt;
    - remove links repetidos entre buscas;
    - filtra produtos por dimensões <= 8,5 cm x 5,5 cm;
    - separa anúncios disfarçados/suspeitos para análise manual;
    - só faz ANATEL/vendedor/comentários para produtos mantidos na planilha principal.
    """

    saida_base = _saida_padrao_amazon(saida)
    linhas: list[dict[str, Any]] = []
    comentarios_linhas: list[dict[str, Any]] = []
    vendedores_linhas: list[dict[str, Any]] = []
    descartados_mini: list[dict[str, Any]] = []
    suspeitos_mini: list[dict[str, Any]] = []

    buscas = [q.strip() for q in (queries or []) if str(q or "").strip()]
    if url:
        buscas = [query]
    elif not buscas:
        buscas = [query or "smartphone"]

    urls_processadas: set[str] = set()
    total_processados = 0
    paginas_sem_links_novos_total = 0

    sem_limite_produtos = _sem_limite(limite)
    sem_limite_paginas = _sem_limite(max_paginas)
    limite_txt = "sem limite" if sem_limite_produtos else str(limite)
    max_paginas_txt = "sem limite" if sem_limite_paginas else str(max_paginas)

    secao("Amazon Playwright")
    log("crawler", f"Buscas na execução: {len(buscas)}")
    if url:
        log("crawler", f"URL direta: {url}")
    else:
        log("crawler", f"Primeira busca: {buscas[0]}")
    log("crawler", f"Limite total de produtos: {limite_txt}")
    log("crawler", f"Máximo de páginas por busca: {max_paginas_txt}")
    log("crawler", f"Análise de vendedor: {'SIM' if analisar_vendedor else 'NÃO'}")
    if mini_celulares:
        log("mini celular", "Modo mini celular ativado")
        log("mini celular", f"Limite dimensional: maior eixo <= {mini_maior_cm} cm e largura <= {mini_largura_cm} cm")
        log("mini celular", f"Sem medida explícita: {'manter para revisão' if mini_manter_sem_medida else 'separar/descartar da planilha principal'}")
    log("crawler", f"Saída: {saida_base.resolve()}")

    with sync_playwright() as p:
        context = _abrir_contexto_chrome_persistente(p, headless=headless)
        page = context.pages[0] if context.pages else context.new_page()
        page.set_default_timeout(12000)
        page.set_default_navigation_timeout(60000)

        try:
            primeira_busca = buscas[0] if buscas else query
            _inicio_lento(page, query=primeira_busca, url=url, headless=headless)
            _clicar_ver_todos_resultados_se_existir(page, headless=headless)

            for indice_busca, consulta_atual in enumerate(buscas, start=1):
                if not sem_limite_produtos and total_processados >= int(limite):
                    log("busca", f"Limite total atingido antes da próxima busca: {total_processados}/{limite}.")
                    break

                if not url:
                    if indice_busca == 1:
                        # A primeira busca já foi aberta por _inicio_lento.
                        pass
                    else:
                        destino = _url_busca(consulta_atual)
                        secao(f"BUSCA {indice_busca}/{len(buscas)}")
                        log("busca", f"Abrindo nova busca Amazon: {consulta_atual}")
                        log("busca", f"URL: {destino}")
                        page.goto(destino, wait_until="domcontentloaded", timeout=60000)
                        page.wait_for_timeout(3000)
                        fechar_modais_amazon(page)
                        _tratar_bloqueio_se_preciso(page, headless=headless)
                        try:
                            page.wait_for_load_state("networkidle", timeout=12000)
                        except Exception:
                            pass
                        _clicar_ver_todos_resultados_se_existir(page, headless=headless)

                pagina_atual = 1
                paginas_sem_links_novos = 0

                while True:
                    if not sem_limite_produtos and total_processados >= int(limite):
                        log("busca", f"Limite total atingido: {total_processados}/{limite}.")
                        break

                    if not sem_limite_paginas and pagina_atual > int(max_paginas):
                        log("paginação", f"Máximo de páginas atingido nesta busca: {max_paginas}.")
                        break

                    if not _tratar_bloqueio_se_preciso(page, headless=headless):
                        log("bloqueio amazon", "Página de listagem bloqueada. Encerrando busca atual.")
                        break

                    secao(f"BUSCA {indice_busca}/{len(buscas)} | PÁGINA {pagina_atual}")
                    bloco("listagem")
                    log("listagem", f"Consulta atual: {consulta_atual}")
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
                        href_limpo = _normalizar_link_amazon(href, base_url=page.url)
                        if not href_limpo:
                            continue
                        if href_limpo in vistos_pagina:
                            continue
                        if href_limpo in urls_processadas:
                            continue
                        vistos_pagina.add(href_limpo)
                        links_novos.append(href_limpo)

                    log("listagem", f"Links capturados: {len(links_pagina)}")
                    log("listagem", f"Links novos para processar: {len(links_novos)}")

                    if not links_novos:
                        paginas_sem_links_novos += 1
                        paginas_sem_links_novos_total += 1
                        bloco("paginação")
                        log(
                            "paginação",
                            f"Nenhum produto novo nesta página. Ocorrências seguidas nesta busca: {paginas_sem_links_novos}/3",
                        )
                        if paginas_sem_links_novos >= 3:
                            log("paginação", "Três páginas seguidas sem links novos nesta busca. Indo para a próxima busca.")
                            break
                        if not _ir_proxima_pagina(page, pagina_atual=pagina_atual, headless=headless):
                            log("paginação", "Não há próxima página disponível nesta busca.")
                            break
                        pagina_atual += 1
                        continue

                    paginas_sem_links_novos = 0

                    for indice_pagina, href in enumerate(links_novos, start=1):
                        if not sem_limite_produtos and total_processados >= int(limite):
                            log("busca", f"Limite total atingido: {total_processados}/{limite}.")
                            break

                        urls_processadas.add(href)
                        total_processados += 1

                        secao(f"BUSCA {indice_busca}/{len(buscas)} | PÁGINA {pagina_atual} | PRODUTO {indice_pagina}/{len(links_novos)}")
                        bloco("navegação")
                        log("navegação", f"Produto geral {total_processados}/{limite_txt}")
                        log("navegação", f"Busca: {consulta_atual}")
                        log("navegação", f"Abrindo anúncio: {href}")

                        prod_page = context.new_page()
                        prod_page.set_default_timeout(12000)
                        prod_page.set_default_navigation_timeout(60000)

                        try:
                            prod_page.goto(href, wait_until="domcontentloaded", timeout=60000)
                            prod_page.wait_for_timeout(2600)
                            fechar_modais_amazon(prod_page)

                            try:
                                prod_page.wait_for_load_state("networkidle", timeout=10000)
                            except Exception:
                                pass

                            if not _tratar_bloqueio_se_preciso(prod_page, headless=headless):
                                raise RuntimeError("Produto bloqueado por CAPTCHA/validação da Amazon")

                            # 1) Extração do produto. No modo mini, só captura comentários depois
                            # que o produto passar pelo filtro dimensional/suspeito.
                            dados = extrair_produto_amazon(prod_page, capturar_reviews=not mini_celulares)

                            mini_info: dict[str, Any] = {}
                            if mini_celulares:
                                mini_info = analisar_mini_celular_amazon(
                                    dados,
                                    maior_max_cm=mini_maior_cm,
                                    largura_max_cm=mini_largura_cm,
                                )

                                mini_status = str(mini_info.get("mini_status") or "")
                                manter_por_medida = mini_status == "MANTER"
                                manter_sem_medida = mini_manter_sem_medida and mini_status in {"REVISAR_SEM_MEDIDA", "SUSPEITO_MANUAL"}

                                bloco("mini celular")
                                log("mini celular", f"Status: {mini_status or 'não classificado'}")
                                log("mini celular", f"Motivo: {mini_info.get('mini_motivo') or 'sem motivo'}")
                                if mini_info.get("mini_evidencia"):
                                    log("mini celular", f"Evidência: {mini_info.get('mini_evidencia')}")
                                if str(mini_info.get("mini_suspeito_manual")).lower() in {"true", "1"} or mini_status == "SUSPEITO_MANUAL":
                                    log("mini celular", f"Suspeito manual: {mini_info.get('mini_suspeito_motivo') or mini_info.get('mini_motivo')}")

                                # Linha base para descartados/suspeitos sem rodar ANATEL/vendedor.
                                if not (manter_por_medida or manter_sem_medida):
                                    linha_descartada = dados_para_linha(
                                        dados,
                                        {
                                            "status_validacao": "FORA_ESCOPO_MINI",
                                            "motivo_validacao": mini_info.get("mini_motivo", "Fora do recorte de mini celular"),
                                            "irregularity_reasons": "",
                                            "warnings": mini_info.get("mini_motivo", ""),
                                            "modo_match_base": "mini_descartado",
                                        },
                                    )
                                    linha_descartada["marketplace_id"] = "1"
                                    linha_descartada["marketplace"] = "amazon"
                                    linha_descartada["created_at"] = time.strftime("%Y-%m-%d")
                                    linha_descartada["atributos_json"] = dados.atributos_json
                                    linha_descartada["busca_origem"] = consulta_atual
                                    linha_descartada.update(mini_info)

                                    if mini_status == "SUSPEITO_MANUAL":
                                        suspeitos_mini.append(linha_descartada)
                                    else:
                                        descartados_mini.append(linha_descartada)

                                    _salvar_resultados(
                                        saida_base,
                                        linhas,
                                        comentarios_linhas,
                                        vendedores_linhas,
                                        descartados_mini,
                                        suspeitos_mini,
                                    )
                                    continue

                                if str(mini_info.get("mini_suspeito_manual")).lower() in {"true", "1"}:
                                    linha_suspeita = dados_para_linha(
                                        dados,
                                        {
                                            "status_validacao": "SUSPEITO_MANUAL",
                                            "motivo_validacao": mini_info.get("mini_suspeito_motivo", "Suspeito manual"),
                                            "irregularity_reasons": "",
                                            "warnings": mini_info.get("mini_suspeito_motivo", ""),
                                            "modo_match_base": "mini_suspeito",
                                        },
                                    )
                                    linha_suspeita["marketplace_id"] = "1"
                                    linha_suspeita["marketplace"] = "amazon"
                                    linha_suspeita["created_at"] = time.strftime("%Y-%m-%d")
                                    linha_suspeita["atributos_json"] = dados.atributos_json
                                    linha_suspeita["busca_origem"] = consulta_atual
                                    linha_suspeita.update(mini_info)
                                    suspeitos_mini.append(linha_suspeita)

                                dados.comentarios = capturar_comentarios_amazon(prod_page, limite=10)

                            # 2) Validação ANATEL.
                            validacao = validar_produto(dados, base_anatel)
                            linha_produto = dados_para_linha(dados, validacao)
                            linha_produto["marketplace_id"] = "1"
                            linha_produto["marketplace"] = "amazon"
                            linha_produto["created_at"] = time.strftime("%Y-%m-%d")
                            linha_produto["atributos_json"] = dados.atributos_json
                            linha_produto["busca_origem"] = consulta_atual
                            if mini_info:
                                linha_produto.update(mini_info)

                            # 3) Análise do vendedor depois de consolidar produto/ANATEL.
                            vendedor = {}
                            sellers_lista = []
                            if analisar_vendedor:
                                try:
                                    vendedor = analisar_vendedor_amazon(
                                        prod_page,
                                        context=context,
                                        saida_base=saida_base,
                                        pid=linha_produto.get("pid", ""),
                                        product_name=linha_produto.get("name") or linha_produto.get("titulo") or "",
                                    )
                                    sellers_lista = vendedor.pop("__sellers_list", []) or []
                                    linha_produto.update(vendedor)
                                except Exception as exc:
                                    log("vendedor amazon", f"Falha na análise de vendedor: {type(exc).__name__}: {exc}")
                                    linha_produto["seller_error"] = f"{type(exc).__name__}: {exc}"

                            linhas.append(linha_produto)

                            if sellers_lista:
                                for seller_item in sellers_lista:
                                    vendedores_linhas.append(
                                        {
                                            "pid": linha_produto["pid"],
                                            "marketplace_id": "1",
                                            "url": linha_produto["url"],
                                            "created_at": linha_produto["created_at"],
                                            **seller_item,
                                        }
                                    )
                            elif vendedor:
                                vendedores_linhas.append(
                                    {
                                        "pid": linha_produto["pid"],
                                        "marketplace_id": "1",
                                        "url": linha_produto["url"],
                                        "created_at": linha_produto["created_at"],
                                        **vendedor,
                                    }
                                )

                            for i, comentario in enumerate(dados.comentarios or [], start=1):
                                comentarios_linhas.append(
                                    {
                                        "pid": linha_produto["pid"],
                                        "marketplace_id": "1",
                                        "url": linha_produto["url"],
                                        "comentario_ordem": i,
                                        "comment": comentario,
                                        "created_at": linha_produto["created_at"],
                                    }
                                )

                            bloco("produto")
                            log("produto", f"Nome: {linha_produto.get('name') or linha_produto.get('titulo') or 'não encontrado'}")
                            log("anatel", f"Código: {linha_produto.get('anatel_number') or 'não encontrado'}")
                            log("marca", f"Marca: {linha_produto.get('brand') or linha_produto.get('marca') or 'não encontrada'}")
                            log("modelo", f"Modelo decisivo: {linha_produto.get('modelo_decisivo') or 'não encontrado'}")
                            log("resultado", f"Situação: {linha_produto.get('status_validacao') or linha_produto.get('status')}")

                            motivo = linha_produto.get("irregularity_reasons") or linha_produto.get("motivo_validacao") or ""
                            if motivo:
                                log("motivo", motivo)

                            bloco("arquivos")
                            _salvar_print(prod_page, saida_base, linha_produto)
                            _salvar_resultados(
                                saida_base,
                                linhas,
                                comentarios_linhas,
                                vendedores_linhas,
                                descartados_mini,
                                suspeitos_mini,
                            )

                        except Exception as exc:
                            bloco("erro")
                            log("erro", f"Falha ao processar produto: {type(exc).__name__}: {exc}")

                            linha_erro = {
                                "pid": gerar_id(href),
                                "marketplace_id": "1",
                                "marketplace": "amazon",
                                "name": "",
                                "titulo": "",
                                "link": href,
                                "url": href,
                                "status": "ERRO",
                                "status_validacao": "ERRO",
                                "motivo_validacao": f"Falha ao processar: {type(exc).__name__}: {exc}",
                                "irregularity_reasons": f"Falha ao processar: {type(exc).__name__}: {exc}",
                                "created_at": time.strftime("%Y-%m-%d"),
                                "busca_origem": consulta_atual,
                            }
                            linhas.append(linha_erro)
                            _salvar_resultados(
                                saida_base,
                                linhas,
                                comentarios_linhas,
                                vendedores_linhas,
                                descartados_mini,
                                suspeitos_mini,
                            )

                        finally:
                            try:
                                prod_page.close()
                            except Exception:
                                pass

                            bloco("navegação")
                            log("navegação", f"Produto geral {total_processados}/{limite_txt} finalizado.")

                    if not sem_limite_produtos and total_processados >= int(limite):
                        log("busca", f"Limite total atingido: {total_processados}/{limite}.")
                        break

                    if not sem_limite_paginas and pagina_atual >= int(max_paginas):
                        log("paginação", f"Máximo de páginas atingido nesta busca: {pagina_atual}/{max_paginas}.")
                        break

                    bloco("paginação")
                    log("paginação", "Produtos da página finalizados. Tentando avançar para a próxima página.")

                    if not _ir_proxima_pagina(page, pagina_atual=pagina_atual, headless=headless):
                        log("paginação", "Não encontrei próxima página nesta busca.")
                        break

                    pagina_atual += 1

                if url:
                    # URL direta não possui sequência de buscas.
                    break

        finally:
            try:
                context.close()
            except Exception:
                pass

    _salvar_resultados(saida_base, linhas, comentarios_linhas, vendedores_linhas, descartados_mini, suspeitos_mini)

    resumo = {
        "saida": str(saida_base.resolve()),
        "total_produtos": len(linhas),
        "total_comentarios": len(comentarios_linhas),
        "total_vendedores": len(vendedores_linhas),
        "regulares": sum(1 for l in linhas if str(l.get("status_validacao") or l.get("status")).upper() == "REGULAR"),
        "irregulares": sum(1 for l in linhas if str(l.get("status_validacao") or l.get("status")).upper() == "IRREGULAR"),
        "erros": sum(1 for l in linhas if str(l.get("status_validacao") or l.get("status")).upper() == "ERRO"),
        "mini_modo": "ativado" if mini_celulares else "desativado",
        "mini_mantidos": sum(1 for l in linhas if str(l.get("mini_status") or "") == "MANTER"),
        "mini_descartados": len(descartados_mini),
        "mini_suspeitos_manuais": len(suspeitos_mini),
        "buscas_executadas": len(buscas),
        "paginas_maximas_por_busca": max_paginas_txt,
        "urls_processadas": len(urls_processadas),
        "paginas_sem_links_novos": paginas_sem_links_novos_total,
        "products_parquet": str((saida_base / "products.parquet").resolve()),
        "comments_parquet": str((saida_base / "comments.parquet").resolve()),
        "sellers_parquet": str((saida_base / "sellers.parquet").resolve()),
        "products_descartados_mini_parquet": str((saida_base / "products_descartados_mini.parquet").resolve()) if mini_celulares else "",
        "products_suspeitos_mini_parquet": str((saida_base / "products_suspeitos_mini.parquet").resolve()) if mini_celulares else "",
    }

    secao("Resumo Amazon Playwright")
    for chave, valor in resumo.items():
        log("resumo", f"{chave}: {valor}")

    return resumo