# -*- coding: utf-8 -*-
from __future__ import annotations
import re
import unicodedata
from typing import Any, Dict, List
from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

try:
    from base_anatel import normalizar_codigo_anatel
except ImportError:
    def normalizar_codigo_anatel(valor: Any) -> str:
        texto = str(valor or "").strip()
        digitos = re.sub(r"\D", "", texto)
        if not digitos:
            return ""
        return digitos.zfill(12) if len(digitos) < 12 else digitos[-12:]

def normalizar_texto(valor: Any) -> str:
    if valor is None:
        return ""
    texto = str(valor).replace("\xa0", " ").strip().lower()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(
        caractere
        for caractere in texto
        if not unicodedata.combining(caractere)
    )
    return re.sub(r"\s+", " ", texto).strip()

def normalizar_chave(valor: Any) -> str:
    return re.sub(
        r"[^a-z0-9]+",
        "",
        normalizar_texto(valor),
    )

async def esperar_carregamento(page: Page, timeout_ms: int = 30000) -> None:
    try: 
        await page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
    except PlaywrightTimeoutError: 
        pass
    
    try:
        await page.wait_for_load_state("networkidle", timeout=6000)
    except Exception:
        pass
    
    try:
        await page.wait_for_timeout(2000)
    except Exception:
        pass

async def fechar_popups_basicos(page: Page) -> None:
    textos = ["Aceitar", "Entendi", "Continuar", "Fechar", "OK"]
    for texto in textos:
        try:
            loc = page.get_by_text(texto, exact=False).first
            if await loc.count(): await loc.click(timeout=900)
        except Exception: pass

async def _expandir_informacoes(page: Page) -> None:
    textos_alvo = ["Informações do Produto", "Ficha Técnica", "Características", "Descrição"]
    for texto in textos_alvo:
        try:
            locators = page.locator(f"text='{texto}'")
            total = await locators.count()
            for i in range(total):
                loc = locators.nth(i)
                if await loc.is_visible():
                    await loc.click(timeout=1000)
                    await page.wait_for_timeout(400)
        except Exception:
            pass

async def coletar_links_resultados(page: Page) -> List[Dict[str, Any]]:
    try:
        for _ in range(5):
            await page.mouse.wheel(0, 900)
            await page.wait_for_timeout(600)
        await page.mouse.wheel(0, -1000)
        await page.wait_for_timeout(1000)
    except Exception: 
        pass

    itens = []
    vistos = set()
    try:
        dados = await page.evaluate(r'''() => {
            const results = [];
            document.querySelectorAll('a[href]').forEach(a => {
                const href = a.href || '';
                if (href.length > 10 && !href.includes('/busca') && !href.includes('/categoria') && !href.includes('login')) {
                    if (href.includes('/p') || href.includes('/produto/') || /-\d{6,}/.test(href)) {
                        results.push(href);
                    }
                }
            });
            return results;
        }''')
        
        for href in dados:
            if href not in vistos:
                vistos.add(href)
                itens.append({"url": href})
    except Exception: 
        pass
        
    return itens

async def coletar_atributos(page: Page) -> dict[str, str]:
    script = r"""
    () => {
      const saida = [];
      const vistos = new Set();
      const limpar = (valor) => (valor || '').replace(/\s+/g, ' ').trim();

      const adicionar = (rotulo, valor) => {
        rotulo = limpar(rotulo);
        valor = limpar(valor);
        if (!rotulo || !valor || rotulo === valor) return;
        const chave = `${rotulo}=>${valor}`;
        if (vistos.has(chave)) return;
        vistos.add(chave);
        saida.push([rotulo, valor]);
      };

      for (const linha of document.querySelectorAll('tr')) {
        const celulas = Array.from(linha.children)
          .map((item) => limpar(item.innerText || item.textContent));
        if (celulas.length >= 2) {
          adicionar(celulas[0], celulas.slice(1).join(' '));
        }
      }

      for (const elemento of document.querySelectorAll('div, li, span')) {
        const filhos = Array.from(elemento.children)
          .map((item) => limpar(item.innerText || item.textContent))
          .filter(Boolean);
        if (filhos.length === 2 && filhos[0].length <= 90 && filhos[1].length <= 260) {
          adicionar(filhos[0], filhos[1]);
        }
      }
      return saida.slice(0, 400);
    }
    """
    try:
        pares = await page.evaluate(script) or []
    except Exception:
        pares = []

    atributos: dict[str, str] = {}
    for rotulo, valor in pares:
        chave = str(rotulo or "").strip()
        conteudo = str(valor or "").strip()
        if not chave or not conteudo:
            continue
        chave_norm = normalizar_chave(chave)
        if chave_norm not in atributos or len(conteudo) < len(atributos[chave_norm]):
            atributos[chave_norm] = conteudo
    return atributos

def _valor_por_rotulos(atributos: dict[str, str], rotulos: list[str]) -> str:
    rotulos_norm = [normalizar_chave(item) for item in rotulos]
    for chave, valor in atributos.items():
        if any(rotulo in chave for rotulo in rotulos_norm):
            return str(valor or "").strip()
    return ""

