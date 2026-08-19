from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urljoin

from playwright.sync_api import Page

from .base_anatel import normalizar_codigo_anatel
from .extracao import DadosProduto
from .utils import normalizar_chave, normalizar_texto, remover_acentos


# ============================================================
# MODAIS / HELPERS GERAIS
# ============================================================

def _texto_primeiro(page: Page, seletores: list[str], timeout_ms: int = 1800) -> str:
    for seletor in seletores:
        try:
            loc = page.locator(seletor).first
            if loc.count() and loc.is_visible(timeout=timeout_ms):
                txt = normalizar_texto(loc.inner_text(timeout=timeout_ms))
                if txt:
                    return txt
        except Exception:
            continue
    return ""


def _href_primeiro(page: Page, seletores: list[str], timeout_ms: int = 1200) -> str:
    for seletor in seletores:
        try:
            loc = page.locator(seletor).first
            if loc.count():
                href = (loc.get_attribute("href", timeout=timeout_ms) or "").strip()
                if href:
                    return urljoin(page.url, href)
        except Exception:
            continue
    return ""


def _click_suave(page: Page, textos: list[str], timeout_ms: int = 1200) -> bool:
    for texto in textos:
        seletores = [
            f"button:has-text('{texto}')",
            f"a:has-text('{texto}')",
            f"span:has-text('{texto}')",
            f"input[value*='{texto}']",
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
            except Exception:
                continue
    return False


def fechar_modais_amazon(page: Page) -> None:
    textos = [
        "Aceitar cookies", "Aceitar todos", "Continuar comprando", 
        "Continuar", "Agora não", "Agora nao", "Mais tarde", "Fechar",
    ]
    _click_suave(page, textos, timeout_ms=1000)


# ============================================================
# ATRIBUTOS / TABELAS DA AMAZON
# ============================================================

def preparar_detalhes_produto_amazon(page: Page) -> bool:
    seletores_evidencia = [
        "#prodDetails", "#detailBullets_feature_div", "#detailBulletsWrapper_feature_div",
        "#productDetails_techSpec_section_1", "#productDetails_detailBullets_sections1",
        "#productFactsDesktop_feature_div", "#productOverview_feature_div",
        "table:has-text('ASIN')", "table:has-text('Fabricante')", "table:has-text('Marca')",
        "table:has-text('Número do modelo')", "table:has-text('Numero do modelo')",
        "table:has-text('Certificação de teste externa')", "table:has-text('Certificacao de teste externa')",
        "text=Especificações do produto", "text=Especificacoes do produto",
        "text=Detalhes do Produto", "text=Detalhes do produto",
        "text=Detalhes Adicionais", "text=Detalhes adicionais",
    ]

    def existe_evidencia() -> bool:
        for seletor in seletores_evidencia:
            try:
                loc = page.locator(seletor).first
                if loc.count() and loc.is_visible(timeout=700):
                    return True
            except Exception:
                continue
        return False

    if existe_evidencia():
        return True

    try:
        for alvo in ["Informações do produto", "Informacoes do produto", "Especificações do produto", "Especificacoes do produto"]:
            try:
                loc = page.get_by_text(alvo, exact=False).first
                if loc.count():
                    loc.scroll_into_view_if_needed(timeout=2500)
                    page.wait_for_timeout(800)
                    break
            except Exception:
                continue
    except Exception:
        pass

    textos_acordeao = [
        "Detalhes do Produto", "Detalhes do produto", "Detalhes Adicionais", 
        "Detalhes adicionais", "Informações do produto", "Informacoes do produto",
    ]
    for texto in textos_acordeao:
        seletores = [
            f"button:has-text('{texto}')", f"[role='button']:has-text('{texto}')",
            f"h2:has-text('{texto}')", f"span:has-text('{texto}')", f"div:has-text('{texto}')",
        ]
        for seletor in seletores:
            try:
                loc = page.locator(seletor).first
                if loc.count() and loc.is_visible(timeout=700):
                    loc.scroll_into_view_if_needed(timeout=2500)
                    page.wait_for_timeout(300)
                    try: loc.click(timeout=1200)
                    except Exception: pass
                    page.wait_for_timeout(700)
                    if existe_evidencia():
                        return True
            except Exception:
                continue

    if existe_evidencia():
        return True

    try:
        texto = normalizar_texto(page.locator("body").inner_text(timeout=2500))
        termos_fortes = [
            "Especificações do produto", "Especificacoes do produto", "Detalhes do Produto",
            "Detalhes do produto", "Certificação de teste externa", "Certificacao de teste externa",
            "Número do modelo", "Numero do modelo", "ASIN",
        ]
        return any(t.lower() in texto.lower() for t in termos_fortes)
    except Exception:
        return False


def _coletar_atributos_amazon(page: Page) -> tuple[dict[str, str], dict[str, dict[str, Any]]]:
    script = r"""
    () => {
      const out = [];
      const seen = new Set();
      function clean(s) { return (s || '').replace(/\s+/g, ' ').replace(/^[:\-\s]+|[:\-\s]+$/g, '').trim(); }
      function push(label, value, source, confidence) {
        label = clean(label); value = clean(value);
        if (!label || !value || label === value) return;
        if (label.length > 120 || value.length > 600) return;
        const key = `${label}=>${value}=>${source}`;
        if (seen.has(key)) return;
        seen.add(key);
        out.push({label, value, source, confidence});
      }

      for (const tr of document.querySelectorAll('table tr')) {
        const cells = Array.from(tr.children).map(c => clean(c.innerText || c.textContent));
        if (cells.length >= 2) push(cells[0], cells.slice(1).join(' '), 'table/tr', 'alta');
      }

      for (const tr of document.querySelectorAll('#productOverview_feature_div tr, div.a-section table tr')) {
        const cells = Array.from(tr.querySelectorAll('td, th, span')).map(c => clean(c.innerText || c.textContent)).filter(Boolean);
        if (cells.length >= 2) push(cells[0], cells.slice(1).join(' '), 'productOverview', 'alta');
      }

      for (const li of document.querySelectorAll('#detailBullets_feature_div li, #detailBulletsWrapper_feature_div li, ul.detail-bullet-list li')) {
        const full = clean(li.innerText || li.textContent);
        if (!full) continue;
        const bold = li.querySelector('.a-text-bold, b, strong');
        if (bold) {
          const label = clean(bold.innerText || bold.textContent).replace(/:$/, '');
          let value = clean(full.replace(bold.innerText || bold.textContent, ''));
          value = value.replace(/^[:\-\s]+/, '');
          push(label, value, 'detailBullets', 'alta');
        } else if (full.includes(':')) {
          const idx = full.indexOf(':');
          push(full.slice(0, idx), full.slice(idx + 1), 'detailBullets', 'media');
        }
      }

      for (const row of document.querySelectorAll('#prodDetails div, #detailBullets_feature_div div, #productFactsDesktop_feature_div div')) {
        const children = Array.from(row.children).map(c => clean(c.innerText || c.textContent)).filter(Boolean);
        if (children.length === 2) push(children[0], children[1], 'visual-row', 'media');
      }

      return out.slice(0, 500);
    }
    """
    try: pares = page.evaluate(script) or []
    except Exception: pares = []

    attrs: dict[str, str] = {}
    evidencias: dict[str, dict[str, Any]] = {}
    prioridade = {"alta": 3, "media": 2, "baixa": 1}

    for item in pares:
        label = normalizar_texto(item.get("label"))
        value = normalizar_texto(item.get("value"))
        if not label or not value: continue

        chave = normalizar_chave(label)
        conf = str(item.get("confidence") or "media").lower()
        atual = evidencias.get(chave, {})
        deve_trocar = False

        if chave not in attrs: deve_trocar = True
        elif prioridade.get(conf, 0) > prioridade.get(str(atual.get("confidence") or ""), 0): deve_trocar = True
        elif len(value) < len(attrs.get(chave, "")) and prioridade.get(conf, 0) == prioridade.get(str(atual.get("confidence") or ""), 0): deve_trocar = True

        if deve_trocar:
            attrs[chave] = value
            evidencias[chave] = {"label": label, "value": value, "source": item.get("source") or "", "confidence": conf}

    return attrs, evidencias


def _valor_por_labels(attrs: dict[str, str], labels: list[str], excluir: list[str] | None = None) -> str:
    labels_norm = [normalizar_chave(x) for x in labels]
    excluir_norm = [normalizar_chave(x) for x in (excluir or [])]
    for chave, valor in attrs.items():
        if any(ex in chave for ex in excluir_norm): continue
        for label in labels_norm:
            if chave == label or chave.endswith(label) or label in chave:
                return normalizar_texto(valor)
    return ""


# ============================================================
# NOME / PREÇO / MARCA / MODELO
# ============================================================

def extrair_nome_amazon(page: Page) -> tuple[str, dict[str, str]]:
    candidatos = [("#productTitle", "#productTitle", "alta"), ("h1#title", "h1#title", "media"), ("h1", "h1", "baixa")]
    for seletor, fonte, conf in candidatos:
        try:
            loc = page.locator(seletor).first
            if loc.count() and loc.is_visible(timeout=2000):
                txt = normalizar_texto(loc.inner_text(timeout=2500))
                if txt: return txt, {"source": fonte, "confidence": conf}
        except Exception: continue
    try: return normalizar_texto(page.title()), {"source": "document.title", "confidence": "baixa"}
    except Exception: return "", {"source": "", "confidence": ""}


def extrair_preco_amazon(page: Page) -> tuple[str, dict[str, str]]:
    seletores = [
        ("#corePriceDisplay_desktop_feature_div .a-price .a-offscreen", "corePriceDisplay", "alta"),
        ("#corePrice_feature_div .a-price .a-offscreen", "corePrice", "alta"),
        (".priceToPay .a-offscreen", "priceToPay", "alta"),
        ("#apex_desktop .a-price .a-offscreen", "apex_desktop", "media"),
        ("span.a-price span.a-offscreen", "a-price/offscreen", "media"),
    ]
    for seletor, fonte, conf in seletores:
        try:
            valores = []
            loc = page.locator(seletor)
            total = min(loc.count(), 5)
            for i in range(total):
                txt = normalizar_texto(loc.nth(i).inner_text(timeout=1200))
                if txt and txt not in valores: valores.append(txt)
            if valores: return valores[0], {"source": fonte, "confidence": conf}
        except Exception: continue

    try:
        inteiro = normalizar_texto(page.locator(".a-price-whole").first.inner_text(timeout=1200))
        decimal = normalizar_texto(page.locator(".a-price-fraction").first.inner_text(timeout=800))
        if inteiro: return f"R$ {inteiro},{decimal or '00'}", {"source": "a-price-whole", "confidence": "baixa"}
    except Exception: pass
    return "", {"source": "", "confidence": ""}


def _limpar_marca_byline(txt: str) -> str:
    txt = normalizar_texto(txt)
    if not txt: return ""
    padroes = [r"(?i)^marca\s*:\s*(.+)$", r"(?i)^brand\s*:\s*(.+)$", r"(?i)^visite\s+a\s+loja\s+(.+)$", r"(?i)^visitar\s+a\s+loja\s+(.+)$", r"(?i)^loja\s+(.+)$"]
    for padrao in padroes:
        m = re.search(padrao, txt)
        if m: return normalizar_texto(m.group(1))
    return txt


def extrair_marca_fabricante_amazon(page: Page, attrs: dict[str, str], evidencias: dict[str, dict[str, Any]]) -> tuple[str, str, dict[str, Any]]:
    marca = _valor_por_labels(attrs, ["Marca", "Brand"])
    fabricante = _valor_por_labels(attrs, ["Fabricante", "Manufacturer"])
    fonte: dict[str, Any] = {"marca": {}, "fabricante": {}}

    if marca: fonte["marca"] = evidencias.get(normalizar_chave("Marca"), {}) or {"source": "attrs", "confidence": "alta"}
    if fabricante: fonte["fabricante"] = evidencias.get(normalizar_chave("Fabricante"), {}) or {"source": "attrs", "confidence": "alta"}

    if not marca:
        byline = _texto_primeiro(page, ["#bylineInfo", "a#bylineInfo", "#brand"])
        marca_byline = _limpar_marca_byline(byline)
        if marca_byline:
            marca = marca_byline
            fonte["marca"] = {"source": "#bylineInfo", "confidence": "media", "raw": byline}

    if not marca and fabricante:
        marca = fabricante
        fonte["marca"] = {"source": "fabricante como marca", "confidence": "media"}

    return normalizar_texto(marca), normalizar_texto(fabricante), fonte


def _inferir_modelo_titulo(titulo: str) -> str:
    txt = remover_acentos(titulo)
    padroes = [
        r"\b(sm-[a-z0-9/\-]+)\b", r"\b(iphone\s*\d+\s*(?:pro\s*max|pro|max|plus|mini)?[a-z0-9]*)\b",
        r"\b(galaxy\s*(?:s|a|m|z)\s*\d+[a-z0-9+\-/]*)\b", r"\b(moto\s*g\s*\d+[a-z0-9]*)\b", r"\b(edge\s*\d+[a-z0-9]*)\b",
        r"\b(redmi\s*(?:note\s*)?\d+[a-z0-9]*(?:\s*pro|\s*plus)?)\b", r"\b(poco\s*[a-z]\s*\d+[a-z0-9]*)\b",
        r"\b(realme\s*[a-z0-9]+(?:\s*pro|\s*plus)?)\b", r"\b(zenfone\s*\d+[a-z0-9]*)\b", r"\b(doogee\s*[a-z0-9]+)\b",
        r"\b(umidigi\s*[a-z0-9]+)\b", r"\b(infinix\s*[a-z0-9]+)\b",
    ]
    for padrao in padroes:
        m = re.search(padrao, txt, flags=re.IGNORECASE)
        if m: return normalizar_texto(m.group(1))
    return ""


def _extrair_modelo_anatel_de_texto(texto: str) -> str:
    texto = normalizar_texto(texto)
    if not texto: return ""
    padroes = [r"(?i)\bmodelo\s*[:\-]\s*([A-Z0-9][A-Z0-9._/\-]{2,40})", r"(?i)\bmodel\s*[:\-]\s*([A-Z0-9][A-Z0-9._/\-]{2,40})"]
    for padrao in padroes:
        m = re.search(padrao, texto)
        if m:
            candidato = normalizar_texto(m.group(1))
            candidato = re.sub(r"[,;|].*$", "", candidato).strip(" .-/")
            if _modelo_tecnico_valido(candidato): return candidato
    return ""


def _modelo_tecnico_valido(valor: str) -> bool:
    valor = normalizar_texto(valor)
    if not valor: return False
    v_norm = remover_acentos(valor)
    v_alnum = re.sub(r"[^a-z0-9]", "", v_norm)
    if not v_alnum or len(v_alnum) < 3: return False
    if re.fullmatch(r"(?:19|20)\d{2}", v_alnum): return False
    termos_ruins = ["mediatek", "helio", "snapdragon", "dimensity", "exynos", "processador", "processor", "octa core", "octacore", "camera", "bateria", "android"]
    if any(t in v_norm for t in termos_ruins): return False
    return True


def _procurar_modelo_em_certificacao(attrs: dict[str, str]) -> str:
    for chave, valor in attrs.items():
        if any(t in normalizar_chave(chave) for t in ["certificacao", "certificacoes", "anatel", "homologacao", "teste externa"]):
            modelo = _extrair_modelo_anatel_de_texto(f"{chave} {valor}")
            if modelo: return modelo

    for chave, valor in attrs.items():
        if "modelo" in remover_acentos(f"{chave} {valor}"):
            modelo = _extrair_modelo_anatel_de_texto(f"{chave} {valor}")
            if modelo: return modelo
    return ""


def extrair_modelos_amazon(titulo: str, attrs: dict[str, str], evidencias: dict[str, dict[str, Any]]) -> tuple[dict[str, str], dict[str, Any]]:
    modelo_certificacao = _procurar_modelo_em_certificacao(attrs)
    nome_modelo_raw = _valor_por_labels(attrs, ["Nome do modelo", "Nome do Modelo", "Model Name", "Model name"])
    numero_modelo_raw = _valor_por_labels(attrs, ["Número do modelo", "Numero do modelo", "Nº do modelo", "N do modelo", "Item model number", "Model number"])
    modelo_generico_raw = _valor_por_labels(attrs, ["Modelo", "Model"], excluir=["Nome do modelo", "Número do modelo", "Numero do modelo", "Ano do modelo", "Ano modelo", "Modelo do ano", "Modelo do processador", "Processador", "CPU", "Chipset"])

    nome_modelo = nome_modelo_raw if _modelo_tecnico_valido(nome_modelo_raw) else ""
    numero_modelo = numero_modelo_raw if _modelo_tecnico_valido(numero_modelo_raw) else ""
    modelo_generico = modelo_generico_raw if _modelo_tecnico_valido(modelo_generico_raw) else ""

    fontes: dict[str, Any] = {}
    if modelo_certificacao: fontes["modelo_certificacao"] = {"source": "attrs/certificacao_teste_externa", "confidence": "alta"}
    if nome_modelo: fontes["nome_modelo"] = {"source": "attrs/nome_modelo", "confidence": "alta"}
    if numero_modelo: fontes["numero_modelo"] = {"source": "attrs/numero_modelo", "confidence": "alta"}
    if modelo_generico: fontes["modelo"] = {"source": "attrs/modelo", "confidence": "alta"}

    inferido_titulo = ""
    if not modelo_certificacao and not nome_modelo and not numero_modelo and not modelo_generico:
        inferido_titulo = _inferir_modelo_titulo(titulo)
        if inferido_titulo and _modelo_tecnico_valido(inferido_titulo): fontes["modelo_inferido_titulo"] = {"source": "regex/titulo", "confidence": "media"}
        else: inferido_titulo = ""

    modelo_decisivo = modelo_certificacao or numero_modelo or nome_modelo or modelo_generico or inferido_titulo
    modelos = {
        "modelo": modelo_generico or inferido_titulo,
        "modelo_detalhado": nome_modelo,
        "modelo_alfanumerico": modelo_decisivo,
        "numero_modelo": modelo_decisivo,
    }
    return {k: normalizar_texto(v) for k, v in modelos.items()}, fontes


# ============================================================
# ANATEL
# ============================================================

def normalizar_codigo_anatel_amazon(valor: object) -> str:
    texto = str(valor or "").replace("\xa0", " ")
    if not texto.strip(): return ""

    candidatos: list[str] = []
    padroes = [
        r"(?i)(?:anatel|homolog[aã]c[aã]o|homologacao|certifica[cç][aã]o|certificado)[^0-9]{0,140}((?:\d[\s.\-/]*){8,14})(?![\s.\-/]*\d)",
        r"(?i)((?:\d[\s.\-/]*){8,14})(?![\s.\-/]*\d)[^a-zA-Z0-9]{0,100}(?:anatel|homolog[aã]c[aã]o|homologacao|certifica[cç][aã]o|certificado)",
    ]
    for padrao in padroes:
        for match in re.finditer(padrao, texto):
            numero = re.sub(r"\D", "", match.group(1) or "")
            if 8 <= len(numero) <= 14: candidatos.append(numero)

    if not candidatos and len(texto) <= 500:
        for match in re.finditer(r"(?<!\d)((?:\d[\s.\-/]*){8,14})(?!\d)", texto):
            numero = re.sub(r"\D", "", match.group(1) or "")
            if 8 <= len(numero) <= 14: candidatos.append(numero)

    if not candidatos: return ""
    for numero in candidatos:
        if len(numero) == 12: return numero
    return candidatos[0]


def extrair_codigo_anatel_amazon(page: Page, attrs: dict[str, str], evidencias: dict[str, dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    labels_possiveis = [
        "Anatel", "Código Anatel", "Codigo Anatel", "Certificação Anatel", "Certificacao Anatel",
        "Certificações", "Certificacoes", "Homologação Anatel", "Homologacao Anatel",
        "Número de homologação", "Numero de homologacao", "Número de Homologação Anatel",
        "Numero de Homologacao Anatel", "Número de certificação da Anatel", "Numero de certificacao da Anatel",
    ]
    for label in labels_possiveis:
        valor = _valor_por_labels(attrs, [label])
        codigo = normalizar_codigo_anatel_amazon(f"{label} {valor}") if valor else ""
        if codigo: return codigo, {"source": "attrs/tabela", "confidence": "alta", "label": label, "value": valor}

    script = r"""
    () => {
      const out = []; const seen = new Set();
      const re = /(anatel|homolog|certifica|certificado)/i;
      const selectors = ['tr', 'li', 'td', 'th', 'span', 'p', 'div.a-row', 'div.a-section', '#feature-bullets li', '#detailBullets_feature_div li'];
      for (const sel of selectors) {
        for (const el of document.querySelectorAll(sel)) {
          const txt = (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
          if (!txt || txt.length > 800 || !re.test(txt)) continue;
          if (seen.has(txt)) continue;
          seen.add(txt); out.push({text: txt, selector: sel});
          if (out.length >= 100) return out;
        }
      }
      return out;
    }
    """
    try: itens = page.evaluate(script) or []
    except Exception: itens = []

    for item in itens:
        txt = normalizar_texto(item.get("text"))
        codigo = normalizar_codigo_anatel_amazon(txt)
        if codigo: return codigo, {"source": "elemento_pequeno", "confidence": "media"}

    try:
        html_limpo = page.evaluate(r"() => document.body ? document.body.innerText.replace(/\s+/g, ' ').trim() : ''") or ""
        for chave in ["anatel", "homolog", "certifica", "certificado"]:
            for match in re.finditer(chave, html_limpo, flags=re.IGNORECASE):
                trecho = html_limpo[max(0, match.start() - 100):min(len(html_limpo), match.end() + 260)]
                codigo = normalizar_codigo_anatel_amazon(trecho)
                if codigo: return codigo, {"source": "janela_texto", "confidence": "baixa"}
    except Exception: pass

    return "", {"source": "", "confidence": ""}


# ============================================================
# COMENTÁRIOS / AVALIAÇÕES
# ============================================================

def _coletar_comentarios_na_pagina(page: Page, limite: int, scroll: bool = True) -> list[str]:
    seletores = ["[data-hook='review-body'] span", "[data-hook='review-body']", ".review-text-content span", ".review-text-content", "span[data-hook='review-body']"]
    comentarios: list[str] = []

    voltas = 6 if scroll else 1
    for _ in range(voltas):
        for seletor in seletores:
            try: textos = page.locator(seletor).all_inner_texts()
            except Exception: textos = []
            for txt in textos:
                txt = normalizar_texto(txt)
                if len(txt) >= 3 and txt not in comentarios: comentarios.append(txt)
                if len(comentarios) >= limite: return comentarios[:limite]
        if not scroll: break
        try: page.mouse.wheel(0, 900); page.wait_for_timeout(450)
        except Exception: break
    return comentarios[:limite]


def capturar_comentarios_amazon(page: Page, limite: int = 10) -> list[str]:
    comentarios = _coletar_comentarios_na_pagina(page, limite=limite, scroll=True)
    if len(comentarios) >= limite: return comentarios[:limite]

    href_reviews = _href_primeiro(page, [
        "a[data-hook='see-all-reviews-link-foot']", "#reviews-medley-footer a[href*='product-reviews']",
        "a:has-text('Ver todas as avaliações')", "a:has-text('Ver todas as avaliacoes')", "a:has-text('See all reviews')",
    ])

    if href_reviews:
        review_page = None
        try:
            review_page = page.context.new_page()
            review_page.set_default_timeout(10000)
            review_page.goto(href_reviews, wait_until="domcontentloaded", timeout=45000)
            review_page.wait_for_timeout(1800)
            mais = _coletar_comentarios_na_pagina(review_page, limite=limite, scroll=True)
            for txt in mais:
                if txt not in comentarios: comentarios.append(txt)
                if len(comentarios) >= limite: break
        except Exception: pass
        finally:
            try:
                if review_page: review_page.close()
            except Exception: pass

    return comentarios[:limite]


# ============================================================
# PRODUTO CONSOLIDADO
# ============================================================

def extrair_produto_amazon(page: Page, capturar_reviews: bool = True) -> DadosProduto:
    fechar_modais_amazon(page)
    try: page.wait_for_load_state("domcontentloaded", timeout=15000)
    except Exception: pass

    nome, _ = extrair_nome_amazon(page)
    preco, _ = extrair_preco_amazon(page)
    detalhes_produto_encontrados = preparar_detalhes_produto_amazon(page)
    attrs, evidencias_attrs = _coletar_atributos_amazon(page)
    
    if not detalhes_produto_encontrados:
        chaves_fortes = {"asin", "marca", "nome da marca", "fabricante", "numero do modelo", "n do modelo", "nome do modelo", "certificacao de teste externa", "certificação de teste externa"}
        detalhes_produto_encontrados = any(chave in chaves_fortes for chave in attrs)
        
    marca, fabricante, _ = extrair_marca_fabricante_amazon(page, attrs, evidencias_attrs)
    modelos, _ = extrair_modelos_amazon(nome, attrs, evidencias_attrs)
    codigo, _ = extrair_codigo_anatel_amazon(page, attrs, evidencias_attrs)
    codigo_norm = normalizar_codigo_anatel(codigo) if codigo else ""

    comentarios = capturar_comentarios_amazon(page, limite=10) if capturar_reviews else []

    pacote_evidencias = {
        "marketplace": "amazon",
        "detalhes_produto_encontrados": bool(detalhes_produto_encontrados),
        "atributos": attrs,
    }

    return DadosProduto(
        url=page.url, titulo=normalizar_texto(nome), preco=normalizar_texto(preco),
        codigo_anatel_principal=codigo, codigo_anatel_normalizado=codigo_norm,
        marca=normalizar_texto(marca), fabricante=normalizar_texto(fabricante),
        modelo=normalizar_texto(modelos.get("modelo")), modelo_detalhado=normalizar_texto(modelos.get("modelo_detalhado")),
        modelo_alfanumerico=normalizar_texto(modelos.get("modelo_alfanumerico")), numero_modelo=normalizar_texto(modelos.get("numero_modelo")),
        atributos_json=json.dumps(pacote_evidencias, ensure_ascii=False), comentarios=comentarios,
    )

# ============================================================
# MINI CELULARES AMAZON / DIMENSÕES / SUSPEITOS MANUAIS
# ============================================================

TERMOS_MINI_CELULAR_AMAZON = ["mini celular", "micro celular", "nano celular", "celular mini", "mini telefone", "micro telefone", "mini phone", "micro phone", "tiny phone", "card phone", "key phone", "bluetooth dialer", "dialer gsm", "celular chaveiro", "telefone chaveiro", "celular cartão", "celular cartao", "telefone cartão", "telefone cartao", "celular batom", "telefone batom", "celular caneta", "pen phone"]
TERMOS_CELULAR_FUNCIONAL_AMAZON = ["celular", "telefone", "smartphone", "phone", "dialer", "gsm", "sim", "chip", "imei", "sms", "ligação", "ligacao", "chamada", "dual sim", "2 chips", "dois chips", "cartão sim", "cartao sim", "rede móvel", "rede movel", "2g", "3g", "4g", "lte"]
MARCAS_MODELOS_SUSPEITOS_MINI_AMAZON = ["bm10", "bm20", "bm30", "bm50", "bm70", "bm90", "bm100", "bm200", "bm310", "bt11", "bt22", "b25", "b30", "j8", "j9", "j10", "long-cz", "long cz", "k10", "k33", "k66", "l8star", "l8 star", "gtstar", "gt star", "zanco", "zanco tiny", "servo phone", "servo", "anica", "aizku", "kechaoda", "soyes", "melrose"]
TERMOS_DISFARCE_MINI_AMAZON = ["batom", "batonzinho", "caneta", "pen phone", "isqueiro", "lighter phone", "chaveiro", "chave de carro", "keyring", "cartão", "cartao", "card phone", "key phone", "bmw", "porsche"]
TERMOS_TECNICOS_SUSPEITOS_AMAZON = ["chip", "sim", "gsm", "imei", "sms", "chamada", "ligação", "ligacao", "dual sim", "2 chips", "dois chips", "2g", "3g", "4g", "lte", "bluetooth dialer"]
TERMOS_DESCARTAR_MINI_AMAZON = ["capinha", "capa para", "case para", "pelicula", "película", "carregador", "cabo usb", "cabo tipo c", "fonte", "fone de ouvido", "suporte", "tripé", "tripe", "bateria para", "display para", "tela para", "frontal para", "placa para", "conector para", "flex para", "slot para", "gaveta chip", "adesivo", "miniatura decorativa"]

def _numero_ptbr_float_amazon(valor: object) -> float | None:
    txt = normalizar_texto(valor).replace(" ", "")
    if not txt: return None
    if "," in txt: txt = txt.replace(".", "").replace(",", ".")
    try: return float(txt)
    except Exception: return None

def _converter_medida_cm_amazon(valor: object, unidade: str | None) -> float | None:
    numero = _numero_ptbr_float_amazon(valor)
    if numero is None: return None
    if remover_acentos(unidade or "cm") == "mm": return numero / 10.0
    return numero

def _fmt_cm_amazon(valor: float | None) -> str:
    if valor is None: return ""
    return f"{float(valor):.2f}".rstrip("0").rstrip(".").replace(".", ",")

def _janela_texto_amazon(texto: str, inicio: int, fim: int, margem: int = 90) -> str:
    return normalizar_texto(texto[max(0, inicio - margem):min(len(texto), fim + margem)])

def _extrair_attrs_pacote_amazon(dados: DadosProduto) -> dict[str, str]:
    try: pacote = json.loads(dados.atributos_json or "{}")
    except Exception: return {}
    if isinstance(pacote, dict):
        attrs = pacote.get("atributos")
        if isinstance(attrs, dict): return {str(k): normalizar_texto(v) for k, v in attrs.items()}
        return {str(k): normalizar_texto(v) for k, v in pacote.items() if isinstance(v, (str, int, float))}
    return {}

def _texto_identificacao_mini_amazon(dados: DadosProduto, attrs: dict[str, str]) -> str:
    partes = [dados.titulo, dados.marca, dados.fabricante, dados.modelo, dados.modelo_detalhado, dados.modelo_alfanumerico, dados.numero_modelo]
    for chave, valor in attrs.items():
        if any(t in normalizar_chave(chave) for t in ["marca", "fabricante", "modelo", "certificacao", "anatel", "homologacao", "tecnologia", "sistema", "operadora", "rede", "sim", "chip", "gsm", "imei", "conectividade", "celular", "telefone", "phone"]):
            partes.append(f"{chave}: {valor}")
    return normalizar_texto(" | ".join(str(p or "") for p in partes if p))

def _texto_dimensoes_mini_amazon(dados: DadosProduto, attrs: dict[str, str]) -> str:
    partes = [dados.titulo]
    for chave, valor in attrs.items():
        if any(t in normalizar_chave(chave) for t in ["dimens", "tamanho", "altura", "largura", "comprimento", "profundidade", "espessura", "medida", "produto", "tela"]):
            partes.append(f"{chave}: {valor}")
    for chave, valor in attrs.items():
        texto = f"{chave}: {valor}"
        if re.search(r"\b(?:cm|mm)\b", texto, flags=re.IGNORECASE) and texto not in partes: partes.append(texto)
    return normalizar_texto(" | ".join(str(p or "") for p in partes if p))[:7000]

def _score_evidencia_dimensao_amazon(evidencia: object, maior_cm: float, largura_cm: float) -> tuple[int, float, float]:
    ev = remover_acentos(evidencia or "")
    prioridade = 4
    if "dimensoes do produto" in ev or "dimensao do produto" in ev or "product dimensions" in ev: prioridade = 0
    elif any(t in ev for t in ["dimens", "altura", "largura", "comprimento", "profundidade", "espessura", "tamanho do produto"]): prioridade = 1
    elif "tamanho da tela" in ev or "screen size" in ev: prioridade = 2
    elif any(t in ev for t in [" cm", "mm"]): prioridade = 3
    if any(t in ev for t in ["r$", "frete", "cupom", "parcela", "amazon", "produtos relacionados"]): prioridade += 2
    return (prioridade, float(maior_cm), float(largura_cm))

def _extrair_dimensao_multiplicacao_amazon(texto: str) -> dict[str, Any] | None:
    padrao = re.compile(r"(?P<a>\d+(?:[\.,]\d+)?)\s*(?P<ua>cm|mm)?\s*(?:x|×|por)\s*(?P<b>\d+(?:[\.,]\d+)?)\s*(?P<ub>cm|mm)?(?:\s*(?:x|×|por)\s*(?P<c>\d+(?:[\.,]\d+)?)\s*(?P<uc>cm|mm)?)?", flags=re.IGNORECASE)
    candidatos: list[dict[str, Any]] = []
    for m in padrao.finditer(texto):
        unidades = [m.group("ua"), m.group("ub"), m.group("uc")]
        unidade_padrao = next((u for u in reversed(unidades) if u), "cm")
        valores: list[float] = []
        for nome_num, nome_un in [("a", "ua"), ("b", "ub"), ("c", "uc")]:
            bruto = m.group(nome_num)
            if not bruto: continue
            cm = _converter_medida_cm_amazon(bruto, m.group(nome_un) or unidade_padrao)
            if cm is not None: valores.append(cm)
        if len(valores) < 2 or any(v <= 0 or v > 40 for v in valores): continue
        ordenados = sorted(valores, reverse=True)
        candidatos.append({
            "maior_cm": ordenados[0], "largura_cm": ordenados[1], "espessura_cm": ordenados[2] if len(ordenados) >= 3 else None,
            "evidencia": _janela_texto_amazon(texto, m.start(), m.end(), margem=70), "origem": "multiplicacao",
        })
    if not candidatos: return None
    candidatos.sort(key=lambda d: _score_evidencia_dimensao_amazon(d.get("evidencia"), d["maior_cm"], d["largura_cm"]))
    return candidatos[0]

def _extrair_dimensao_rotulos_amazon(texto: str) -> dict[str, Any] | None:
    rotulos = "altura|comprimento|diâmetro|diametro|largura|profundidade"
    numero = r"\d+(?:[\.,]\d+)?"
    achados: list[dict[str, Any]] = []
    padroes = [
        re.compile(rf"(?P<label>{rotulos})\b(?P<gap>[^0-9]{{0,35}})(?P<num>{numero})\s*(?P<unit>cm|mm)?", flags=re.IGNORECASE),
        re.compile(rf"(?P<num>{numero})\s*(?P<unit>cm|mm)?\s*(?:de\s*)?(?P<label>{rotulos})\b", flags=re.IGNORECASE),
    ]
    for padrao in padroes:
        for m in padrao.finditer(texto):
            tipo = "maior" if any(t in normalizar_chave(m.group("label")) for t in ["altura", "comprimento", "diametro", "profundidade"]) else ("largura" if "largura" in normalizar_chave(m.group("label")) else "")
            if not tipo or re.search(r"\be\b", remover_acentos(m.groupdict().get("gap") or "")): continue
            achados.append({"tipo": tipo, "num": m.group("num"), "unit": m.group("unit"), "start": m.start(), "end": m.end()})

    if not achados: return None
    unidade_padrao = next((a["unit"] for a in achados if a.get("unit")), None)
    if not unidade_padrao: return None

    maior_vals, largura_vals = [], []
    for a in achados:
        cm = _converter_medida_cm_amazon(a["num"], a.get("unit") or unidade_padrao)
        if cm is None or cm <= 0 or cm > 40: continue
        if a["tipo"] == "maior": maior_vals.append(cm)
        elif a["tipo"] == "largura": largura_vals.append(cm)

    if not maior_vals or not largura_vals: return None
    maior, largura = min(maior_vals), min(largura_vals)
    if largura > maior: maior, largura = largura, maior

    return {
        "maior_cm": maior, "largura_cm": largura, "espessura_cm": None,
        "evidencia": _janela_texto_amazon(texto, min(a["start"] for a in achados), max(a["end"] for a in achados), margem=85),
        "origem": "rotulos",
    }

def extrair_dimensoes_mini_amazon(texto: str) -> dict[str, Any] | None:
    texto = normalizar_texto(texto)
    if not texto: return None
    candidatos = [_extrair_dimensao_multiplicacao_amazon(texto), _extrair_dimensao_rotulos_amazon(texto)]
    candidatos = [c for c in candidatos if c]
    if not candidatos: return None
    candidatos.sort(key=lambda d: _score_evidencia_dimensao_amazon(d.get("evidencia"), d["maior_cm"], d["largura_cm"]))
    return candidatos[0]

def _detectar_suspeito_manual_amazon(texto_identificacao_norm: str, titulo_norm: str) -> tuple[bool, str]:
    termo_marca_modelo = next((t for t in MARCAS_MODELOS_SUSPEITOS_MINI_AMAZON if remover_acentos(t) in texto_identificacao_norm), "")
    termo_disfarce = next((t for t in TERMOS_DISFARCE_MINI_AMAZON if remover_acentos(t) in texto_identificacao_norm), "")
    termo_tecnico = next((t for t in TERMOS_TECNICOS_SUSPEITOS_AMAZON if remover_acentos(t) in texto_identificacao_norm), "")
    termo_mini = next((t for t in TERMOS_MINI_CELULAR_AMAZON if remover_acentos(t) in texto_identificacao_norm), "")

    if termo_marca_modelo and (termo_tecnico or termo_mini): return True, f"Marca/modelo suspeito com indício técnico: {termo_marca_modelo}"
    if termo_disfarce and (termo_tecnico or termo_mini): return True, f"Formato/disfarce suspeito com indício técnico: {termo_disfarce}"
    if "bluetooth dialer" in texto_identificacao_norm and termo_tecnico: return True, "Bluetooth dialer com indício de chip/SIM/GSM"
    if any(remover_acentos(t) in titulo_norm for t in ["mini phone", "card phone", "key phone", "mini celular", "celular chaveiro"]): return True, "Título possui termo forte de mini celular/disfarce"
    return False, ""

def analisar_mini_celular_amazon(dados: DadosProduto, maior_max_cm: float = 12.0, largura_max_cm: float = 5.5) -> dict[str, Any]:
    attrs = _extrair_attrs_pacote_amazon(dados)
    titulo_norm = remover_acentos(normalizar_texto(dados.titulo))
    texto_identificacao_norm = remover_acentos(_texto_identificacao_mini_amazon(dados, attrs))

    termo_descartar = next((t for t in TERMOS_DESCARTAR_MINI_AMAZON if remover_acentos(t) in titulo_norm), "")
    if termo_descartar: return {"mini_status": "DESCARTAR_ACESSORIO", "mini_motivo": f"Produto parece acessório/peça, não mini celular: {termo_descartar}", "mini_maior_cm": None, "mini_largura_cm": None, "mini_espessura_cm": None, "mini_evidencia": ""}

    suspeito_manual, motivo_suspeito = _detectar_suspeito_manual_amazon(texto_identificacao_norm, titulo_norm)
    parece_mini = any(remover_acentos(t) in texto_identificacao_norm for t in TERMOS_MINI_CELULAR_AMAZON)
    parece_celular = parece_mini or any(remover_acentos(t) in texto_identificacao_norm for t in TERMOS_CELULAR_FUNCIONAL_AMAZON)

    if not parece_celular and not suspeito_manual:
        return {"mini_status": "DESCARTAR_NAO_CELULAR", "mini_motivo": "Anúncio não possui indício textual suficiente de celular/telefone funcional", "mini_maior_cm": None, "mini_largura_cm": None, "mini_espessura_cm": None, "mini_evidencia": ""}

    dimensoes = extrair_dimensoes_mini_amazon(_texto_dimensoes_mini_amazon(dados, attrs))

    if not dimensoes:
        if suspeito_manual: return {"mini_status": "SUSPEITO_MANUAL", "mini_motivo": f"Sem medida explícita, mas separado para análise manual: {motivo_suspeito}", "mini_maior_cm": None, "mini_largura_cm": None, "mini_espessura_cm": None, "mini_evidencia": ""}
        return {"mini_status": "REVISAR_SEM_MEDIDA" if parece_mini else "DESCARTAR_SEM_MEDIDA", "mini_motivo": "Não encontrei medida explícita em cm/mm", "mini_maior_cm": None, "mini_largura_cm": None, "mini_espessura_cm": None, "mini_evidencia": ""}

    maior = float(dimensoes.get("maior_cm") or 0)
    largura = float(dimensoes.get("largura_cm") or 0)
    espessura = dimensoes.get("espessura_cm")
    evidencia = normalizar_texto(dimensoes.get("evidencia") or "")

    dentro_limite = maior <= float(maior_max_cm) and largura <= float(largura_max_cm)

    return {
        "mini_status": "MANTER" if dentro_limite else "DESCARTAR_MEDIDA",
        "mini_motivo": f"Dentro do limite: maior eixo {_fmt_cm_amazon(maior)} cm <= {_fmt_cm_amazon(maior_max_cm)} cm e largura {_fmt_cm_amazon(largura)} cm <= {_fmt_cm_amazon(largura_max_cm)} cm" if dentro_limite else f"Fora do limite: maior eixo {_fmt_cm_amazon(maior)} cm / largura {_fmt_cm_amazon(largura)} cm",
        "mini_maior_cm": maior,
        "mini_largura_cm": largura,
        "mini_espessura_cm": float(espessura) if espessura is not None else None,
        "mini_evidencia": evidencia,
    }