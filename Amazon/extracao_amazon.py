from __future__ import annotations

import json
import re
import unicodedata
from typing import Any
from urllib.parse import urljoin
from playwright.sync_api import Page

# Importa o padronizador e classificador do nosso módulo central
from core.base_anatel import normalize_item

# ============================================================
# UTILS (Trazidos para cá para manter o arquivo independente)
# ============================================================
def remover_acentos(txt: str) -> str:
    if not txt: return ""
    return unicodedata.normalize('NFKD', txt).encode('ASCII', 'ignore').decode('ASCII')

def normalizar_texto(txt: str) -> str:
    if not txt: return ""
    return re.sub(r'\s+', ' ', str(txt)).strip()

def normalizar_chave(txt: str) -> str:
    return remover_acentos(normalizar_texto(txt)).lower()

# ============================================================
# MODAIS / HELPERS GERAIS DA AMAZON
# ============================================================
def _texto_primeiro(page: Page, seletores: list[str], timeout_ms: int = 1800) -> str:
    for seletor in seletores:
        try:
            loc = page.locator(seletor).first
            if loc.count() and loc.is_visible(timeout=timeout_ms):
                txt = normalizar_texto(loc.inner_text(timeout=timeout_ms))
                if txt: return txt
        except Exception: continue
    return ""

def _href_primeiro(page: Page, seletores: list[str], timeout_ms: int = 1200) -> str:
    for seletor in seletores:
        try:
            loc = page.locator(seletor).first
            if loc.count():
                href = (loc.get_attribute("href", timeout=timeout_ms) or "").strip()
                if href: return urljoin(page.url, href)
        except Exception: continue
    return ""

def _click_suave(page: Page, textos: list[str], timeout_ms: int = 1200) -> bool:
    for texto in textos:
        seletores = [
            f"button:has-text('{texto}')", f"a:has-text('{texto}')",
            f"span:has-text('{texto}')", f"input[value*='{texto}']"
        ]
        for seletor in seletores:
            try:
                loc = page.locator(seletor).first
                if loc.count() and loc.is_visible(timeout=500):
                    loc.scroll_into_view_if_needed(timeout=timeout_ms)
                    page.wait_for_timeout(250)
                    loc.click(timeout=timeout_ms)
                    page.wait_for_timeout(700)
                    return True
            except Exception: continue
    return False

def fechar_modais_amazon(page: Page) -> None:
    textos = ["Aceitar cookies", "Aceitar todos", "Continuar comprando", "Continuar", "Agora não", "Agora nao", "Mais tarde", "Fechar"]
    _click_suave(page, textos, timeout_ms=1000)

# ============================================================
# EXTRAÇÃO DE ATRIBUTOS E TABELAS
# ============================================================
def preparar_detalhes_produto_amazon(page: Page) -> bool:
    seletores_evidencia = [
        "#prodDetails", "#detailBullets_feature_div", "#detailBulletsWrapper_feature_div",
        "table:has-text('ASIN')", "table:has-text('Fabricante')", "table:has-text('Marca')"
    ]
    
    # Rola e abre acordeões
    textos_acordeao = ["Medidas", "Detalhes do Produto", "Detalhes Adicionais", "Informações do produto"]
    for texto in textos_acordeao:
        _click_suave(page, [texto], timeout_ms=800)

    for seletor in seletores_evidencia:
        try:
            if page.locator(seletor).first.count(): return True
        except Exception: pass
    return False

def _coletar_atributos_amazon(page: Page) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    # Seu script JS brutal para varrer tabelas
    script = r"""
    () => {
      const out = []; const seen = new Set();
      function clean(s) { return (s || '').replace(/\s+/g, ' ').replace(/^[:\-\s]+|[:\-\s]+$/g, '').trim(); }
      function push(label, value) {
        label = clean(label); value = clean(value);
        if (!label || !value || label === value) return;
        const key = `${label}=>${value}`;
        if (!seen.has(key)) { seen.add(key); out.push({label, value}); }
      }
      for (const tr of document.querySelectorAll('table tr')) {
        const cells = Array.from(tr.children).map(c => clean(c.innerText || c.textContent));
        if (cells.length >= 2) push(cells[0], cells.slice(1).join(' '));
      }
      for (const li of document.querySelectorAll('#detailBullets_feature_div li')) {
        const full = clean(li.innerText || li.textContent);
        if (full && full.includes(':')) {
          const idx = full.indexOf(':'); push(full.slice(0, idx), full.slice(idx + 1));
        }
      }
      return out;
    }
    """
    try: pares = page.evaluate(script) or []
    except Exception: pares = []

    attrs = {}
    evidencias = {}
    for item in pares:
        label = normalizar_texto(item.get("label"))
        value = normalizar_texto(item.get("value"))
        if label and value:
            chave = normalizar_chave(label)
            attrs[chave] = value
            evidencias[chave] = {"label": label, "value": value}
    return attrs, evidencias

