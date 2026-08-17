# -*- coding: utf-8 -*-
"""Extração de links e dados de produto no Alibaba.com."""

from __future__ import annotations

import re
from typing import Any, Dict, List

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

# IMPORTAÇÕES CORRIGIDAS AQUI
from utils_alibaba import limpar_url, normalizar_chave
from base_anatel_alibaba import normalizar_codigo_anatel


async def fechar_popups_basicos(page: Page) -> None:
    seletores = [
        "button:has-text('Accept')",
        "button:has-text('I agree')",
        "button:has-text('Agree')",
        "button:has-text('Got it')",
        "button:has-text('OK')",
        "button:has-text('No thanks')",
        "button[aria-label='Close']",
        ".next-dialog-close",
        ".ui-dialog-close",
        "[class*='close']",
    ]
    for seletor in seletores:
        try:
            loc = page.locator(seletor).first
            if await loc.count() and await loc.is_visible(timeout=500):
                await loc.click(timeout=1000)
                await page.wait_for_timeout(300)
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


async def rolar_pagina(page: Page, passos: int = 4, pausa_ms: int = 700) -> None:
    for _ in range(passos):
        try:
            await page.mouse.wheel(0, 1200)
            await page.wait_for_timeout(pausa_ms)
        except Exception:
            break


async def coletar_links_resultados(page: Page) -> List[str]:
    await rolar_pagina(page, passos=4, pausa_ms=600)

    seletores_links = [
        "a[href*='/product-detail/']",
        "a[href*='alibaba.com/product-detail']",
    ]

    vistos = set()
    resultados = []

    for seletor in seletores_links:
        try:
            links = page.locator(seletor)
            total = await links.count()
        except Exception:
            continue

        limite = min(total, 160)
        for i in range(limite):
            try:
                href = await links.nth(i).get_attribute("href", timeout=1200)
                if not href:
                    continue

                url = limpar_url(href)
                if "/product-detail/" in url and url not in vistos:
                    vistos.add(url)
                    resultados.append(url)
            except Exception:
                continue

        if resultados:
            break

    return resultados


async def coletar_atributos(page: Page) -> dict[str, str]:
    script = r"""
    () => {
      const saida = [];
      const vistos = new Set();
      const limpar = (valor) => (valor || '').replace(/\s+/g, ' ').trim();
      
      for (const elemento of document.querySelectorAll('.do-entry-list dl, .specification-table tr, [data-role="specification"] dl, .product-properties tr')) {
        const rotulo = elemento.querySelector('dt, th, .attr-name, .title');
        const valor = elemento.querySelector('dd, td, .attr-value, .value');
        if (rotulo && valor) {
            const r = limpar(rotulo.innerText || rotulo.textContent);
            const v = limpar(valor.innerText || valor.textContent);
            if (r && v) {
                const chave = `${r}=>${v}`;
                if (!vistos.has(chave)) {
                    vistos.add(chave);
                    saida.push([r, v]);
                }
            }
        }
      }
      return saida.slice(0, 200);
    }
    """
    try:
        pares = await page.evaluate(script) or []
    except Exception:
        pares = []

    atributos: dict[str, str] = {}
    for rotulo, valor in pares:
        chave = normalizar_chave(rotulo)
        if chave not in atributos or len(str(valor)) < len(atributos[chave]):
            atributos[chave] = str(valor).strip()

    return atributos


async def _primeiro_texto(page: Page, seletores: List[str]) -> str:
    for seletor in seletores:
        try:
            loc = page.locator(seletor).first
            if await loc.count() and await loc.is_visible(timeout=1000):
                txt = (await loc.inner_text(timeout=1000)).strip()
                if txt:
                    return re.sub(r"\s+", " ", txt)
        except Exception:
            continue
    return ""


def _extrair_trecho_detalhes(texto: str) -> str:
    if not texto:
        return ""
    marcadores = [
        "Product descriptions",
        "Product Description",
        "Key attributes",
        "Product details",
        "Specifications",
        "Overview",
    ]
    lower = texto.lower()
    indices = [lower.find(m.lower()) for m in marcadores if lower.find(m.lower()) >= 0]
    if not indices:
        return texto[:5000]
    inicio = min(indices)
    return texto[inicio : inicio + 9000]


async def extrair_produto(page: Page, url: str) -> Dict[str, Any]:
    await esperar_carregamento(page)
    await rolar_pagina(page, passos=5, pausa_ms=500)

    titulo = await _primeiro_texto(
        page,
        [
            "h1",
            "[data-pl='product-title']",
            "[class*='title'] h1",
        ],
    )

    preco = await _primeiro_texto(
        page,
        [
            "[class*='price']",
            "[data-pl='product-price']",
            "span:has-text('US$')",
        ],
    )

    atributos = await coletar_atributos(page)
    
    texto_pagina = ""
    try:
        if await page.locator("body").count():
            texto_pagina = await page.locator("body").inner_text(timeout=5000)
            texto_pagina = re.sub(r"\s+", " ", texto_pagina).strip()
    except Exception:
        pass

    marca = atributos.get(normalizar_chave("brand name")) or atributos.get(normalizar_chave("brand")) or ""
    modelo = atributos.get(normalizar_chave("model number")) or atributos.get(normalizar_chave("model")) or ""

    codigo_anatel = ""
    padroes_anatel = [
        r"(?:anatel|homologa(?:cao|ção))[^\d]{0,40}(\d{8,14})",
        r"(\d{5}[-\s]?\d{2}[-\s]?\d{4})"
    ]
    
    for padrao in padroes_anatel:
        for match in re.finditer(padrao, texto_pagina, flags=re.IGNORECASE):
            cand = normalizar_codigo_anatel(match.group(1))
            if len(cand) == 12:
                codigo_anatel = cand
                break
        if codigo_anatel:
            break

    return {
        "url": url,
        "titulo": titulo,
        "preco": preco,
        "marca": marca,
        "fabricante": marca,
        "modelo": modelo,
        "modelo_detalhado": modelo,
        "modelo_alfanumerico": modelo,
        "numero_modelo": modelo,
        "codigo_anatel_principal": codigo_anatel,
        "descricao": _extrair_trecho_detalhes(texto_pagina),
        "texto_pagina": texto_pagina[:80000] if texto_pagina else "",
        "atributos": atributos,
        "comentarios": []
    }