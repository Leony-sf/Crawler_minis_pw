from __future__ import annotations
import json
import re
from dataclasses import dataclass, asdict
from typing import Any
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from .base_anatel import BaseAnatel, normalizar_homologacao_base
from .utils import apenas_alnum, bloco, gerar_id, log, normalizar_chave, normalizar_texto, remover_acentos

LABELS_MODELO_VALIDAR = [
    "Modelo", "Modelo detalhado", "Modelo alfanumérico", "Modelo alfanumerico",
    "Número do modelo", "Numero do modelo",
]

LABELS_MODELO_IGNORAR = [
    "Modelo do processador", "Modelo de processador",
]

@dataclass
class DadosProduto:
    url: str = ""
    titulo: str = ""
    preco: str = ""
    codigo_anatel_principal: str = ""
    codigo_anatel_normalizado: str = ""
    marca: str = ""
    fabricante: str = ""
    modelo: str = ""
    modelo_detalhado: str = ""
    modelo_alfanumerico: str = ""
    numero_modelo: str = ""
    atributos_json: str = ""
    texto_relevante_mini: str = ""
    comentarios: list[str] | None = None

def _click_suave(page: Page, locator_textos: list[str], timeout_ms: int = 1500) -> bool:
    for texto in locator_textos:
        seletores = [
            f"button:has-text('{texto}')", f"a:has-text('{texto}')", f"span:has-text('{texto}')",
        ]
        for sel in seletores:
            try:
                loc = page.locator(sel).first
                if loc.count() and loc.is_visible(timeout=400):
                    loc.scroll_into_view_if_needed(timeout=timeout_ms)
                    page.wait_for_timeout(250)
                    loc.click(timeout=timeout_ms)
                    page.wait_for_timeout(900)
                    return True
            except Exception:
                continue
    return False

def fechar_modais_leves(page: Page) -> None:
    textos = ["Aceitar cookies", "Entendi", "Mais tarde", "Agora não", "Depois", "Fechar"]
    _click_suave(page, textos, timeout_ms=1000)

def expandir_ficha_tecnica(page: Page) -> bool:
    textos = [
        "Ver todas as características", "Ver todas as caracteristicas",
        "Ver características", "Ver caracteristicas",
        "Ver mais características", "Ver mais caracteristicas",
        "Ficha técnica", "Ficha tecnica",
    ]
    for y in [0, 700, 1400, 2200, 3200]:
        try:
            page.evaluate("window.scrollTo(0, arguments[0])", y)
            page.wait_for_timeout(350)
        except Exception:
            pass
        if _click_suave(page, textos, timeout_ms=1400):
            log("anatel ml", "Ficha técnica/características expandida.")
            return True
    return False

def _coletar_atributos(page: Page) -> dict[str, str]:
    script = r"""
    () => {
      const out = [];
      const seen = new Set();
      function clean(s) { return (s || '').replace(/\s+/g, ' ').trim(); }
      function push(label, value) {
        label = clean(label); value = clean(value);
        if (!label || !value || label === value) return;
        const key = `${label}=>${value}`;
        if (seen.has(key)) return;
        seen.add(key); out.push([label, value]);
      }
      for (const tr of document.querySelectorAll('tr')) {
        const cells = Array.from(tr.children).map(c => clean(c.innerText || c.textContent));
        if (cells.length >= 2) push(cells[0], cells.slice(1).join(' '));
      }
      const candidates = Array.from(document.querySelectorAll('div, li, section'));
      for (const el of candidates) {
        const children = Array.from(el.children).filter(c => clean(c.innerText || c.textContent));
        if (children.length === 2) {
          const a = clean(children[0].innerText || children[0].textContent);
          const b = clean(children[1].innerText || children[1].textContent);
          if (a.length <= 80 && b.length <= 220) push(a, b);
        }
      }
      return out.slice(0, 300);
    }
    """
    pares = []
    try:
        pares = page.evaluate(script) or []
    except Exception:
        pares = []
    attrs: dict[str, str] = {}
    for label, value in pares:
        label_limpo = normalizar_texto(label)
        value_limpo = normalizar_texto(value)
        if not label_limpo or not value_limpo:
            continue
        chave = normalizar_chave(label_limpo)
        if chave not in attrs or len(attrs[chave]) > len(value_limpo):
            attrs[chave] = value_limpo
    return attrs

