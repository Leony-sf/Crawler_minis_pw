# -*- coding: utf-8 -*-
"""Extração limpa para Casas Bahia.

Fluxo:
- não clicar em busca;
- não preencher CEP;
- não aceitar autocomplete;
- rolar a página sem clicar;
- coletar links;
- abrir produtos por URL direta no crawler principal.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List
from urllib.parse import unquote, urljoin, urlparse

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError


BASE_URL = "https://www.casasbahia.com.br"


TERMOS_RELEVANTES_BUSCA = [
    "celular", "smartphone", "telefone", "phone", "mobile", "dual chip", "dual sim",
    "sim card", "gsm", "2g", "3g", "4g", "5g", "lte", "volte", "iphone",
    "samsung", "galaxy", "motorola", "moto ", "xiaomi", "redmi", "positivo",
    "nokia", "multilaser", "lg ", "lg-", "flip", "tijolinho", "feature phone",
    "mini celular", "mini phone", "bluetooth dialer", "ponto eletrônico",
    "l8star", "gtstar", "bm70", "bm30", "bm10", "bm50", "soyes", "melrose",
]

TERMOS_DESCARTE_OBVIO_BUSCA = [
    "chocolate", "amendoim", "amêndoa", "amendoas", "biscoito", "bolacha",
    "leite", "lacta", "garoto", "nestlé", "nestle", "café", "cafe",
    "açúcar", "acucar", "arroz", "feijão", "feijao", "macarrão", "macarrao",
    "molho", "tempero", "salgadinho", "suco", "refrigerante", "vinho",
    "cerveja", "ração", "racao", "shampoo", "condicionador", "sabonete",
    "fralda", "detergente", "desinfetante", "limpador", "desodorante",
    "perfume", "creme dental", "escova dental", "petisco",
]


def limpar_texto(texto: str | None) -> str:
    texto = texto or ""
    texto = texto.replace("\xa0", " ").replace("\u200b", " ")
    return re.sub(r"\s+", " ", texto).strip()


def normalizar_url(url: str) -> str:
    url = (url or "").strip().strip('"').strip("'")
    url = url.replace("\\/", "/")
    url = unquote(url)
    url = url.split("#")[0]

    if url.startswith("//"):
        url = "https:" + url

    return urljoin(BASE_URL, url)


def pagina_erro_casas_bahia(page) -> bool:
    """Verifica se caiu no bloqueio pesado da Akamai (Bonequinho/IP) ignorando erros comuns 404."""
    try:
        texto = page.locator("body").inner_text(timeout=2000).lower()
        if "reference id:" in texto and "client ip:" in texto:
            return True
        if "alguns detalhes do erro:" in texto:
            return True
        return False
    except Exception:
        return False


def url_produto_valida(url: str) -> bool:
    if not url:
        return False

    url = normalizar_url(url)
    parsed = urlparse(url)
    netloc = parsed.netloc.lower()
    path = parsed.path.lower().rstrip("/")

    if "casasbahia.com.br" not in netloc:
        return False

    bloqueios = [
        "/busca", "/s", "/search", "/categoria", "/hotsite", "/landingpage",
        "/login", "/checkout", "/especial", "/marca", "/favoritos",
        "/minha-conta", "/carrinho", "/atendimento", "/campanha",
        "/servicos", "/institucional",
    ]
    if any(path == bloqueio or path.startswith(bloqueio + "/") for bloqueio in bloqueios):
        return False

    if "/produto/" in path:
        return True
    if path.endswith("/p") or "/p/" in path:
        return True
    if re.search(r"/[^/]+-\d{5,}/p$", path):
        return True
    if re.search(r"/p/\d{5,}", path):
        return True

    return False


def texto_parece_produto_relevante(texto: str, url: str = "") -> bool:
    texto_base = limpar_texto(f"{texto or ''} {url or ''}").lower()
    if not texto_base:
        return False

    tem_relevante = any(termo in texto_base for termo in TERMOS_RELEVANTES_BUSCA)
    tem_descarte = any(termo in texto_base for termo in TERMOS_DESCARTE_OBVIO_BUSCA)

    if tem_descarte and not tem_relevante:
        return False

    return tem_relevante


def esperar_carregamento(page: Page, timeout_ms: int = 30000) -> None:
    try:
        page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
    except PlaywrightTimeoutError:
        pass

    try:
        page.wait_for_timeout(2000)
    except Exception:
        pass


def aceitar_cookies_se_aparecer(page: Page) -> None:
    seletores = [
        "button:has-text('Aceitar cookies')",
        "button:has-text('Aceitar todos')",
        "button:has-text('Aceitar')",
        "button:has-text('Concordo')",
        "[id*='cookie'] button",
        "[class*='cookie'] button",
        "[data-testid*='cookie'] button",
    ]

    for seletor in seletores:
        try:
            botao = page.locator(seletor).first
            if botao.count():
                botao.click(timeout=700)
                page.wait_for_timeout(250)
                return
        except Exception:
            pass


def rolar_busca_sem_clicar(page: Page) -> None:
    try:
        page.wait_for_timeout(800)
        for _ in range(8):
            page.mouse.wheel(0, 1200)
            page.wait_for_timeout(400)
        page.mouse.wheel(0, -900)
        page.wait_for_timeout(500)
    except Exception:
        pass


def coletar_links_por_anchors(page: Page) -> List[Dict[str, Any]]:
    seletores = [
        "a[href*='/produto/']",
        "a[href*='/p/']",
        "a[href$='/p']",
        "a[href*='casasbahia.com.br/produto']",
        "a[href*='casasbahia.com.br/'][href$='/p']",
        "a[href]",
    ]

    vistos: set[str] = set()
    itens: List[Dict[str, Any]] = []

    for seletor in seletores:
        try:
            anchors = page.locator(seletor)
            total = anchors.count()
        except Exception:
            continue

        for indice in range(min(total, 1000)):
            try:
                anchor = anchors.nth(indice)
                href = anchor.get_attribute("href")
                if not href:
                    continue

                url = normalizar_url(href)
                if not url_produto_valida(url) or url in vistos:
                    continue

                texto = ""
                try:
                    texto = limpar_texto(anchor.inner_text(timeout=600))
                except Exception:
                    pass

                if len(texto) < 5:
                    try:
                        texto = limpar_texto(anchor.get_attribute("title"))
                    except Exception:
                        pass

                if len(texto) < 5:
                    try:
                        pai = anchor.locator("xpath=ancestor::*[self::li or self::article or self::div][1]").first
                        texto = limpar_texto(pai.inner_text(timeout=600))
                    except Exception:
                        pass

                if not texto_parece_produto_relevante(texto, url):
                    continue

                vistos.add(url)
                itens.append({
                    "url": url,
                    "titulo_busca": texto[:500],
                    "texto_card": texto[:1800],
                })
            except Exception:
                continue

        if itens:
            break

    return itens


def coletar_links_por_dom_js(page: Page) -> List[Dict[str, Any]]:
    try:
        dados = page.evaluate(
            """
            () => {
                const out = [];
                const anchors = Array.from(document.querySelectorAll('a[href]'));
                for (const a of anchors) {
                    const href = a.href || a.getAttribute('href') || '';
                    const card = a.closest('li, article, [data-testid], div');
                    const texto = ((card && card.innerText) || a.innerText || a.title || '')
                        .replace(/\\s+/g, ' ')
                        .trim();
                    out.push({ href, texto });
                }
                return out;
            }
            """
        )
    except Exception:
        return []

    vistos: set[str] = set()
    itens: List[Dict[str, Any]] = []

    for item in dados or []:
        href = item.get("href", "")
        url = normalizar_url(href)
        if not url_produto_valida(url) or url in vistos:
            continue

        texto = limpar_texto(item.get("texto", ""))
        if not texto_parece_produto_relevante(texto, url):
            continue

        vistos.add(url)
        itens.append({
            "url": url,
            "titulo_busca": texto[:500],
            "texto_card": texto[:1800],
        })

    return itens


def extrair_urls_de_html(html: str) -> List[str]:
    html = html or ""
    html = html.replace("\\/", "/")

    padroes = [
        r"https?://(?:www\.)?casasbahia\.com\.br/[^\"'<>\\\s]+?/p(?:/[^\"'<>\\\s]+)?(?:\?[^\"'<>\\\s]+)?",
        r"https?://(?:www\.)?casasbahia\.com\.br/produto/[^\"'<>\\\s]+",
        r"https?://(?:www\.)?casasbahia\.com\.br/p/[^\"'<>\\\s]+",
        r"//(?:www\.)?casasbahia\.com\.br/[^\"'<>\\\s]+?/p(?:/[^\"'<>\\\s]+)?(?:\?[^\"'<>\\\s]+)?",
        r"//(?:www\.)?casasbahia\.com\.br/produto/[^\"'<>\\\s]+",
        r"//(?:www\.)?casasbahia\.com\.br/p/[^\"'<>\\\s]+",
        r"(?<![a-zA-Z])/(?:[a-z0-9-]+/)*[a-z0-9-]+-\d{5,}/p(?:\?[^\"'<>\\\s]+)?",
        r"(?<![a-zA-Z])/(?:produto|p)/[^\"'<>\\\s]+",
    ]

    candidatos: List[str] = []
    for padrao in padroes:
        candidatos.extend(re.findall(padrao, html, flags=re.IGNORECASE))

    for match in re.finditer(
        r'"(?:url|href|productUrl|canonicalUrl)"\s*:\s*"([^"]+)"',
        html,
        flags=re.IGNORECASE,
    ):
        candidatos.append(match.group(1))

    return [normalizar_url(candidato) for candidato in candidatos]

def coletar_links_por_html(page: Page) -> List[Dict[str, Any]]:
    try:
        html = page.content()
    except Exception:
        return []

    vistos: set[str] = set()
    itens: List[Dict[str, Any]] = []

    for url in extrair_urls_de_html(html):
        if not url_produto_valida(url) or url in vistos:
            continue

        if not texto_parece_produto_relevante("", url):
            continue

        vistos.add(url)
        itens.append({
            "url": url,
            "titulo_busca": "",
            "texto_card": "",
        })

    return itens


def coletar_links_resultados(page: Page) -> List[Dict[str, Any]]:
    aceitar_cookies_se_aparecer(page)
    rolar_busca_sem_clicar(page)

    funcoes = [
        coletar_links_por_anchors,
        coletar_links_por_dom_js,
        coletar_links_por_html,
    ]

    vistos: set[str] = set()
    itens_finais: List[Dict[str, Any]] = []

    for funcao in funcoes:
        itens = funcao(page)

        for item in itens:
            url = normalizar_url(item.get("url", ""))
            if not url_produto_valida(url) or url in vistos:
                continue

            vistos.add(url)
            item["url"] = url
            itens_finais.append(item)

        if itens_finais:
            break

    return itens_finais


def texto_primeiro(page: Page, seletores: List[str], timeout: int = 900) -> str:
    for seletor in seletores:
        try:
            loc = page.locator(seletor).first
            if loc.count():
                texto = limpar_texto(loc.inner_text(timeout=timeout))
                if texto:
                    return texto
        except Exception:
            continue
    return ""


def atributo_primeiro(page: Page, seletores: List[str], atributo: str) -> str:
    for seletor in seletores:
        try:
            loc = page.locator(seletor).first
            if loc.count():
                valor = loc.get_attribute(atributo)
                if valor:
                    return valor.strip()
        except Exception:
            continue
    return ""


def extrair_json_ld(page: Page) -> Dict[str, Any]:
    dados: Dict[str, Any] = {}

    try:
        scripts = page.locator("script[type='application/ld+json']").all()
        for script in scripts:
            try:
                raw = script.text_content(timeout=700)
                if not raw:
                    continue

                obj = json.loads(raw)
                objs = obj if isinstance(obj, list) else [obj]

                for item in objs:
                    if not isinstance(item, dict):
                        continue

                    tipo = str(item.get("@type", "")).lower()
                    if "product" in tipo or item.get("name"):
                        if item.get("name") and not dados.get("name"):
                            dados["name"] = limpar_texto(str(item.get("name")))

                        offers = item.get("offers")
                        if isinstance(offers, dict):
                            price = offers.get("price") or offers.get("lowPrice")
                            if price and not dados.get("price"):
                                dados["price"] = str(price)

                        if item.get("image") and not dados.get("image"):
                            imagem = item.get("image")
                            dados["image"] = imagem[0] if isinstance(imagem, list) and imagem else str(imagem)
            except Exception:
                continue
    except Exception:
        pass

    return dados


def abrir_secoes_de_detalhes(page: Page) -> None:
    textos = [
        "Ver mais", "Mostrar mais", "Descrição", "Ficha técnica",
        "Características", "Informações do produto", "Detalhes do produto", "Especificações",
    ]

    for texto in textos:
        try:
            botao = page.get_by_text(texto, exact=False).first
            if botao.count():
                botao.click(timeout=700)
                page.wait_for_timeout(250)
        except Exception:
            pass


def extrair_blocos_informacao(page: Page) -> str:
    seletores = [
        "section", "article", "table", "dl", "ul",
        "[data-testid*='spec']", "[data-testid*='description']",
        "[data-testid*='product']", "[class*='spec']", "[class*='description']",
        "[class*='Descricao']", "[class*='Product']", "[class*='produto']",
    ]

    blocos: List[str] = []

    for seletor in seletores:
        try:
            loc = page.locator(seletor)
            total = loc.count()

            for indice in range(min(total, 60)):
                texto = limpar_texto(loc.nth(indice).inner_text(timeout=700))
                texto_lower = texto.lower()

                if len(texto) > 30 and any(
                    termo in texto_lower
                    for termo in [
                        "dimens", "altura", "largura", "comprimento", "tela",
                        "chip", "sim", "gsm", "celular", "telefone", "anatel", "produto",
                    ]
                ):
                    blocos.append(texto[:3000])
        except Exception:
            continue

    return " | ".join(dict.fromkeys(blocos))[:12000]


def extrair_produto(page: Page, url_produto: str, card: Dict[str, Any]) -> Dict[str, Any]:
    esperar_carregamento(page)
    aceitar_cookies_se_aparecer(page)
    abrir_secoes_de_detalhes(page)

    jsonld = extrair_json_ld(page)

    titulo = texto_primeiro(page, [
        "h1",
        "[data-testid='product-title']",
        "[data-testid*='title']",
        "[class*='ProductTitle']",
        "[class*='product-title']",
    ])

    if not titulo:
        titulo = limpar_texto(page.title())

    if not titulo:
        titulo = jsonld.get("name", "") or card.get("titulo_busca", "")

    preco = texto_primeiro(page, [
        "[data-testid='price-value']",
        "[data-testid*='price']",
        "[class*='price']",
        "[class*='Price']",
    ])

    if not preco and jsonld.get("price"):
        preco = f"R$ {jsonld.get('price')}"

    if not preco:
        try:
            body_txt = page.locator("body").inner_text(timeout=1500)
            match = re.search(r"R\$\s?\d{1,3}(?:\.\d{3})*,\d{2}", body_txt)
            if match:
                preco = match.group(0)
        except Exception:
            pass

    imagem = atributo_primeiro(page, ["meta[property='og:image']"], "content")

    if not imagem:
        imagem = atributo_primeiro(page, ["img[data-testid*='image']", "img[src*='casasbahia']", "img[src]"], "src")

    if not imagem:
        imagem = jsonld.get("image", "")

    fornecedor = ""
    body_small = ""

    try:
        body_small = limpar_texto((page.locator("body").inner_text(timeout=2500))[:14000])
        match = re.search(
            r"(?:vendido por|vendida por|loja parceira|fornecedor)\s*:??\s*([^|\n\r]{3,90})",
            body_small,
            re.IGNORECASE,
        )
        if match:
            fornecedor = limpar_texto(match.group(1))
    except Exception:
        body_small = ""

    detalhes = extrair_blocos_informacao(page)
    ficha_tecnica = detalhes
    texto_pagina = body_small

    if not texto_pagina:
        try:
            texto_pagina = limpar_texto(page.locator("body").inner_text(timeout=3000))[:30000]
        except Exception:
            texto_pagina = ""

    return {
        "titulo": titulo,
        "preco": preco,
        "fornecedor": fornecedor,
        "moq": "",
        "vendidos_pedidos": "",
        "url": url_produto,
        "url_canonica": page.url or url_produto,
        "imagem": imagem,
        "detalhes": detalhes,
        "ficha_tecnica": ficha_tecnica,
        "texto_card": card.get("texto_card", "") or card.get("titulo_busca", ""),
        "texto_pagina": texto_pagina,
    }


# Aliases de compatibilidade.
_limpar_texto = limpar_texto
_normalizar_url = normalizar_url
_url_produto_valida = url_produto_valida
_texto_parece_produto_relevante = texto_parece_produto_relevante
_scroll_busca = rolar_busca_sem_clicar
_texto_primeiro = texto_primeiro
_atributo_primeiro = atributo_primeiro
_extrair_json_ld = extrair_json_ld
_extrair_blocos_informacao = extrair_blocos_informacao
fechar_popups_basicos = aceitar_cookies_se_aparecer