def _valor_por_labels(attrs: dict[str, str], labels: list[str]) -> str:
    labels_norm = [normalizar_chave(x) for x in labels]
    for chave, valor in attrs.items():
        for label in labels_norm:
            if chave == label or chave.endswith(label) or label in chave:
                return normalizar_texto(valor)
    return ""

# ============================================================
# COMPONENTES DO PRODUTO (Preço, Nome, Anatel)
# ============================================================
def extrair_nome_amazon(page: Page) -> str:
    return _texto_primeiro(page, ["#productTitle", "h1#title", "h1"]) or normalizar_texto(page.title())

def extrair_preco_amazon(page: Page) -> str:
    preco = _texto_primeiro(page, [
        "#corePriceDisplay_desktop_feature_div .a-price .a-offscreen",
        "#corePrice_feature_div .a-price .a-offscreen",
        ".priceToPay .a-offscreen"
    ])
    if preco: return preco
    
    try:
        inteiro = normalizar_texto(page.locator(".a-price-whole").first.inner_text(timeout=1000))
        decimal = normalizar_texto(page.locator(".a-price-fraction").first.inner_text(timeout=500))
        if inteiro: return f"R$ {inteiro},{decimal or '00'}"
    except Exception: pass
    return "0.0"

def extrair_codigo_anatel_amazon(page: Page, attrs: dict[str, str]) -> str:
    # 1. Tenta pelas tabelas de atributos
    labels = ["Anatel", "Código Anatel", "Homologação Anatel", "Número de homologação"]
    valor = _valor_por_labels(attrs, labels)
    if valor:
        numeros = re.sub(r"\D", "", valor)
        if len(numeros) >= 8: return numeros

    # 2. Tenta caçando direto no DOM
    html_limpo = page.evaluate(r"() => document.body ? document.body.innerText.replace(/\s+/g, ' ').trim() : ''") or ""
    for match in re.finditer(r"(?i)(?:anatel|homologacao)[^0-9]{0,50}((?:\d[\s.\-/]*){8,14})", html_limpo):
        numero = re.sub(r"\D", "", match.group(1))
        if len(numero) >= 8: return numero
    return ""

def extrair_marca_modelo(attrs: dict[str, str]) -> tuple[str, str]:
    marca = _valor_por_labels(attrs, ["Marca", "Brand", "Fabricante"])
    modelo = _valor_por_labels(attrs, ["Número do modelo", "Nome do modelo", "Model Name", "Modelo"])
    return marca, modelo

# ============================================================
# ORQUESTRADOR PRINCIPAL
# ============================================================
def extrair_dados_amazon(page: Page, query: str) -> dict:
    """
    Função principal que navega na página de detalhes de um produto Amazon,
    extrai todos os atributos via JS e envia para o validador central (core).
    """
    fechar_modais_amazon(page)
    try: page.wait_for_load_state("domcontentloaded", timeout=15000)
    except Exception: pass

    # 1. Extração bruta usando as lógicas robustas da Amazon
    preparar_detalhes_produto_amazon(page)
    attrs, _ = _coletar_atributos_amazon(page)
    
    nome = extrair_nome_amazon(page)
    preco = extrair_preco_amazon(page)
    codigo_anatel = extrair_codigo_anatel_amazon(page, attrs)
    marca, modelo = extrair_marca_modelo(attrs)

    # 2. Concatena os atributos extraídos para que o validador consiga ler as dimensões
    desc_parts = [f"{k}: {v}" for k, v in attrs.items()]
    description = " | ".join(desc_parts)

    # 3. Monta o Dicionário Cru
    item_cru = {
        "marketplace": "Amazon",
        "query": query,
        "title": nome,
        "price": preco,
        "seller": marca,
        "model": modelo,
        "url": page.url,
        "anatel_code": codigo_anatel,
        "description": description
    }

    # 4. Passa pelo "Funil" do Core (que vai checar medidas, doces, brinquedos e validação final da base)
    return normalize_item(item_cru)