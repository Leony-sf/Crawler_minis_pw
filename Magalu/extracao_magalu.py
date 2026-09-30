# -*- coding: utf-8 -*-
"""Extração de links e dados de produto no Magalu (Otimizado com JS Injection)."""

from __future__ import annotations

import re
from typing import Any, Dict, List

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from utils_magalu import BASE_URL_MAGALU, limpar_url
from classificacao_magalu import extrair_codigo_anatel


async def fechar_popups_basicos(page: Page) -> None:
    seletores = [
        "button:has-text('Aceitar')",
        "button:has-text('ACEITAR')",
        "button:has-text('Entendi')",
        "button:has-text('OK')",
        "button:has-text('Ok')",
        "button:has-text('Agora não')",
        "button:has-text('Não, obrigado')",
        "button[aria-label='Fechar']",
        "button[aria-label='close']",
        "[data-testid*='close']",
        "[class*='close']",
    ]
    for seletor in seletores:
        try:
            loc = page.locator(seletor).first
            if await loc.count() and await loc.is_visible(timeout=700):
                await loc.click(timeout=1000)
                await page.wait_for_timeout(250)
        except Exception:
            continue


async def esperar_carregamento(page: Page, timeout_ms: int = 20000) -> None:
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
    except PlaywrightTimeoutError:
        pass
    try:
        await page.wait_for_load_state("networkidle", timeout=6000)
    except PlaywrightTimeoutError:
        pass
    await fechar_popups_basicos(page)


async def rolar_pagina(page: Page, passos: int = 4, pausa_ms: int = 650) -> None:
    for _ in range(passos):
        try:
            await page.mouse.wheel(0, 1200)
            await page.wait_for_timeout(pausa_ms)
        except Exception:
            break


def _parece_link_produto(url: str) -> bool:
    url_l = url.lower()
    if "magazineluiza.com.br" not in url_l:
        return False
    if "/busca/" in url_l or "/departamentos/" in url_l or "/marcas/" in url_l:
        return False
    if any(x in url_l for x in ["/sacola", "/login", "/cadastro", "/atendimento", "/servicos"]):
        return False
    return "/p/" in url_l


async def coletar_links_resultados(page: Page) -> List[Dict[str, Any]]:
    await rolar_pagina(page, passos=5, pausa_ms=650)

    # JavaScript Injetado: Extrai todos os links e textos de uma vez direto no navegador
    script = r"""
    () => {
        const saida = [];
        for (const a of document.querySelectorAll('a[href]')) {
            let href = a.getAttribute('href') || '';
            if (!href) continue;

            let texto_link = (a.innerText || a.textContent || '').trim();
            let texto_card = texto_link;

            let parent = a.closest('[data-testid*="product"], li, article, div');
            if (parent) {
                texto_card = (parent.innerText || parent.textContent || '').trim();
            }

            let titulo_attr = a.getAttribute('title') || '';
            let aria = a.getAttribute('aria-label') || '';
            let titulo = titulo_attr || aria || texto_link || (texto_card.split('\n')[0] || '');

            titulo = titulo.replace(/\s+/g, ' ').trim();
            texto_card = texto_card.replace(/\s+/g, ' ').trim();

            saida.push({ href: href, titulo_busca: titulo, texto_card: texto_card });
        }
        return saida;
    }
    """

    try:
        elementos = await page.evaluate(script) or []
    except Exception:
        elementos = []

    vistos = set()
    resultados: List[Dict[str, Any]] = []

    for item in elementos:
        href = item.get("href", "")
        if not href:
            continue

        url = limpar_url(href)
        if not url.startswith("http"):
            url = limpar_url(BASE_URL_MAGALU + href)

        if not _parece_link_produto(url) or url in vistos:
            continue

        vistos.add(url)
        resultados.append({
            "url": url,
            "titulo_busca": item.get("titulo_busca", ""),
            "texto_card": item.get("texto_card", "")
        })

    return resultados


def _extrair_atributo_generico(texto: str, atributo: str) -> str:
    m = re.search(rf"{atributo}\s*:?\s*([^\n|]+)", texto, re.IGNORECASE)
    return m.group(1).strip() if m else ""


async def capturar_comentarios(page: Page, limite: int = 10) -> list[str]:
    if limite <= 0:
        return []

    try:
        for _ in range(4):
            await page.mouse.wheel(0, 1500)
            await page.wait_for_timeout(800)
    except Exception:
        pass

    # JavaScript Injetado: Varre avaliações rapidamente
    script = r"""
    (limite) => {
        const seletores = [
            "[data-testid='review-description']",
            "[data-testid='review-text']",
            ".review-text",
            ".review-description",
            "p[data-testid='review-content']",
            "[class*='review'] [class*='description']"
        ];
        const saida = [];
        const vistos = new Set();

        for (const sel of seletores) {
            const els = document.querySelectorAll(sel);
            for (const el of els) {
                let txt = (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
                if (txt.length >= 15 && !vistos.has(txt)) {
                    vistos.add(txt);
                    saida.push(txt);
                    if (saida.length >= limite) return saida;
                }
            }
            if (saida.length >= limite) break;
        }
        return saida;
    }
    """

    try:
        comentarios = await page.evaluate(script, limite) or []
    except Exception:
        comentarios = []

    return comentarios