def _valor_por_labels(attrs: dict[str, str], labels: list[str], excluir: list[str] | None = None) -> str:
    excluir_norm = [normalizar_chave(x) for x in (excluir or [])]
    labels_norm = [normalizar_chave(x) for x in labels]
    for chave, valor in attrs.items():
        if any(ex in chave for ex in excluir_norm):
            continue
        for label in labels_norm:
            if chave == label or chave.endswith(label) or label in chave:
                return valor
    return ""

def extrair_codigo_de_texto(texto: str) -> str:
    texto = normalizar_texto(texto)
    if not texto:
        return ""
    texto_norm = remover_acentos(texto)
    padroes = [
        r"(?i)(?:anatel|homologacao|homologado|certificacao|certificado|numero\s+de\s+homologacao|codigo\s+anatel)[^0-9]{0,180}((?:\d[\s.\-/]*){8,14})(?![\s.\-/]*\d)",
        r"(?i)((?:\d[\s.\-/]*){8,14})(?![\s.\-/]*\d)[^a-z0-9]{0,180}(?:anatel|homologacao|homologado|certificacao|certificado)",
    ]
    candidatos: list[str] = []
    for padrao in padroes:
        for m in re.finditer(padrao, texto_norm):
            dig = re.sub(r"\D", "", m.group(1) or "")
            if 8 <= len(dig) <= 14:
                candidatos.append(dig)
    for c in candidatos:
        if len(c) == 12:
            return c
    return candidatos[0] if candidatos else ""

def extrair_codigo_anatel(page: Page, attrs: dict[str, str]) -> str:
    for chave, valor in attrs.items():
        if any(p in chave for p in ["anatel", "homolog", "certific"]):
            codigo = extrair_codigo_de_texto(f"{chave} {valor}")
            if codigo:
                return codigo
    try:
        texto = page.locator("body").inner_text(timeout=3000)
    except Exception:
        texto = ""
    texto = normalizar_texto(texto)
    for termo in ["anatel", "homolog", "certific"]:
        for m in re.finditer(termo, texto, flags=re.IGNORECASE):
            ini = max(0, m.start() - 240)
            fim = min(len(texto), m.end() + 320)
            codigo = extrair_codigo_de_texto(texto[ini:fim])
            if codigo:
                return codigo
    return ""

# ============================================================
# MINI CELULARES: REGRAS SIMPLIFICADAS E DIRETAS
# ============================================================

TERMOS_FALSO_POSITIVO = [
    "redmi note", "poco x", "poco m", "poco f", "galaxy s", "galaxy a", "galaxy m", "galaxy z",
    "moto g", "moto e", "moto edge", "iphone 11", "iphone 12", "iphone 13", "iphone 14",
    "iphone 15", "iphone 16", "realme c", "infinix note", "infinix hot", "cubot kingkong"
]

TERMOS_ACESSORIOS = [
    "capinha", "capa", "case", "pelicula", "película", "carregador", "cabo usb",
    "cabo tipo c", "fonte", "fone de", "fone bluetooth", "suporte", "tripé", "tripe",
    "bateria para", "display para", "tela para", "placa para", "conector para", "flex para",
    "slot para", "gaveta chip", "smartwatch", "relógio", "relogio", "tablet", "ipad",
    "caixa de som", "alto falante", "speaker", "bolsa", "pochete", "adesivo", "projetor", 
    "adaptador", "microfone", "drone", "brinquedo", "jogo", "aquaplay",
    "tampa para", "tampa de", "borne", "vareta", "carcaça", "jumper", "motor", "calha", "batom","lip",
    "balm", "jumper","tampa","monitor", "protetor", "kit", "manutencao", "manutenção", 
    "milho", "rolo", "rolos", "batedeira", "lanterna", "bloco"
]

