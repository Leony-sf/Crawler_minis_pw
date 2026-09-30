from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urljoin, urlsplit

from playwright.sync_api import BrowserContext, Locator, Page

from .utils import arquivo_seguro, bloco, gerar_id, log, normalizar_texto


CNPJ_RE = re.compile(r"\b\d{2}\.?\d{3}\.?\d{3}/?\d{4}-?\d{2}\b")
CPF_RE = re.compile(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b")

TEXTOS_LIXO = {
    "",
    "sem nome",
    "ver detalhes",
    "detalhes",
    "política de devolução",
    "politica de devolucao",
    "adicionar ao carrinho",
    "comprar agora",
    "novo",
    "usado",
    "frete grátis",
    "frete gratis",
    "saiba mais",
    "devolução",
    "devolucao",
}


# ============================================================
# Utilidades
# ============================================================


def _digits(txt: object) -> str:
    return re.sub(r"\D", "", str(txt or ""))


def _key_texto(txt: object) -> str:
    txt = normalizar_texto(txt).lower()
    txt = unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode("ascii")
    txt = re.sub(r"[^a-z0-9]+", "", txt)
    return txt


def _extrair_documento(texto: str) -> tuple[str, str]:
    """Retorna (documento_somente_digitos, tipo CPF/CNPJ)."""
    texto = texto or ""

    m_cpf = CPF_RE.search(texto)
    if m_cpf:
        return _digits(m_cpf.group(0)), "CPF"

    m_cnpj = CNPJ_RE.search(texto)
    if m_cnpj:
        return _digits(m_cnpj.group(0)), "CNPJ"

    return "", ""


def _texto_locator(loc: Locator, timeout_ms: int = 1200) -> str:
    try:
        return normalizar_texto(loc.inner_text(timeout=timeout_ms))
    except Exception:
        return ""


def _href_locator(loc: Locator, timeout_ms: int = 1000) -> str:
    try:
        href = normalizar_texto(loc.get_attribute("href", timeout=timeout_ms) or "")
        return href
    except Exception:
        return ""


def _primeiro_texto(base: Page | Locator, seletores: list[str], timeout_ms: int = 1200) -> str:
    for seletor in seletores:
        try:
            loc = base.locator(seletor).first
            if loc.count():
                txt = _texto_locator(loc, timeout_ms=timeout_ms)
                if txt:
                    return txt
        except Exception:
            continue
    return ""


def _primeiro_href(base: Page | Locator, seletores: list[str], pagina_url: str, timeout_ms: int = 1000) -> str:
    for seletor in seletores:
        try:
            loc = base.locator(seletor).first
            if loc.count():
                href = _href_locator(loc, timeout_ms=timeout_ms)
                if href:
                    return urljoin(pagina_url, href)
        except Exception:
            continue
    return ""


def _limpar_nome_vendedor(nome: str) -> str:
    nome = normalizar_texto(nome)
    if not nome:
        return ""

    nome = re.sub(r"(?i)^vendido\s+por\s*", "", nome).strip(" :-")
    nome = re.sub(r"(?i)^enviado\s+por\s*", "", nome).strip(" :-")
    nome = re.sub(r"(?i)^sold\s+by\s*", "", nome).strip(" :-")
    nome = normalizar_texto(nome)

    if _key_texto(nome) in {_key_texto(x) for x in TEXTOS_LIXO}:
        return ""

    if len(nome) > 120:
        return ""

    return nome


def _pagina_login_amazon(page: Page) -> bool:
    try:
        url = (page.url or "").lower()
        if "/ap/signin" in url or "signin" in url or "login" in url:
            return True
    except Exception:
        pass

    for seletor in ["input#ap_email", "input#ap_password", "form[name='signIn']", "#authportal-main-section"]:
        try:
            loc = page.locator(seletor).first
            if loc.count() and loc.is_visible(timeout=500):
                return True
        except Exception:
            continue
    return False


def _seller_id_from_url(url: str) -> str:
    url = normalizar_texto(url)
    if not url:
        return ""

    try:
        parts = urlsplit(url)
        qs = parse_qs(parts.query)
        for key in ["seller", "me", "sellerID", "sellerId"]:
            vals = qs.get(key) or qs.get(key.lower()) or []
            if vals and vals[0]:
                return _key_texto(vals[0])

        m = re.search(r"(?:seller|me)=([A-Z0-9]+)", url, flags=re.IGNORECASE)
        if m:
            return _key_texto(m.group(1))
    except Exception:
        pass

    return ""


def _dedupe_key(vendedor: dict[str, Any]) -> str:
    seller_id = _seller_id_from_url(str(vendedor.get("seller_profile_url") or ""))
    if seller_id:
        return f"id:{seller_id}"

    doc = _digits(vendedor.get("seller_doc", ""))
    if doc:
        return f"doc:{doc}"

    nome = _key_texto(vendedor.get("seller_name") or vendedor.get("seller_profile_name"))
    if nome:
        return f"nome:{nome}"

    bruto = _key_texto(str(vendedor.get("seller_offer_raw_text") or "")[:180])
    return f"raw:{bruto}"


def _deduplicar(vendedores: list[dict[str, Any]]) -> list[dict[str, Any]]:
    saida: list[dict[str, Any]] = []
    vistos: set[str] = set()

    for vendedor in vendedores:
        vendedor = dict(vendedor)
        vendedor["seller_name"] = _limpar_nome_vendedor(str(vendedor.get("seller_name") or ""))
        vendedor["seller_profile_url"] = normalizar_texto(vendedor.get("seller_profile_url") or "")

        # Se não tem nome nem link, não é vendedor analisável.
        if not vendedor["seller_name"] and not vendedor["seller_profile_url"]:
            continue

        chave = _dedupe_key(vendedor)
        if chave in vistos:
            continue
        vistos.add(chave)
        saida.append(vendedor)

    return saida


def _asin_da_url(url: str) -> str:
    m = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", url or "", flags=re.IGNORECASE)
    return m.group(1).upper() if m else ""


# ============================================================
# Abrir lista/aba de vendedores
# ============================================================


def _clicar_aba_vendedores(page: Page) -> bool:
    seletores = [
        "#aod-ingress-link",
        "#buybox-see-all-buying-choices",
        "#all-offers-display-scroller a",
        "a[href*='offer-listing']",
        "a:has-text('Ver todas as opções de compra')",
        "a:has-text('Ver todas as ofertas')",
        "span:has-text('Ver todas as opções de compra')",
        "span:has-text('Ver todas as ofertas')",
        "input[name='submit.addToCart'][aria-labelledby*='aod']",
    ]

    for seletor in seletores:
        try:
            loc = page.locator(seletor).first
            if not loc.count():
                continue

            try:
                loc.scroll_into_view_if_needed(timeout=2000)
            except Exception:
                pass

            page.wait_for_timeout(400)

            try:
                loc.click(timeout=3000)
            except Exception:
                handle = loc.element_handle()
                if handle:
                    page.evaluate("(el) => el.click()", handle)
                else:
                    continue

            page.wait_for_timeout(2200)
            return True
        except Exception:
            continue

    return False


def _abrir_lista_vendedores(page: Page, context: BrowserContext | None = None) -> Page:
    """Retorna a página/aba onde a lista de ofertas/vendedores está aberta."""
    if _clicar_aba_vendedores(page):
        # Geralmente a Amazon abre um modal AOD na mesma página.
        return page

    # Fallback: abre a página clássica de oferta pelo ASIN.
    asin = _asin_da_url(page.url)
    if asin and context is not None:
        ofertas_url = f"https://www.amazon.com.br/gp/offer-listing/{asin}/ref=dp_olp_ALL_mbc?ie=UTF8&condition=ALL"
        ofertas_page = context.new_page()
        ofertas_page.set_default_timeout(12000)
        ofertas_page.set_default_navigation_timeout(45000)
        ofertas_page.goto(ofertas_url, wait_until="domcontentloaded", timeout=45000)
        ofertas_page.wait_for_timeout(2500)
        return ofertas_page

    return page


# ============================================================
# Coleta dos vendedores da lista/ofertas
# ============================================================


def _extrair_nome_de_texto_card(texto: str) -> str:
    texto = normalizar_texto(texto)
    if not texto:
        return ""

    linhas = [normalizar_texto(x) for x in re.split(r"[\r\n]+", texto) if normalizar_texto(x)]
    for i, linha in enumerate(linhas):
        if re.search(r"(?i)vendido\s+por|sold\s+by", linha):
            # Exemplo: "Vendido por Loja X" ou "Vendido por\nLoja X".
            m = re.search(r"(?i)(?:vendido\s+por|sold\s+by)\s*:?[\s-]*(.+)$", linha)
            if m and _limpar_nome_vendedor(m.group(1)):
                return _limpar_nome_vendedor(m.group(1))
            if i + 1 < len(linhas):
                nome = _limpar_nome_vendedor(linhas[i + 1])
                if nome:
                    return nome

    return ""


def _extrair_vendedor_de_card(card: Locator, pagina_url: str) -> dict[str, Any] | None:
    texto = _texto_locator(card, timeout_ms=1600)
    if not texto:
        return None

    doc, tipo_doc = _extrair_documento(texto)

    link = _primeiro_href(
        card,
        [
            "#aod-offer-soldBy a[href]",
            "[id*='soldBy'] a[href]",
            "a[href*='/sp?'][href*='seller=']",
            "a[href*='seller='][href*='marketplaceID']",
            "a[href*='me=']",
            "a[href*='/shops/']",
            "a[href*='/gp/help/seller/']",
        ],
        pagina_url=pagina_url,
    )

    nome = _primeiro_texto(
        card,
        [
            "#aod-offer-soldBy a",
            "[id*='soldBy'] a",
            "a[href*='/sp?'][href*='seller=']",
            "a[href*='seller='][href*='marketplaceID']",
            "a[href*='/shops/']",
            "a[href*='me=']",
        ],
        timeout_ms=1200,
    )
    nome = _limpar_nome_vendedor(nome)

    if not nome:
        nome = _extrair_nome_de_texto_card(texto)

    preco = _primeiro_texto(
        card,
        [
            ".a-price .a-offscreen",
            ".a-price",
            "[class*='price']",
        ],
        timeout_ms=800,
    )

    # Se ainda não houver nome/link/doc, não é card de vendedor.
    if not nome and not link and not doc:
        return None

    return {
        "seller_name": nome,
        "seller_profile_url": link,
        "seller_offer_price": preco,
        "seller_offer_raw_text": texto[:2500],
        "seller_doc": doc,
        "seller_doc_type": tipo_doc,
        "seller_doc_source": "lista_ofertas" if doc else "",
    }


def _coletar_cards_vendedores(lista_page: Page) -> list[Locator]:
    seletores_cards = [
        "#aod-offer",
        "div[id^='aod-offer']",
        "#aod-container div[id*='aod-offer']",
        ".olpOffer",
        "div[role='listitem']:has(a[href*='seller='])",
        "div:has(> div a[href*='seller=']):has-text('Vendido por')",
    ]

    cards: list[Locator] = []
    for seletor in seletores_cards:
        try:
            loc = lista_page.locator(seletor)
            total = loc.count()
        except Exception:
            total = 0

        for i in range(total):
            try:
                card = loc.nth(i)
                txt = _texto_locator(card, timeout_ms=500)
                if txt:
                    cards.append(card)
            except Exception:
                continue

        if cards:
            break

    return cards


def _coletar_vendedores_da_lista(lista_page: Page) -> tuple[list[dict[str, Any]], list[Locator]]:
    # Pequena rolagem só dentro da área/lista de ofertas para carregar cards preguiçosos.
    for _ in range(3):
        try:
            lista_page.mouse.wheel(0, 700)
            lista_page.wait_for_timeout(350)
        except Exception:
            break

    cards = _coletar_cards_vendedores(lista_page)
    vendedores: list[dict[str, Any]] = []
    cards_validos: list[Locator] = []

    for card in cards:
        vendedor = _extrair_vendedor_de_card(card, pagina_url=lista_page.url)
        if vendedor:
            vendedores.append(vendedor)
            cards_validos.append(card)

    vendedores_unicos = _deduplicar(vendedores)

    # Mantém uma lista de cards alinhada aproximadamente com os vendedores únicos para fallback de print.
    cards_unicos: list[Locator] = []
    vistos: set[str] = set()
    for vendedor, card in zip(vendedores, cards_validos):
        chave = _dedupe_key(vendedor)
        if chave and chave not in vistos:
            vistos.add(chave)
            cards_unicos.append(card)

    return vendedores_unicos, cards_unicos


def _vendedor_principal_do_produto(page: Page) -> dict[str, Any] | None:
    texto = _primeiro_texto(
        page,
        [
            "#merchant-info",
            "#tabular-buybox",
            "#sellerProfileTriggerId",
            "#desktop_qualifiedBuyBox_feature_div",
            "#buybox",
        ],
        timeout_ms=1800,
    )

    link = _primeiro_href(
        page,
        [
            "#sellerProfileTriggerId[href]",
            "#merchant-info a[href]",
            "#tabular-buybox a[href*='seller=']",
            "a[href*='/sp?'][href*='seller=']",
        ],
        pagina_url=page.url,
    )

    nome = _primeiro_texto(
        page,
        [
            "#sellerProfileTriggerId",
            "#merchant-info a",
            "#tabular-buybox a[href*='seller=']",
        ],
        timeout_ms=1200,
    )

    if not nome and texto:
        nome = _extrair_nome_de_texto_card(texto)

    nome = _limpar_nome_vendedor(nome)
    doc, tipo_doc = _extrair_documento(texto)

    if not nome and not link and not doc:
        return None

    return {
        "seller_name": nome,
        "seller_profile_url": link,
        "seller_offer_price": "",
        "seller_offer_raw_text": texto[:2500],
        "seller_doc": doc,
        "seller_doc_type": tipo_doc,
        "seller_doc_source": "produto" if doc else "",
    }


# ============================================================
# Análise individual do perfil do vendedor
# ============================================================


def _clicar_expansores_documento(page: Page) -> None:
    textos = [
        "Informações comerciais detalhadas",
        "Informacoes comerciais detalhadas",
        "Informações do vendedor",
        "Informacoes do vendedor",
        "Detalhes do vendedor",
        "Ver detalhes",
        "Ver endereço comercial",
        "Ver endereco comercial",
        "Business Address",
        "Detailed Seller Information",
    ]

    for texto in textos:
        try:
            loc = page.get_by_text(texto, exact=False).first
            if loc.count() and loc.is_visible(timeout=500):
                try:
                    loc.scroll_into_view_if_needed(timeout=1000)
                except Exception:
                    pass
                try:
                    loc.click(timeout=1200)
                    page.wait_for_timeout(500)
                except Exception:
                    pass
        except Exception:
            continue


def _extrair_doc_do_perfil(perfil: Page) -> tuple[str, str, str]:
    """Rola a página individual do vendedor até encontrar CPF/CNPJ."""
    texto_total = ""

    for tentativa in range(1, 9):
        _clicar_expansores_documento(perfil)

        try:
            texto = normalizar_texto(perfil.locator("body").inner_text(timeout=2500))
        except Exception:
            texto = ""

        if texto:
            texto_total = texto
            doc, tipo = _extrair_documento(texto)
            if doc:
                return doc, tipo, texto[:3500]

        try:
            perfil.mouse.wheel(0, 900)
        except Exception:
            try:
                perfil.evaluate("() => window.scrollBy(0, 900)")
            except Exception:
                pass

        perfil.wait_for_timeout(450)

    return "", "", texto_total[:3500]


def _salvar_print_cpf(
    page_or_card: Page | Locator,
    saida_base: Path,
    pid: str,
    indice: int,
    seller_name: str,
) -> str:
    pasta = Path(saida_base) / "prints" / "irregulares" / "cpf"
    pasta.mkdir(parents=True, exist_ok=True)

    nome = arquivo_seguro(f"{pid}_vendedor_{indice}_{seller_name or 'sem_nome'}", limite=130)
    caminho = pasta / f"{nome}.png"

    try:
        # Page aceita full_page; Locator não.
        if isinstance(page_or_card, Page):
            page_or_card.screenshot(path=str(caminho), full_page=True)
        else:
            page_or_card.screenshot(path=str(caminho))
        return str(caminho)
    except Exception:
        return ""


def _analisar_um_vendedor(
    vendedor: dict[str, Any],
    indice: int,
    total: int,
    context: BrowserContext | None,
    saida_base: Path | None,
    pid: str,
    card_fallback: Locator | None = None,
) -> dict[str, Any]:
    vendedor = dict(vendedor)
    nome = _limpar_nome_vendedor(vendedor.get("seller_name") or "") or "sem nome"
    perfil_url = normalizar_texto(vendedor.get("seller_profile_url") or "")

    doc = _digits(vendedor.get("seller_doc", ""))
    tipo_doc = normalizar_texto(vendedor.get("seller_doc_type") or "")
    fonte_doc = normalizar_texto(vendedor.get("seller_doc_source") or "")
    perfil_texto = ""
    print_path = ""

    perfil: Page | None = None
    try:
        if perfil_url and context is not None:
            perfil = context.new_page()
            perfil.set_default_timeout(10000)
            perfil.set_default_navigation_timeout(45000)
            perfil.goto(perfil_url, wait_until="domcontentloaded", timeout=45000)
            perfil.wait_for_timeout(1800)

            if not _pagina_login_amazon(perfil):
                doc_perfil, tipo_perfil, perfil_texto = _extrair_doc_do_perfil(perfil)
                if doc_perfil:
                    doc = doc_perfil
                    tipo_doc = tipo_perfil
                    fonte_doc = "perfil_vendedor"

                # Melhora nome pelo perfil, quando possível.
                nome_perfil = _primeiro_texto(
                    perfil,
                    [
                        "#sellerName",
                        "#storefront-link",
                        "h1",
                        "h2",
                        "[data-testid='seller-name']",
                    ],
                    timeout_ms=1200,
                )
                nome_perfil = _limpar_nome_vendedor(nome_perfil)
                if nome_perfil:
                    nome = nome_perfil
            else:
                fonte_doc = fonte_doc or "perfil_redirecionou_login"

        # Fallback: documento pode ter vindo do card/lista.
        if not doc:
            doc_card, tipo_card = _extrair_documento(vendedor.get("seller_offer_raw_text") or "")
            if doc_card:
                doc = doc_card
                tipo_doc = tipo_card
                fonte_doc = fonte_doc or "lista_ofertas"

        if tipo_doc == "CPF" and saida_base is not None:
            if perfil is not None and not _pagina_login_amazon(perfil):
                print_path = _salvar_print_cpf(perfil, saida_base, pid, indice, nome)
            elif card_fallback is not None:
                print_path = _salvar_print_cpf(card_fallback, saida_base, pid, indice, nome)

        vendedor.update(
            {
                "seller_index": indice,
                "seller_name": nome,
                "seller_profile_url": perfil_url,
                "seller_doc": doc,
                "seller_doc_type": tipo_doc,
                "seller_doc_source": fonte_doc,
                "seller_profile_text_sample": perfil_texto,
                "seller_cpf_print_path": print_path,
            }
        )

        if tipo_doc == "CNPJ":
            log("vendedor amazon", f"vendedor {indice}/{total} - {nome} - CNPJ ENCONTRADO: {doc}")
        elif tipo_doc == "CPF":
            log("vendedor amazon", f"vendedor {indice}/{total} - {nome} - CPF ENCONTRADO: {doc}")
            if print_path:
                log("vendedor amazon", f"print adicionado em: {print_path}")
            else:
                log("vendedor amazon", "CPF encontrado, mas não consegui salvar o print individual.")
        else:
            log("vendedor amazon", f"vendedor {indice}/{total} - {nome} - DOCUMENTO NÃO ENCONTRADO")

        return vendedor

    finally:
        try:
            if perfil is not None:
                perfil.close()
        except Exception:
            pass


# ============================================================
# Função pública
# ============================================================


def analisar_vendedor_amazon(
    page: Page,
    context: BrowserContext | None = None,
    saida_base: str | Path | None = None,
    pid: str = "",
    product_name: str = "",
    *args: Any,
    **kwargs: Any,
) -> dict[str, Any]:
    """Analisa vendedores da Amazon individualmente.

    Fluxo:
    1. Abre a aba/lista de vendedores/ofertas.
    2. Conta vendedores únicos e analisáveis.
    3. Entra no perfil de cada vendedor, um a um.
    4. Rola a tela do perfil até localizar CPF/CNPJ.
    5. Se encontrar CPF, salva print da tela individual do vendedor.
    6. Retorna lista detalhada para sellers.parquet e campos agregados mínimos.
    """
    bloco("vendedor amazon")

    saida_path = Path(saida_base) if saida_base is not None else None
    pid = pid or gerar_id(product_name, page.url)

    lista_page = _abrir_lista_vendedores(page, context=context)
    lista_aberta_em_nova_aba = lista_page is not page

    try:
        vendedores, cards = _coletar_vendedores_da_lista(lista_page)

        # Fallback: vendedor principal da página do produto.
        if not vendedores:
            principal = _vendedor_principal_do_produto(page)
            if principal:
                vendedores = _deduplicar([principal])
                cards = []

        total = len(vendedores)
        log("vendedor amazon", f"Lista/aba de vendedores aberta. Vendedores únicos encontrados: {total}")

        vendedores_analisados: list[dict[str, Any]] = []
        for idx, vendedor in enumerate(vendedores, start=1):
            card = cards[idx - 1] if idx - 1 < len(cards) else None
            analisado = _analisar_um_vendedor(
                vendedor=vendedor,
                indice=idx,
                total=total,
                context=context,
                saida_base=saida_path,
                pid=pid,
                card_fallback=card,
            )
            vendedores_analisados.append(analisado)

        cpf_count = sum(1 for v in vendedores_analisados if v.get("seller_doc_type") == "CPF")
        cnpj_count = sum(1 for v in vendedores_analisados if v.get("seller_doc_type") == "CNPJ")
        sem_doc_count = sum(1 for v in vendedores_analisados if not v.get("seller_doc_type"))

        return {
            "seller_count": total,
            "seller_cpf_count": cpf_count,
            "seller_cnpj_count": cnpj_count,
            "seller_sem_doc_count": sem_doc_count,
            "seller_has_cpf": cpf_count > 0,
            "sellers_json": json.dumps(vendedores_analisados, ensure_ascii=False),
            "__sellers_list": vendedores_analisados,
        }

    finally:
        if lista_aberta_em_nova_aba:
            try:
                lista_page.close()
            except Exception:
                pass
