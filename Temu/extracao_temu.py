from __future__ import annotations

import re
from typing import Any

from playwright.sync_api import Page

from base_anatel import normalizar_codigo_anatel
from utils import normalizar_chave, normalizar_texto


def fechar_modais_iniciais(page: Page) -> None:
    seletores_fechar = [
        "img[alt='close']",
        ".close-btn",
        "[aria-label='Close']",
        "svg.coupon-close"
    ]
    for seletor in seletores_fechar:
        try:
            btn = page.locator(seletor).first
            if btn.count() and btn.is_visible(timeout=1000):
                btn.click(timeout=1000)
                page.wait_for_timeout(500)
        except Exception:
            continue


def expandir_especificacoes(page: Page) -> None:
    textos = ["Ver mais", "Especificações", "Detalhes", "See more", "Details"]
    for texto in textos:
        try:
            btn = page.get_by_text(texto, exact=False).first
            if btn.count() and btn.is_visible(timeout=500):
                btn.scroll_into_view_if_needed(timeout=1000)
                btn.click(timeout=1000)
                page.wait_for_timeout(800)
                return
        except Exception:
            continue


def coletar_atributos_temu(page: Page) -> dict[str, str]:
    script = r"""
    () => {
      const saida = {};
      const limpar = (v) => (v || '').replace(/\s+/g, ' ').trim();
      
      const elementos = document.querySelectorAll('.product-spec-item, li, tr');
      for (const el of elementos) {
        const partes = el.innerText.split(':');
        if (partes.length >= 2) {
            const chave = limpar(partes[0]);
            const valor = limpar(partes.slice(1).join(':'));
            if (chave && valor) {
                saida[chave] = valor;
            }
        }
      }
      return saida;
    }
    """
    try:
        pares = page.evaluate(script) or {}
    except Exception:
        pares = {}

    atributos = {}
    for chave, valor in pares.items():
        chave_norm = normalizar_chave(chave)
        if chave_norm and valor:
            atributos[chave_norm] = valor
    return atributos


def extrair_produto_temu(page: Page) -> dict[str, Any] | None:
    fechar_modais_iniciais(page)
    
    texto_pagina = ""
    try:
        texto_pagina = page.locator("body").inner_text(timeout=4000)
    except Exception:
        pass

    # Se o item estiver esgotado, a Temu exibe essa mensagem na página
    if "está esgotado" in texto_pagina or "is sold out" in texto_pagina:
        return None

    expandir_especificacoes(page)
    atributos = coletar_atributos_temu(page)
    
    titulo = ""
    try:
        titulo = page.locator("h1").first.inner_text(timeout=2000).strip()
    except Exception:
        pass

    preco = ""
    try:
        preco = page.locator("[class*='price']").first.inner_text(timeout=2000).strip()
    except Exception:
        pass

    marca = atributos.get("brand", atributos.get("marca", ""))
    modelo = atributos.get("model", atributos.get("modelo", ""))
    
    codigo_anatel = "" 

    return {
        "url": page.url,
        "titulo": titulo,
        "preco": preco,
        "marca": marca,
        "fabricante": marca,
        "modelo": modelo,
        "modelo_detalhado": "",
        "modelo_alfanumerico": "",
        "numero_modelo": modelo,
        "codigo_anatel_principal": codigo_anatel,
        "descricao": texto_pagina[:1000], 
        "texto_pagina": texto_pagina,
        "atributos": atributos,
        "comentarios": [] 
    }