async def extrair_produto(page: Page, url: str, card: Dict[str, Any] | None = None) -> Dict[str, Any]:
    card = card or {}
    await esperar_carregamento(page)
    await rolar_pagina(page, passos=6, pausa_ms=500)

    # JavaScript Injetado: Extrai título, preço, imagem e body inteiro de uma vez
    script = r"""
    () => {
        const getPrimeiroTexto = (seletores) => {
            for (const sel of seletores) {
                const el = document.querySelector(sel);
                if (el && el.innerText) return el.innerText.replace(/\s+/g, ' ').trim();
            }
            return "";
        };
        const getMeta = (sel) => {
            const el = document.querySelector(sel);
            return el ? (el.getAttribute('content') || '').trim() : "";
        };

        let titulo = getPrimeiroTexto([
            "h1[data-testid*='heading']", "h1", "[data-testid='product-title']",
            "[class*='ProductTitle']", "[class*='product-title']"
        ]) || getMeta("meta[property='og:title']");

        let preco = getPrimeiroTexto([
            "[data-testid='price-value']", "[data-testid*='price']",
            "[class*='Price']", "[class*='price']"
        ]);
        
        if (!preco) {
            const els = document.querySelectorAll("p, span");
            for (const el of els) {
                if (el.innerText && el.innerText.includes('R$')) {
                    preco = el.innerText.replace(/\s+/g, ' ').trim();
                    break;
                }
            }
        }

        let imagem = getMeta("meta[property='og:image']");
        if (!imagem) {
            const img = document.querySelector("img");
            if (img) imagem = img.getAttribute("src") || "";
        }

        let texto_pagina = document.body ? document.body.innerText.replace(/\s+/g, ' ').trim() : "";

        return {titulo, preco, imagem, texto_pagina};
    }
    """

    try:
        dados = await page.evaluate(script) or {}
    except Exception:
        dados = {}

    titulo = dados.get("titulo", "") or card.get("titulo_busca", "")
    preco = dados.get("preco", "")
    imagem = dados.get("imagem", "")
    texto_pagina = dados.get("texto_pagina", "")

    ficha = _extrair_ficha_tecnica(texto_pagina)
    detalhes = _extrair_trecho_detalhes(texto_pagina)
    vendedor = _extrair_vendedor(texto_pagina)
    avaliacao = _extrair_avaliacao(texto_pagina)
    
    texto_combinado = f"{detalhes} {ficha}"
    marca = _extrair_atributo_generico(texto_combinado, "Marca") or card.get("marca", "")
    modelo = _extrair_atributo_generico(texto_combinado, "Modelo")
    codigo_anatel = extrair_codigo_anatel(texto_pagina)

    comentarios = await capturar_comentarios(page, limite=10)

    return {
        "url": url,
        "url_canonica": limpar_url(url),
        "titulo": titulo,
        "preco": preco,
        "marca": marca,
        "modelo": modelo,
        "codigo_anatel_principal": codigo_anatel,
        "fornecedor": vendedor,
        "moq": "",
        "vendidos_pedidos": avaliacao,
        "imagem": imagem,
        "detalhes": detalhes,
        "ficha_tecnica": ficha,
        "texto_card": card.get("texto_card", ""),
        "texto_pagina": texto_pagina[:80000],
        "comentarios": comentarios,
    }


def _extrair_trecho_detalhes(texto: str) -> str:
    if not texto:
        return ""
    marcadores = [
        "Informações do Produto", "Informacoes do Produto", "Descrição do Produto", "Descricao do Produto",
        "Características", "Caracteristicas", "Ficha Técnica", "Ficha Tecnica", "Dados do produto",
        "Especificações", "Especificacoes",
    ]
    lower = texto.lower()
    indices = [lower.find(m.lower()) for m in marcadores if lower.find(m.lower()) >= 0]
    if not indices:
        return texto[:5000]
    inicio = min(indices)
    return texto[inicio : inicio + 10000]


def _extrair_ficha_tecnica(texto: str) -> str:
    if not texto:
        return ""
    lower = texto.lower()
    marcadores_inicio = ["ficha técnica", "ficha tecnica", "características", "caracteristicas", "especificações", "especificacoes"]
    marcadores_fim = ["avaliações", "avaliacoes", "perguntas", "produtos relacionados", "quem viu", "também comprou"]
    inicios = [lower.find(m) for m in marcadores_inicio if lower.find(m) >= 0]
    if not inicios:
        return ""
    inicio = min(inicios)
    fim = len(texto)
    for m in marcadores_fim:
        idx = lower.find(m, inicio + 30)
        if idx >= 0:
            fim = min(fim, idx)
    return texto[inicio:min(fim, inicio + 12000)]


def _extrair_vendedor(texto: str) -> str:
    if not texto:
        return ""
    padroes = [
        r"Vendido\s+por\s+([^\|]{2,90})",
        r"Vendido\s+e\s+entregue\s+por\s+([^\|]{2,90})",
        r"Entregue\s+por\s+([^\|]{2,90})",
    ]
    for p in padroes:
        m = re.search(p, texto, re.IGNORECASE)
        if m:
            vendedor = re.sub(r"\s+", " ", m.group(1)).strip()
            vendedor = re.split(r"(?:Política|Politica|Adicionar|Comprar|R\$|Avalia)", vendedor)[0].strip()
            return vendedor[:120]
    return ""


def _extrair_avaliacao(texto: str) -> str:
    if not texto:
        return ""
    m = re.search(r"(\d+[\d\.,]*\s*(?:avaliaç(?:ão|ões)|avaliacoes|reviews?))", texto, re.IGNORECASE)
    return m.group(1).strip() if m else ""