def extrair_codigo_anatel_attr(atributos: dict[str, str], texto_pagina: str) -> str:
    for chave, valor in atributos.items():
        if "anatel" in chave or "homologacao" in chave or "homologação" in chave:
            codigo = normalizar_codigo_anatel(valor)
            if len(codigo) >= 8:
                return codigo
                
    padroes = [
        r"(?:anatel|homologa(?:cao|ção)|certifica(?:cao|ção))[^0-9]{0,60}((?:\d[\s./-]*){8,14})",
        r"((?:\d[\s./-]*){8,14})[^a-z0-9]{0,40}(?:anatel|homologa(?:cao|ção))",
    ]
    for padrao in padroes:
        for match in re.finditer(padrao, normalizar_texto(texto_pagina), flags=re.IGNORECASE):
            codigo = normalizar_codigo_anatel(match.group(1))
            if len(codigo) >= 8:
                return codigo
    return ""

async def capturar_comentarios(page: Page, limite: int = 10) -> List[str]:
    comentarios = []
    seletores = [".ui-review-capability-comments__comment__content", "[class*='review-text']", ".avaliacao-texto"]
    for sel in seletores:
        try:
            locs = page.locator(sel)
            total = await locs.count()
            for i in range(min(total, limite)):
                txt = await locs.nth(i).inner_text(timeout=1000)
                if len(txt) > 10: comentarios.append(txt.strip())
            if comentarios: break
        except Exception: continue
    return comentarios

async def extrair_produto(page: Page, url_produto: str, card: Dict[str, Any]) -> Dict[str, Any]:
    await esperar_carregamento(page)
    
    try:
        for _ in range(3):
            await page.mouse.wheel(0, 1000)
            await page.wait_for_timeout(800)
        await page.mouse.wheel(0, -600)
    except Exception:
        pass

    await _expandir_informacoes(page)

    titulo = ""
    try: titulo = await page.title()
    except Exception: pass

    body_txt = ""
    try: body_txt = await page.locator("body").inner_text(timeout=3000)
    except Exception: pass

    atributos = await coletar_atributos(page)
    codigo_anatel = extrair_codigo_anatel_attr(atributos, body_txt)

    marca = _valor_por_rotulos(atributos, ["marca", "fabricante"])
    modelo = _valor_por_rotulos(atributos, ["modelo", "modelo detalhado", "numero do modelo"])
    nome_comercial = _valor_por_rotulos(atributos, ["nome comercial", "linha", "familia", "nome do produto"])

    # Extração de Dimensões
    altura_mm, largura_mm, maior_dim = None, None, None
    dim_str = _valor_por_rotulos(atributos, ["altura", "height", "dimensoes", "dimensões", "medidas", "tamanho"])
    if not dim_str:
        dim_str = body_txt

    m_dim = re.search(r"(?:altura|height)?\s*[:]?\s*(\d{1,3}(?:[.,]\d{1,2})?)\s*(cm|mm)", dim_str, re.IGNORECASE)
    if m_dim:
        val = float(m_dim.group(1).replace(",", "."))
        altura_mm = val * 10 if "cm" in m_dim.group(2).lower() else val
        maior_dim = altura_mm

    m_lar = re.search(r"(?:largura|width)?\s*[:]?\s*(\d{1,3}(?:[.,]\d{1,2})?)\s*(cm|mm)", dim_str, re.IGNORECASE)
    if m_lar:
        val = float(m_lar.group(1).replace(",", "."))
        largura_mm = val * 10 if "cm" in m_lar.group(2).lower() else val

    # Fallback por multiplicação caso não ache separado (ex: 131.5 x 64.2 mm)
    if not altura_mm or not largura_mm:
        m_mult = re.search(r"(\d{2,3}(?:[.,]\d{1,2})?)\s*[xX×]\s*(\d{2,3}(?:[.,]\d{1,2})?)(?:\s*[xX×]\s*\d{2,3}(?:[.,]\d{1,2})?)?\s*(mm|cm)?", dim_str, re.IGNORECASE)
        if m_mult:
            v1 = float(m_mult.group(1).replace(",", "."))
            v2 = float(m_mult.group(2).replace(",", "."))
            unidade = (m_mult.group(3) or "mm").lower()
            fator = 10.0 if "cm" in unidade else 1.0
            vals = sorted([v1 * fator, v2 * fator], reverse=True)
            altura_mm, largura_mm = vals[0], vals[1]
            maior_dim = altura_mm

    comentarios = await capturar_comentarios(page)

    return {
        "titulo": titulo, "url": url_produto, "texto_pagina": body_txt,
        "codigo_anatel": codigo_anatel, "marca": marca, "fabricante": marca, "modelo": modelo,
        "nome_comercial": nome_comercial,
        "altura_mm": altura_mm, "largura_mm": largura_mm,
        "maior_dimensao_mm": maior_dim, "comentarios": comentarios, "atributos": atributos
    }