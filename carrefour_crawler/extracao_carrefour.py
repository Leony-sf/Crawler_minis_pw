# -*- coding: utf-8 -*-
"""Funções de extração para o crawler Carrefour."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List
from urllib.parse import unquote, urljoin, urlparse

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError


BASE_URL = "https://www.carrefour.com.br"
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


def limpar_texto(txt: str | None) -> str:
    txt = txt or ""
    txt = txt.replace("\xa0", " ").replace("\u200b", " ")
    return re.sub(r"\s+", " ", txt).strip()


def normalizar_url(url: str) -> str:
    url = (url or "").strip().strip('"').strip("'")
    url = url.replace("\\/", "/")
    url = unquote(url)
    url = url.split("#")[0]

    if url.startswith("//"):
        url = "https:" + url

    return urljoin(BASE_URL, url)


def url_produto_valida(url: str) -> bool:
    if not url:
        return False

    url = normalizar_url(url)
    parsed = urlparse(url)
    netloc = parsed.netloc.lower()
    path = parsed.path.lower().rstrip("/")

    if "carrefour.com.br" not in netloc:
        return False

    bloqueios = [
        "/busca", "/s", "/categoria", "/hotsite", "/landingpage", "/login",
        "/checkout", "/especial", "/marca", "/favoritos", "/minha-conta",
        "/carrinho", "/atendimento", "/campanha", "/servicos", "/institucional",
    ]
    if any(path == bloqueio or path.startswith(bloqueio + "/") for bloqueio in bloqueios):
        return False

    if "/produto/" in path:
        return True

    if path.endswith("/p") or "/p/" in path:
        return True

    if re.search(r"/[^/]+-\d{5,}/p$", path):
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


async def esperar_carregamento(page: Page, timeout_ms: int = 30000) -> None:
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
    except PlaywrightTimeoutError:
        pass

    try:
        await page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 12000))
    except Exception:
        pass

    try:
        await page.wait_for_timeout(2200)
    except Exception:
        pass


async def fechar_popups_basicos(page: Page) -> None:
    """
    No Carrefour, não preencher CEP automaticamente.
    Apenas aceita cookies/popups simples que não interferem no fluxo.
    """
    textos_cookies = [
        "Aceitar cookies",
        "Aceitar todos",
        "Aceitar",
        "Concordo",
        "Entendi",
        "OK",
        "Ok",
        "ok",
    ]

    for texto in textos_cookies:
        try:
            botao = page.get_by_text(texto, exact=False).first

            if await botao.count():
                await botao.click(timeout=900)
                await page.wait_for_timeout(350)
                return
        except Exception:
            pass

    seletores_cookie = [
        "button:has-text('Aceitar')",
        "button:has-text('Aceitar cookies')",
        "button:has-text('Aceitar todos')",
        "[id*='cookie'] button",
        "[class*='cookie'] button",
        "[data-testid*='cookie'] button",
    ]

    for seletor in seletores_cookie:
        try:
            botao = page.locator(seletor).first

            if await botao.count():
                await botao.click(timeout=900)
                await page.wait_for_timeout(350)
                return
        except Exception:
            pass


async def rolar_busca(page: Page) -> None:
    try:
        await page.wait_for_timeout(900)

        for _ in range(7):
            await page.mouse.wheel(0, 1200)
            await page.wait_for_timeout(650)

        await page.mouse.wheel(0, -900)
        await page.wait_for_timeout(600)
    except Exception:
        pass


async def coletar_links_por_anchors(page: Page) -> List[Dict[str, Any]]:
    seletores = [
        "a[href*='/produto/']",
        "a[href$='/p']",
        "a[href*='/p?']",
        "a[href*='carrefour.com.br/produto']",
        "a[href*='carrefour.com.br/'][href$='/p']",
        "a[href]",
    ]

    vistos: set[str] = set()
    itens: List[Dict[str, Any]] = []

    for seletor in seletores:
        try:
            anchors = page.locator(seletor)
            total = await anchors.count()
        except Exception:
            continue

        for indice in range(min(total, 900)):
            try:
                anchor = anchors.nth(indice)
                href = await anchor.get_attribute("href")

                if not href:
                    continue

                url = normalizar_url(href)

                if not url_produto_valida(url) or url in vistos:
                    continue

                texto = limpar_texto(await anchor.inner_text(timeout=900))

                if len(texto) < 5:
                    texto = limpar_texto(await anchor.get_attribute("title"))

                if len(texto) < 5:
                    try:
                        pai = anchor.locator("xpath=ancestor::*[self::li or self::article or self::div][1]").first
                        texto = limpar_texto(await pai.inner_text(timeout=700))
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


async def coletar_links_por_dom_js(page: Page) -> List[Dict[str, Any]]:
    try:
        dados = await page.evaluate(
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
        r"https?://(?:www\.)?carrefour\.com\.br/[^\"'<>\\\s]+?/p(?:\?[^\"'<>\\\s]+)?",
        r"https?://(?:www\.)?carrefour\.com\.br/produto/[^\"'<>\\\s]+",
        r"https?://(?:www\.)?carrefour\.com\.br/p/[^\"'<>\\\s]+",
        r"//(?:www\.)?carrefour\.com\.br/[^\"'<>\\\s]+?/p(?:\?[^\"'<>\\\s]+)?",
        r"//(?:www\.)?carrefour\.com\.br/produto/[^\"'<>\\\s]+",
        r"//(?:www\.)?carrefour\.com\.br/p/[^\"'<>\\\s]+",
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


async def coletar_links_por_html(page: Page) -> List[Dict[str, Any]]:
    try:
        html = await page.content()
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


async def coletar_links_por_texto_renderizado(page: Page) -> List[Dict[str, Any]]:
    try:
        texto = await page.locator("body").inner_text(timeout=2000)
    except Exception:
        return []

    vistos: set[str] = set()
    itens: List[Dict[str, Any]] = []

    for url in extrair_urls_de_html(texto):
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


async def coletar_links_resultados(page: Page) -> List[Dict[str, Any]]:
    await rolar_busca(page)

    seletores_indicio = [
        "a[href*='/produto/']",
        "a[href*='/p/']",
        "a[href$='/p']",
        "[data-testid*='product']",
        "article",
        "li",
    ]

    for seletor in seletores_indicio:
        try:
            await page.locator(seletor).first.wait_for(timeout=3500)
            break
        except Exception:
            continue

    funcoes = [
        coletar_links_por_anchors,
        coletar_links_por_dom_js,
        coletar_links_por_html,
        coletar_links_por_texto_renderizado,
    ]

    vistos: set[str] = set()
    itens_finais: List[Dict[str, Any]] = []

    for funcao in funcoes:
        itens = await funcao(page)

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


async def texto_primeiro(page: Page, seletores: List[str], timeout: int = 900) -> str:
    for seletor in seletores:
        try:
            loc = page.locator(seletor).first

            if await loc.count():
                texto = limpar_texto(await loc.inner_text(timeout=timeout))

                if texto:
                    return texto
        except Exception:
            continue

    return ""


async def atributo_primeiro(page: Page, seletores: List[str], atributo: str) -> str:
    for seletor in seletores:
        try:
            loc = page.locator(seletor).first

            if await loc.count():
                valor = await loc.get_attribute(atributo)

                if valor:
                    return valor.strip()
        except Exception:
            continue

    return ""


async def extrair_json_ld(page: Page) -> Dict[str, Any]:
    dados: Dict[str, Any] = {}

    try:
        scripts = await page.locator("script[type='application/ld+json']").all()

        for script in scripts:
            try:
                raw = await script.text_content(timeout=700)

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


async def abrir_secoes_de_detalhes(page: Page) -> None:
    textos = [
        "Ver mais", "Mostrar mais", "Descrição", "Ficha técnica", "Características",
        "Informações do produto", "Detalhes do produto", "Especificações",
    ]

    for texto in textos:
        try:
            botao = page.get_by_text(texto, exact=False).first

            if await botao.count():
                await botao.click(timeout=900)
                await page.wait_for_timeout(450)
        except Exception:
            pass


async def extrair_blocos_informacao(page: Page) -> str:
    seletores = [
        "section",
        "article",
        "table",
        "dl",
        "ul",
        "[data-testid*='spec']",
        "[data-testid*='description']",
        "[data-testid*='product']",
        "[class*='spec']",
        "[class*='description']",
        "[class*='Descricao']",
        "[class*='Product']",
        "[class*='produto']",
    ]

    blocos: List[str] = []

    for seletor in seletores:
        try:
            loc = page.locator(seletor)
            total = await loc.count()

            for indice in range(min(total, 60)):
                texto = limpar_texto(await loc.nth(indice).inner_text(timeout=700))
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


async def extrair_produto(page: Page, url_produto: str, card: Dict[str, Any]) -> Dict[str, Any]:
    await esperar_carregamento(page)
    await fechar_popups_basicos(page)
    await abrir_secoes_de_detalhes(page)

    try:
        await page.mouse.wheel(0, 1100)
        await page.wait_for_timeout(900)
        await page.mouse.wheel(0, 1600)
        await page.wait_for_timeout(900)
    except Exception:
        pass

    jsonld = await extrair_json_ld(page)

    titulo = await texto_primeiro(page, [
        "h1",
        "[data-testid='product-title']",
        "[data-testid*='title']",
        "[class*='ProductTitle']",
        "[class*='product-title']",
    ])

    if not titulo:
        titulo = limpar_texto(await page.title())

    if not titulo:
        titulo = jsonld.get("name", "") or card.get("titulo_busca", "")

    preco = await texto_primeiro(page, [
        "[data-testid='price-value']",
        "[data-testid*='price']",
        "[class*='price']",
        "[class*='Price']",
    ])

    if not preco and jsonld.get("price"):
        preco = f"R$ {jsonld.get('price')}"

    if not preco:
        try:
            body_txt = await page.locator("body").inner_text(timeout=1500)
            match = re.search(r"R\$\s?\d{1,3}(?:\.\d{3})*,\d{2}", body_txt)

            if match:
                preco = match.group(0)
        except Exception:
            pass

    imagem = await atributo_primeiro(page, ["meta[property='og:image']"], "content")

    if not imagem:
        imagem = await atributo_primeiro(page, ["img[data-testid*='image']", "img[src*='carrefour']", "img[src]"], "src")

    if not imagem:
        imagem = jsonld.get("image", "")

    fornecedor = ""
    body_small = ""

    try:
        body_small = limpar_texto((await page.locator("body").inner_text(timeout=2500))[:14000])
        match = re.search(
            r"(?:vendido por|vendida por|loja parceira|fornecedor)\s*:??\s*([^|\n\r]{3,90})",
            body_small,
            re.IGNORECASE,
        )

        if match:
            fornecedor = limpar_texto(match.group(1))
    except Exception:
        body_small = ""

    detalhes = await extrair_blocos_informacao(page)
    ficha_tecnica = detalhes
    texto_pagina = body_small

    if not texto_pagina:
        try:
            texto_pagina = limpar_texto(await page.locator("body").inner_text(timeout=3000))[:30000]
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


# Aliases mantidos apenas para evitar quebra caso algum arquivo antigo use nomes com sublinhado.
_limpar_texto = limpar_texto
_normalizar_url = normalizar_url
_url_produto_valida = url_produto_valida
_texto_parece_produto_relevante = texto_parece_produto_relevante
_scroll_busca = rolar_busca
_texto_primeiro = texto_primeiro
_atributo_primeiro = atributo_primeiro
_extrair_json_ld = extrair_json_ld
_extrair_blocos_informacao = extrair_blocos_informacao