TERMOS_ALVOS_CLAROS = [
    "bm10", "bm20", "bm30", "bm50", "bm70", "bm90", "bm100", "bm200", "bm310",
    "bt11", "bt22", "b25", "b30", "b68", "cat b68", "j8", "j9", "j10", "k10", "k33", "k66",
    "soyes", "melrose", "long-cz", "zanco", "l8star", "anica",
    "i17 pro", "i17 pro max", "i17promax", "i16 pro", "i15 pro", "i14 pro", "mini i17", "16pro",
    "batom", "caneta", "isqueiro", "chaveiro", "chave de carro", "porsche", "bmw",
    "cartao", "cartão", "card phone", "flip phone", "ventosa", "dobravel i17", "dobrável i17", "mini celular"
]

def _numero_ptbr_para_float(valor: object) -> float | None:
    txt = normalizar_texto(valor).replace(" ", "")
    if not txt:
        return None
    if "," in txt:
        txt = txt.replace(".", "").replace(",", ".")
    try:
        return float(txt)
    except Exception:
        return None

def _converter_para_cm(valor: object, unidade: str | None) -> float | None:
    numero = _numero_ptbr_para_float(valor)
    if numero is None:
        return None
    unidade_norm = remover_acentos(unidade or "cm")
    if unidade_norm == "mm":
        return numero / 10.0
    return numero

def _fmt_cm(valor: float | None) -> str:
    if valor is None:
        return ""
    txt = f"{valor:.2f}".rstrip("0").rstrip(".")
    return txt.replace(".", ",")

def _janela_texto(texto: str, inicio: int, fim: int, margem: int = 90) -> str:
    ini = max(0, inicio - margem)
    fim = min(len(texto), fim + margem)
    return normalizar_texto(texto[ini:fim])

def _score_evidencia_dimensao(evidencia: object, maior_cm: float, largura_cm: float) -> tuple[int, float, float]:
    ev = remover_acentos(evidencia or "")
    prioridade = 3
    if "caracteristicas do produto" in ev or "ficha tecnica" in ev:
        prioridade = 0
    elif any(t in ev for t in ["dimens", "altura", "largura", "comprimento", "diametro", "tamanho"]):
        prioridade = 1
    elif any(t in ev for t in [" cm", "mm"]):
        prioridade = 2
    if any(t in ev for t in ["frete", "r$", "parcela", "mercado livre", "produtos relacionados"]):
        prioridade += 2
    return (prioridade, float(maior_cm), float(largura_cm))

def _extrair_dimensao_por_multiplicacao(texto: str) -> dict[str, Any] | None:
    padrao = re.compile(
        r"(?P<a>\d+(?:[\.,]\d+)?)\s*(?P<ua>cm|mm)?\s*(?:x| |por)\s*"
        r"(?P<b>\d+(?:[\.,]\d+)?)\s*(?P<ub>cm|mm)?"
        r"(?:\s*(?:x| |por)\s*(?P<c>\d+(?:[\.,]\d+)?)\s*(?P<uc>cm|mm)?)?",
        flags=re.IGNORECASE,
    )
    melhores: list[dict[str, Any]] = []
    for m in padrao.finditer(texto):
        unidades = [m.group("ua"), m.group("ub"), m.group("uc")]
        unidade_padrao = next((u for u in reversed(unidades) if u), "cm")
        valores: list[float] = []
        for nome_num, nome_un in [("a", "ua"), ("b", "ub"), ("c", "uc")]:
            bruto = m.group(nome_num)
            if not bruto:
                continue
            cm = _converter_para_cm(bruto, m.group(nome_un) or unidade_padrao)
            if cm is not None:
                valores.append(cm)
        if len(valores) < 2:
            continue
        if any(v <= 0 or v > 40 for v in valores):
            continue
        ordenados = sorted(valores, reverse=True)
        melhores.append(
            {
                "maior_cm": ordenados[0],
                "largura_cm": ordenados[1],
                "espessura_cm": ordenados[2] if len(ordenados) >= 3 else None,
                "evidencia": _janela_texto(texto, m.start(), m.end(), margem=55),
                "origem": "multiplicacao",
            }
        )
    if not melhores:
        return None
    melhores.sort(key=lambda d: _score_evidencia_dimensao(d.get("evidencia"), d["maior_cm"], d["largura_cm"]))
    return melhores[0]

def _normalizar_rotulo_dimensao(rotulo: str) -> str:
    r = normalizar_chave(rotulo)
    if any(t in r for t in ["altura", "comprimento", "diametro"]):
        return "maior"
    if "largura" in r:
        return "largura"
    return ""

