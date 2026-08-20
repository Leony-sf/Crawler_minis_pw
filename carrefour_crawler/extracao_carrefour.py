from __future__ import annotations

import json
import re
from typing import Any, Dict, List
from urllib.parse import unquote, urljoin, urlparse
from dataclasses import dataclass

from playwright.async_api import Page, TimeoutError as PlaywrightTimeoutError

from base_anatel import normalizar_codigo_anatel
from utils_carrefour import normalizar_texto, remover_acentos

BASE_URL = "https://www.carrefour.com.br"
TERMOS_RELEVANTES_BUSCA = ["celular", "smartphone", "telefone", "phone", "mobile", "dual chip", "dual sim", "mini celular", "l8star", "bm70"]
TERMOS_DESCARTE_OBVIO_BUSCA = ["chocolate", "amendoim", "amêndoa", "biscoito", "leite", "café", "arroz", "ração", "shampoo", "capinha", "pelicula"]

@dataclass
class DadosProduto:
    url: str
    titulo: str
    preco: str
    codigo_anatel_principal: str
    codigo_anatel_normalizado: str
    marca: str
    fabricante: str
    modelo: str
    modelo_alfanumerico: str
    atributos_json: str
    comentarios: list[str]
    
    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

def limpar_texto(txt: str | None) -> str:
    txt = txt or ""
    return re.sub(r"\s+", " ", txt.replace("\xa0", " ").replace("\u200b", " ")).strip()

def normalizar_url(url: str) -> str:
    url = (url or "").strip().strip('"').strip("'").replace("\\/", "/").split("#")[0]
    if url.startswith("//"): url = "https:" + url
    return urljoin(BASE_URL, url)

def url_produto_valida(url: str) -> bool:
    if not url: return False
    path = urlparse(normalizar_url(url)).path.lower().rstrip("/")
    if "/produto/" in path or path.endswith("/p") or "/p/" in path or re.search(r"/[^/]+-\d{5,}/p$", path): return True
    return False

async def esperar_carregamento(page: Page, timeout_ms: int = 30000) -> None:
    try: await page.wait_for_load_state("domcontentloaded", timeout=timeout_ms)
    except PlaywrightTimeoutError: pass
    try: await page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 12000))
    except Exception: pass
    try: await page.wait_for_timeout(2200)
    except Exception: pass

async def fechar_popups_basicos(page: Page) -> None:
    textos_cookies = ["Aceitar cookies", "Aceitar todos", "Aceitar", "Concordo", "Entendi", "OK", "Ok"]
    for texto in textos_cookies:
        try:
            botao = page.get_by_text(texto, exact=False).first
            if await botao.count():
                await botao.click(timeout=900)
                await page.wait_for_timeout(350)
                return
        except Exception: pass

async def rolar_busca(page: Page) -> None:
    try:
        await page.wait_for_timeout(900)
        for _ in range(7):
            await page.mouse.wheel(0, 1200)
            await page.wait_for_timeout(650)
    except Exception: pass

async def coletar_links_resultados(page: Page, vistos_globais: set[str]) -> List[str]:
    await rolar_busca(page)
    try: await page.locator("a[href*='/produto/'], a[href*='/p/']").first.wait_for(timeout=3500)
    except Exception: pass

    script = """
    () => {
        const out = new Set();
        const anchors = Array.from(document.querySelectorAll('a[href]'));
        for (const a of anchors) {
            const href = a.href || '';
            if (href.includes('/produto/') || href.includes('/p/') || href.endsWith('/p')) {
                out.add(href);
            }
        }
        return Array.from(out);
    }
    """
    try: links = await page.evaluate(script) or []
    except Exception: links = []

    validos = []
    for href in links:
        url = normalizar_url(href)
        if url_produto_valida(url) and url not in vistos_globais:
            validos.append(url)
            vistos_globais.add(url)
    return validos

async def extrair_json_ld(page: Page) -> Dict[str, Any]:
    dados = {}
    try:
        scripts = await page.locator("script[type='application/ld+json']").all()
        for script in scripts:
            raw = await script.text_content(timeout=700)
            if not raw: continue
            obj = json.loads(raw)
            objs = obj if isinstance(obj, list) else [obj]
            for item in objs:
                if isinstance(item, dict) and ("product" in str(item.get("@type", "")).lower() or item.get("name")):
                    if item.get("name"): dados["name"] = limpar_texto(str(item.get("name")))
                    if item.get("brand") and isinstance(item.get("brand"), dict): dados["brand"] = limpar_texto(item["brand"].get("name", ""))
                    offers = item.get("offers")
                    if isinstance(offers, dict) and (offers.get("price") or offers.get("lowPrice")):
                        dados["price"] = str(offers.get("price") or offers.get("lowPrice"))
    except Exception: pass
    return dados

async def extrair_blocos_informacao(page: Page) -> str:
    seletores = ["section", "article", "table", "dl", "ul", "[data-testid*='spec']", "[data-testid*='description']"]
    blocos = []
    for seletor in seletores:
        try:
            loc = page.locator(seletor)
            total = await loc.count()
            for indice in range(min(total, 60)):
                texto = limpar_texto(await loc.nth(indice).inner_text(timeout=700))
                if len(texto) > 30 and any(t in texto.lower() for t in ["dimens", "altura", "largura", "comprimento", "tela", "chip", "sim", "anatel", "modelo", "marca"]):
                    blocos.append(texto[:3000])
        except Exception: continue
    return " | ".join(dict.fromkeys(blocos))[:12000]

async def extrair_produto_carrefour(page: Page) -> DadosProduto:
    await esperar_carregamento(page)
    await fechar_popups_basicos(page)

    jsonld = await extrair_json_ld(page)
    
    try: titulo = limpar_texto(await page.locator("h1, [data-testid='product-title']").first.inner_text(timeout=2000))
    except Exception: titulo = jsonld.get("name", "")

    try: preco = limpar_texto(await page.locator("[data-testid='price-value'], [class*='price']").first.inner_text(timeout=1500))
    except Exception: preco = f"R$ {jsonld.get('price', '')}"

    detalhes = await extrair_blocos_informacao(page)
    texto_completo = f"{titulo} | {detalhes}"

    marca = jsonld.get("brand", "")
    if not marca:
        m = re.search(r"(?i)\b(?:marca|fabricante)\s*[:\-]\s*([a-zA-Z0-9\s]{2,20})", detalhes)
        if m: marca = m.group(1).strip()

    modelo = ""
    m_modelo = re.search(r"(?i)\bmodelo\s*[:\-]\s*([a-zA-Z0-9\-\s]{2,30})", detalhes)
    if m_modelo: modelo = m_modelo.group(1).strip()

    codigo_anatel = ""
    for padrao in [r"(?i)anatel[^\d]{0,45}(\d{8,14})", r"\b(\d{5}[-\s]?\d{2}[-\s]?\d{4})\b"]:
        m_anatel = re.search(padrao, texto_completo)
        if m_anatel:
            cand = re.sub(r"\D", "", m_anatel.group(1))
            if 8 <= len(cand) <= 14:
                codigo_anatel = cand
                break

    return DadosProduto(
        url=page.url,
        titulo=titulo,
        preco=preco,
        codigo_anatel_principal=codigo_anatel,
        codigo_anatel_normalizado=normalizar_codigo_anatel(codigo_anatel),
        marca=normalizar_texto(marca),
        fabricante=normalizar_texto(marca),
        modelo=normalizar_texto(modelo),
        modelo_alfanumerico=normalizar_texto(modelo),
        atributos_json=json.dumps({"detalhes_brutos": detalhes}, ensure_ascii=False),
        comentarios=[]
    )

def _parse_medida_cm(valor: str, unidade: str) -> float:
    try:
        num = float(valor.replace(",", "."))
        return num / 10.0 if "mm" in unidade.lower() or "milimetro" in unidade.lower() else num
    except Exception: return 0.0

def analisar_mini_celular_carrefour(dados: DadosProduto, maior_max_cm: float = 12.0, largura_max_cm: float = 5.5) -> dict[str, Any]:
    try: pacote = json.loads(dados.atributos_json)
    except Exception: pacote = {}
    
    texto = normalizar_texto(pacote.get("detalhes_brutos", "")).lower()
    padrao_mult = re.compile(r"(\d+(?:[\.,]\d+)?)\s*(cm|mm)?\s*(?:x|X|×)\s*(\d+(?:[\.,]\d+)?)\s*(cm|mm)?(?:.*?(\d+(?:[\.,]\d+)?)\s*(cm|mm)?)?")
    candidatos = []
    
    for m in padrao_mult.finditer(texto):
        uns = [m.group(2), m.group(4), m.group(6)]
        upadrao = next((u for u in reversed(uns) if u), "cm")
        vals = []
        for i, idx in enumerate([1, 3, 5]):
            if m.group(idx): vals.append(_parse_medida_cm(m.group(idx), uns[i] or upadrao))
        if len(vals) >= 2 and all(v < 40 for v in vals):
            vals = sorted(vals, reverse=True)
            candidatos.append((vals[0], vals[1], vals[2] if len(vals) >= 3 else None, m.group(0)))

    if not candidatos:
        return {
            "dimensoes_encontradas": "NAO",
            "dimensoes_confiaveis": "NAO",
            "dentro_limite_dimensional": "NAO_VERIFICADO",
            "origem_dimensoes": "",
        }

    maior_cm, largura_cm, espessura_cm, ev = candidatos[0]
    dentro = maior_cm <= maior_max_cm and largura_cm <= largura_max_cm

    return {
        "dimensoes_encontradas": "SIM",
        "dimensoes_confiaveis": "SIM",
        "dentro_limite_dimensional": "SIM" if dentro else "NAO",
        "altura_cm": maior_cm,
        "largura_cm": largura_cm,
        "espessura_cm": espessura_cm,
        "origem_dimensoes": ev,
    }