def _extrair_dimensao_por_rotulos(texto: str) -> dict[str, Any] | None:
    rotulos = "altura|comprimento|diametro|diâmetro|largura"
    numero = r"\d+(?:[\.,]\d+)?"
    achados: list[dict[str, Any]] = []
    padroes = [
        re.compile(rf"(?P<label>{rotulos})\b(?P<gap>[^0-9]{{0,35}})(?P<num>{numero})\s*(?P<unit>cm|mm)?", flags=re.IGNORECASE),
        re.compile(rf"(?P<num>{numero})\s*(?P<unit>cm|mm)?\s*(?:de\s*)?(?P<label>{rotulos})\b", flags=re.IGNORECASE),
    ]
    for padrao in padroes:
        for m in padrao.finditer(texto):
            tipo = _normalizar_rotulo_dimensao(m.group("label"))
            if not tipo:
                continue
            grupos = m.groupdict()
            gap = grupos.get("gap") or ""
            if re.search(r"\be\b", remover_acentos(gap)):
                continue
            if "gap" not in grupos:
                antes = texto[max(0, m.start() - 40):m.start()]
                if re.search(r"(altura|comprimento|diametro|diâmetro|largura)\b\s*[:=\-]?\s*$", antes, flags=re.IGNORECASE):
                    continue
            achados.append(
                {
                    "tipo": tipo,
                    "num": m.group("num"),
                    "unit": m.group("unit"),
                    "start": m.start(),
                    "end": m.end(),
                }
            )
    if not achados:
        return None
    unidade_padrao = next((a["unit"] for a in achados if a.get("unit")), None)
    if not unidade_padrao:
        return None
    maior_vals: list[float] = []
    largura_vals: list[float] = []
    ini = min(a["start"] for a in achados)
    fim = max(a["end"] for a in achados)
    for a in achados:
        cm = _converter_para_cm(a["num"], a.get("unit") or unidade_padrao)
        if cm is None or cm <= 0 or cm > 40:
            continue
        if a["tipo"] == "maior":
            maior_vals.append(cm)
        elif a["tipo"] == "largura":
            largura_vals.append(cm)
    if not maior_vals or not largura_vals:
        return None
    maior = min(maior_vals)
    largura = min(largura_vals)
    if largura > maior:
        maior, largura = largura, maior
    return {
        "maior_cm": maior,
        "largura_cm": largura,
        "espessura_cm": None,
        "evidencia": _janela_texto(texto, ini, fim, margem=75),
        "origem": "rotulos",
    }

def extrair_dimensoes_mini_celular(texto: str) -> dict[str, Any] | None:
    texto = normalizar_texto(texto)
    if not texto:
        return None
    candidatos = [
        _extrair_dimensao_por_multiplicacao(texto),
        _extrair_dimensao_por_rotulos(texto),
    ]
    candidatos = [c for c in candidatos if c]
    if not candidatos:
        return None
    candidatos.sort(key=lambda d: _score_evidencia_dimensao(d.get("evidencia"), d["maior_cm"], d["largura_cm"]))
    return candidatos[0]

def _termo_presente(texto_norm: str, termo: str) -> bool:
    termo_norm = remover_acentos(termo)
    if not termo_norm:
        return False
    padrao = r"(?<![a-z0-9])" + re.escape(termo_norm) + r"(?![a-z0-9])"
    return re.search(padrao, texto_norm, flags=re.IGNORECASE) is not None

def _base_retorno_mini(maior_max_cm: float, largura_max_cm: float) -> dict[str, Any]:
    return {
        "mini_suspeito_manual": "NAO",
        "mini_suspeito_tipo": "",
        "mini_suspeito_motivo": "",
        "mini_limite_maior_cm": maior_max_cm,
        "mini_limite_largura_cm": largura_max_cm,
    }

def analisar_mini_celular(
    dados: DadosProduto,
    maior_max_cm: float = 12.0,
    largura_max_cm: float = 5.5,
) -> dict[str, Any]:
    """A nova lógica simplificada de captura."""
    
    texto_titulo_norm = remover_acentos(normalizar_texto(dados.titulo))
    texto_id_norm = remover_acentos(normalizar_texto(f"{dados.titulo} {dados.marca} {dados.modelo}"))
    extras_base = _base_retorno_mini(maior_max_cm, largura_max_cm)

    # 1. PENEIRA DE PREÇO (Entre R$ 30 e R$ 900)
    preco_num = _numero_ptbr_para_float(dados.preco)
    if preco_num is not None:
        if preco_num > 900.0:
            return {**extras_base, "mini_status": "DESCARTAR_PRECO_ALTO", "mini_motivo": f"Preço R$ {preco_num} é alto demais para alvos", "mini_evidencia": f"R$ {dados.preco}"}
        if preco_num < 30.0:
            return {**extras_base, "mini_status": "DESCARTAR_PRECO_BAIXO", "mini_motivo": f"Preço R$ {preco_num} é baixo demais (golpe/peça)", "mini_evidencia": f"R$ {dados.preco}"}

    # 2. DESCARTA ACESSÓRIOS (Capinhas, Fones, etc)
    termo_acessorio = next((t for t in TERMOS_ACESSORIOS if _termo_presente(texto_titulo_norm, t)), "")
    if termo_acessorio:
        return {**extras_base, "mini_status": "DESCARTAR_ACESSORIO", "mini_motivo": f"É acessório: {termo_acessorio}", "mini_evidencia": ""}

    # 3. ESCUDO ANTI-FALSO POSITIVO (Marcas famosas)
    termo_fp = next((t for t in TERMOS_FALSO_POSITIVO if _termo_presente(texto_titulo_norm, t)), "")
    if termo_fp:
        return {**extras_base, "mini_status": "DESCARTAR_FALSO_POSITIVO", "mini_motivo": f"Celular comum de marca famosa: {termo_fp}", "mini_evidencia": ""}

    # 4. CAPTURA ALVOS CRIMINOSOS EXPLÍCITOS (i17 pro, b68, ventosa...)
    termo_alvo = next((t for t in TERMOS_ALVOS_CLAROS if _termo_presente(texto_id_norm, t)), "")
    if termo_alvo:
        return {
            **extras_base,
            "mini_status": "MANTER",
            "mini_motivo": f"Alvo criminoso direto: {termo_alvo}",
            "mini_suspeito_manual": "SIM",
            "mini_suspeito_tipo": "ALVO_CONHECIDO",
            "mini_suspeito_motivo": f"Encontrado termo alvo: {termo_alvo}",
            "mini_evidencia": dados.titulo,
        }

    # 5. TESTE DE DIMENSÃO PARA OS RESTANTES
    attrs_txt = ""
    try:
        attrs = json.loads(dados.atributos_json or "{}")
        attrs_txt = " ".join(f"{k}: {v}" for k, v in attrs.items())
    except Exception:
        attrs_txt = dados.atributos_json or ""
    
    fontes_dimensao = [dados.titulo, attrs_txt, dados.texto_relevante_mini]
    dimensoes = None
    fonte_usada = ""
    for fonte in fontes_dimensao:
        dim = extrair_dimensoes_mini_celular(fonte)
        if dim:
            dimensoes = dim
            fonte_usada = fonte[:200]
            break

    if not dimensoes:
        return {**extras_base, "mini_status": "DESCARTAR_SEM_MEDIDA", "mini_motivo": "Sem medida ou indício de alvo", "mini_evidencia": ""}
        
    maior = float(dimensoes.get("maior_cm") or 0)
    largura = float(dimensoes.get("largura_cm") or 0)
    
    if maior <= float(maior_max_cm) and largura <= float(largura_max_cm):
        return {
            **extras_base,
            "mini_status": "MANTER",
            "mini_motivo": f"Medidas confirmam mini celular: {_fmt_cm(maior)} x {_fmt_cm(largura)} cm",
            "mini_maior_cm": maior,
            "mini_largura_cm": largura,
            "mini_evidencia": dimensoes.get("evidencia", ""),
            "mini_fonte_dimensao": fonte_usada,
        }

    return {**extras_base, "mini_status": "DESCARTAR_MEDIDA", "mini_motivo": f"Maior que o limite: {_fmt_cm(maior)} cm", "mini_evidencia": ""}

def capturar_comentarios(page: Page, limite: int = 10) -> list[str]:
    bloco("comentários")
    log("comentários", f"Tentando capturar até {limite} comentários.")
    comentarios: list[str] = []
    textos_botao = ["Ver todas as opiniões", "Ver opiniões", "Opiniões", "Ver avaliações", "Avaliações"]
    _click_suave(page, textos_botao, timeout_ms=1200)
    try:
        page.wait_for_timeout(1000)
    except Exception:
        pass
    seletores = [
        ".ui-review-capability-comments__comment__content",
        ".ui-review-capability-comments__comment__content p",
        ".ui-review-capability__comment",
        ".ui-review-capability-comments__comment",
        "[data-testid*='comment']",
    ]
    for _ in range(10):
        for sel in seletores:
            try:
                for txt in page.locator(sel).all_inner_texts():
                    txt = normalizar_texto(txt)
                    if len(txt) >= 3 and txt not in comentarios:
                        comentarios.append(txt)
                    if len(comentarios) >= limite:
                        break
            except Exception:
                pass
            if len(comentarios) >= limite:
                break
        if len(comentarios) >= limite:
            break
        try:
            page.mouse.wheel(0, 900)
            page.wait_for_timeout(450)
        except Exception:
            break
    log("comentários", f"Comentários capturados: {len(comentarios[:limite])}")
    return comentarios[:limite]

def extrair_produto(page: Page, capturar_reviews: bool = True) -> DadosProduto:
    fechar_modais_leves(page)
    expandir_ficha_tecnica(page)
    try:
        titulo = page.locator("h1, .ui-pdp-title").first.inner_text(timeout=6000)
    except Exception:
        titulo = ""
    try:
        preco = page.locator(".andes-money-amount__fraction, .price-tag-fraction").first.inner_text(timeout=1500)
    except Exception:
        preco = ""
    attrs = _coletar_atributos(page)
    marca = _valor_por_labels(attrs, ["Marca"])
    fabricante = _valor_por_labels(attrs, ["Fabricante"])
    modelo = _valor_por_labels(attrs, ["Modelo"], excluir=LABELS_MODELO_IGNORAR + ["Modelo detalhado", "Modelo alfanumérico", "Modelo alfanumerico"])
    modelo_detalhado = _valor_por_labels(attrs, ["Modelo detalhado"])
    modelo_alfanumerico = _valor_por_labels(attrs, ["Modelo alfanumérico", "Modelo alfanumerico"])
    numero_modelo = _valor_por_labels(attrs, ["Número do modelo", "Numero do modelo"])
    codigo = extrair_codigo_anatel(page, attrs)
    codigo_norm = normalizar_homologacao_base(codigo) if codigo else ""
    texto_relevante_mini = ""
    comentarios = capturar_comentarios(page, limite=10) if capturar_reviews else []
    return DadosProduto(
        url=page.url,
        titulo=normalizar_texto(titulo),
        preco=normalizar_texto(preco),
        codigo_anatel_principal=codigo,
        codigo_anatel_normalizado=codigo_norm,
        marca=normalizar_texto(marca),
        fabricante=normalizar_texto(fabricante),
        modelo=normalizar_texto(modelo),
        modelo_detalhado=normalizar_texto(modelo_detalhado),
        modelo_alfanumerico=normalizar_texto(modelo_alfanumerico),
        numero_modelo=normalizar_texto(numero_modelo),
        atributos_json=json.dumps(attrs, ensure_ascii=False),
        texto_relevante_mini=texto_relevante_mini,
        comentarios=comentarios,
    )

def _alias_marca(marca: str) -> set[str]:
    m = remover_acentos(marca)
    tokens = set(re.findall(r"[a-z0-9]+", m))
    aliases = set(tokens)
    joined = " ".join(tokens)
    regras = {
        "xiaomi": ["xiaomi", "redmi", "poco", "mi"],
        "apple": ["apple", "iphone", "ipad", "airpods", "macbook"],
        "samsung": ["samsung", "galaxy"],
        "motorola": ["motorola", "moto"],
        "oppo": ["oppo"],
        "realme": ["realme"],
        "asus": ["asus", "rog", "zenfone"],
        "doogee": ["doogee"],
        "umidigi": ["umidigi"],
        "infinix": ["infinix"],
        "honor": ["honor"],
        "huawei": ["huawei"],
        "nokia": ["nokia"],
        "positivo": ["positivo"],
        "multilaser": ["multilaser", "multi"],
        "tcl": ["tcl"],
    }
    for canon, vals in regras.items():
        if any(v in tokens or v in joined for v in vals):
            aliases.add(canon)
            aliases.update(vals)
    return {a for a in aliases if len(a) >= 2}

def marca_compativel(marca_capturada: str, fabricante_base: str) -> bool:
    marca_capturada = normalizar_texto(marca_capturada)
    fabricante_base = normalizar_texto(fabricante_base)
    if not marca_capturada or not fabricante_base:
        return False
    aliases = _alias_marca(marca_capturada)
    fab_norm = remover_acentos(fabricante_base)
    fab_tokens = set(re.findall(r"[a-z0-9]+", fab_norm))
    for alias in aliases:
        if alias in fab_tokens or alias in fab_norm:
            return True
    return False

def _normalizar_modelo_comparacao(valor: str) -> str:
    return apenas_alnum(valor)

def _partes_modelo_no_campo(valor: str) -> list[str]:
    txt = normalizar_texto(valor)
    if not txt:
        return []
    partes = re.split(
        r"\s*(?:,|;|\||\s+\+\s+|\s+e\s+|\s+ou\s+)\s*",
        txt,
        flags=re.IGNORECASE,
    )
    saida: list[str] = []
    vistos: set[str] = set()
    for parte in partes:
        parte = normalizar_texto(parte)
        chave = _normalizar_modelo_comparacao(parte)
        if len(chave) < 3:
            continue
        if chave not in vistos:
            vistos.add(chave)
            saida.append(parte)
    return saida

def modelo_compativel(modelo_capturado: str, modelo_base: str) -> bool:
    a = _normalizar_modelo_comparacao(modelo_capturado)
    b = _normalizar_modelo_comparacao(modelo_base)
    if not a or not b:
        return False
    return a == b

def _modelos_capturados(dados: DadosProduto) -> dict[str, str]:
    modelos = {
        "Modelo": dados.modelo,
        "Modelo detalhado": dados.modelo_detalhado,
        "Modelo alfanumérico": dados.modelo_alfanumerico,
        "Número do modelo": dados.numero_modelo,
    }
    return {k: normalizar_texto(v) for k, v in modelos.items() if normalizar_texto(v)}

def _modelo_decisivo_capturado(dados: DadosProduto) -> tuple[str, str]:
    prioridade = [
        ("Modelo alfanumérico", dados.modelo_alfanumerico),
        ("Modelo detalhado", dados.modelo_detalhado),
        ("Modelo", dados.modelo),
    ]
    for label, valor in prioridade:
        valor_norm = normalizar_texto(valor)
        if valor_norm:
            return label, valor_norm
    return "", ""


def validar_produto(dados: DadosProduto, base: BaseAnatel | None) -> dict[str, Any]:
    motivos_irreg: list[str] = []
    avisos: list[str] = []
    
    codigo = dados.codigo_anatel_normalizado or normalizar_homologacao_base(dados.codigo_anatel_principal)
    
    bloco("anatel")
    if not codigo:
        motivos_irreg.append("Código ANATEL não encontrado")
        log("anatel", "Código capturado: não encontrado")
    else:
        log("anatel", f"Código capturado: {dados.codigo_anatel_principal}")
        log("anatel", f"Código normalizado: {codigo}")
        
    if not codigo:
        status = "IRREGULAR"
        return _resultado_validacao(status, motivos_irreg, avisos, modo_base="sem_codigo")
        
    if base is None:
        avisos.append("Código ANATEL capturado, mas nenhuma base foi informada")
        return _resultado_validacao("SEM_BASE", motivos_irreg, avisos, modo_base="sem_base")
        
    modo, candidatos = base.candidatos_para_codigo(codigo)
    pref = codigo[: base.prefix_len]
    
    bloco("base")
    log("base", f"Código exato no CSV: {'SIM' if modo == 'exato' else 'NÃO'}")
    log("base", f"Prefixo {pref} no CSV: {'SIM' if modo in ['exato', 'prefixo'] else 'NÃO'}")
    
    if modo == "nenhum" or candidatos.empty:
        motivos_irreg.append(f"Código ANATEL {codigo} não existe na base nem por prefixo {base.prefix_len}")
        return _resultado_validacao("IRREGULAR", motivos_irreg, avisos, modo_base="nenhum")
        
    if modo == "prefixo":
        avisos.append(f"Código sem match exato, mas prefixo {pref} existe na base")
        
    bloco("marca x base")
    if dados.marca:
        fabricantes = [normalizar_texto(v) for v in candidatos.get("fabricante_base", []).tolist() if normalizar_texto(v)]
        if fabricantes:
            ok_marca = any(marca_compativel(dados.marca, fab) for fab in fabricantes)
            log("marca x base", f"Marca capturada: {dados.marca}")
            log("marca x base", f"Fabricantes candidatos: {', '.join(fabricantes[:5])}")
            if not ok_marca:
                motivos_irreg.append(
                    f"Marca '{dados.marca}' diverge da base para o código/prefixo. Base encontrada: {', '.join(fabricantes[:5])}"
                )
        else:
            avisos.append("Base não possui fabricante para validar marca")
    else:
        avisos.append("Marca não capturada no anúncio")
        
    status = "IRREGULAR" if motivos_irreg else "REGULAR"
    return _resultado_validacao(status, motivos_irreg, avisos, modo_base=modo)


def _resultado_validacao(status: str, motivos_irreg: list[str], avisos: list[str], modo_base: str) -> dict[str, Any]:
    motivos = motivos_irreg + avisos
    bloco("resultado")
    log("resultado", f"Situação final: {status}")
    if motivos_irreg:
        log("resultado", "Irregularidades:")
        for m in motivos_irreg:
            print(f"- {m}")
    if avisos:
        log("resultado", "Avisos:")
        for a in avisos:
            print(f"- {a}")
    return {
        "status_validacao": status,
        "motivo_validacao": "; ".join(motivos),
        "irregularity_reasons": "; ".join(motivos_irreg),
        "warnings": "; ".join(avisos),
        "modo_match_base": modo_base,
    }


def dados_para_linha(dados: DadosProduto, validacao: dict[str, Any]) -> dict[str, Any]:
    status = validacao.get("status_validacao", "")
    pid = gerar_id(dados.titulo, dados.marca, dados.codigo_anatel_normalizado, dados.url)
    modelos = _modelos_capturados(dados)
    modelo_decisivo_label, modelo_decisivo_valor = _modelo_decisivo_capturado(dados)
    
    linha = {
        "pid": pid,
        "marketplace_id": "2",
        "name": dados.titulo,
        "titulo": dados.titulo,
        "link": dados.url,
        "url": dados.url,
        "anatel_number": dados.codigo_anatel_normalizado,
        "codigo_anatel_principal": dados.codigo_anatel_normalizado,
        "brand": dados.marca,
        "marca": dados.marca,
        "price": dados.preco,
        "preco": dados.preco,
        "reviewers": "",
        "status": "Irregular" if status == "IRREGULAR" else ("Regular" if status == "REGULAR" else status),
        "status_validacao": status,
        "irregularity_reasons": validacao.get("irregularity_reasons", ""),
        "motivo_validacao": validacao.get("motivo_validacao", ""),
        "warnings": validacao.get("warnings", ""),
        "created_at": "",
        "modelo": dados.modelo,
        "modelo_detalhado": dados.modelo_detalhado,
        "modelo_alfanumerico": dados.modelo_alfanumerico,
        "numero_modelo": dados.numero_modelo,
        "modelo_decisivo_label": modelo_decisivo_label,
        "modelo_decisivo": modelo_decisivo_valor,
        "modelo_decisivo_partes_json": json.dumps(_partes_modelo_no_campo(modelo_decisivo_valor), ensure_ascii=False),
        "modelos_capturados_json": json.dumps(modelos, ensure_ascii=False),
        "fabricante": dados.fabricante,
        "modo_match_base": validacao.get("modo_match_base", ""),
    }
    return linha