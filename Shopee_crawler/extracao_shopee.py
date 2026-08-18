from __future__ import annotations
import re
from typing import Any
from bs4 import BeautifulSoup

from base_anatel import normalizar_codigo_anatel
from utils import normalizar_texto, normalizar_chave, juntar_textos

LABELS_MARCA = ["marca", "brand"]
LABELS_MODELO = ["modelo", "modelo alfanumerico", "numero do modelo"]
LABELS_FABRICANTE = ["fabricante", "nome do fabricante"]
LABELS_ANATEL = ["anatel", "codigo anatel", "homologacao", "numero de homologacao"]

LIMITE_ALTURA_CM = 12.0
LIMITE_LARGURA_CM = 5.5

TERMOS_TELEFONIA = {
    "celular", "telefone", "smartphone", "phone", "chip", "gsm", "sim card", "dual sim", "2 chips"
}
TERMOS_MINI_FORTES = {
    "mini celular", "micro celular", "bm10", "bm20", "bm30", "bm50", "bm70", 
    "l8star", "zanco", "long cz", "soyes", "celular chaveiro", "celular cartao"
}
PADROES_FORA_ESCOPO = [
    r"^\s*(capa|capinha|case|pelicula|vidro)\b",
    r"^\s*(carregador|cabo|fonte|suporte)\b",
    r"^\s*(fone|headset|earbud|caixa de som)\b",
    r"^\s*(bateria|display|tela|placa|conector)\b",
    r"\bsmartwatch\b",
]

def extrair_label_values(html: str, texto_extra: str = "") -> dict[str, str]:
    soup = BeautifulSoup(html or "", "lxml")
    pares: dict[str, str] = {}
    for tr in soup.select("tr"):
        celulas = [c.get_text(" ", strip=True) for c in tr.select("th, td")]
        if len(celulas) >= 2 and celulas[0] and celulas[1]:
            pares[celulas[0].strip(" :")] = celulas[1].strip()
    return pares

def _buscar_por_labels(pares: dict[str, str], labels: list[str]) -> str:
    for c, v in pares.items():
        cn = normalizar_texto(c)
        if any(normalizar_texto(l) in cn for l in labels): return str(v).strip()
    return ""

def extrair_dados_html(html: str, url: str = "", texto_extra: str = "") -> dict[str, Any]:
    soup = BeautifulSoup(html or "", "lxml")
    pares = extrair_label_values(html, texto_extra)
    
    titulo = ""
    for sel in ["meta[property='og:title']", "h1", "[class*='product-title']"]:
        el = soup.select_one(sel)
        if el:
            titulo = el.get("content") if el.name == "meta" else el.get_text(" ", strip=True)
            if titulo: break
            
    preco = ""
    for sel in ["meta[property='product:price:amount']", "[class*='price']"]:
        el = soup.select_one(sel)
        if el:
            txt = el.get("content") if el.name == "meta" else el.get_text(" ", strip=True)
            if txt:
                preco = txt
                break

    codigos = []
    texto_total = normalizar_texto(titulo + " " + texto_extra)
    for m in re.findall(r"[\d.\-/\s]{8,24}", texto_total):
        dig = re.sub(r"\D", "", m)
        if 8 <= len(dig) <= 12: codigos.append(normalizar_codigo_anatel(dig))
        
    return {
        "url": url,
        "titulo": titulo,
        "preco": preco,
        "marca": _buscar_por_labels(pares, LABELS_MARCA),
        "modelo": _buscar_por_labels(pares, LABELS_MODELO),
        "fabricante": _buscar_por_labels(pares, LABELS_FABRICANTE),
        "codigo_anatel_principal": codigos[0] if codigos else "",
        "texto_relevante_mini": texto_total,
        "atributos": pares
    }

def analisar_dimensoes_produto(dados: dict[str, Any]) -> dict[str, Any]:
    texto = str(dados.get("texto_relevante_mini", ""))
    padrao = re.compile(r"(\d+(?:[\.,]\d+)?)\s*(?:cm|mm)?\s*(?:x|×|por)\s*(\d+(?:[\.,]\d+)?)\s*(?:cm|mm)?", re.IGNORECASE)
    
    valores = []
    evidencia = ""
    
    for m in padrao.finditer(texto):
        v1 = float(m.group(1).replace(",", "."))
        v2 = float(m.group(2).replace(",", "."))
        if "mm" in m.group(0).lower():
            v1, v2 = v1 / 10.0, v2 / 10.0
        
        if 0 < v1 < 60 and 0 < v2 < 60:
            valores = sorted([v1, v2], reverse=True)
            evidencia = texto[max(0, m.start()-40):min(len(texto), m.end()+40)]
            break

    if not valores:
        return {
            "dimensoes_encontradas": "NAO", "dimensoes_confiaveis": "NAO",
            "dentro_limite_dimensional": "NAO_VERIFICADO",
            "altura_cm": None, "largura_cm": None, "espessura_cm": None,
            "origem_dimensoes": "", "evidencia_dimensoes": "",
            "motivo_dimensoes": "Dimensões não localizadas."
        }
        
    dentro = valores[0] <= LIMITE_ALTURA_CM and valores[1] <= LIMITE_LARGURA_CM
    return {
        "dimensoes_encontradas": "SIM", "dimensoes_confiaveis": "SIM",
        "dentro_limite_dimensional": "SIM" if dentro else "NAO",
        "altura_cm": valores[0], "largura_cm": valores[1], "espessura_cm": None,
        "origem_dimensoes": "Shopee", "evidencia_dimensoes": evidencia,
        "motivo_dimensoes": f"Dimensões {'dentro' if dentro else 'acima'} do limite de 12 × 5,5 cm."
    }

def _analisar_indicios(dados: dict[str, Any]) -> dict[str, str]:
    texto = normalizar_texto(dados.get("texto_relevante_mini", ""))
    titulo = normalizar_texto(dados.get("titulo", ""))
    
    fora_escopo = ""
    for padrao in PADROES_FORA_ESCOPO:
        match = re.search(padrao, titulo, flags=re.IGNORECASE)
        if match:
            fora_escopo = match.group(0).strip()
            break

    ev_mini = next((t for t in TERMOS_MINI_FORTES if t in texto), "")
    ev_tel = next((t for t in TERMOS_TELEFONIA if t in texto), "")
    
    return {
        "fora_escopo": "SIM" if fora_escopo else "NAO",
        "motivo_fora_escopo": fora_escopo,
        "evidencia_mini": ev_mini,
        "evidencia_telefonia": ev_tel,
        "tem_indicios": "SIM" if ev_mini or ev_tel else "NAO"
    }

def classificar_produto(dados: dict[str, Any], analise_dimensional: dict[str, Any], analise_anatel: dict[str, Any]) -> dict[str, Any]:
    indicios = _analisar_indicios(dados)
    dim_conf = analise_dimensional.get("dimensoes_confiaveis") == "SIM"
    dentro = analise_dimensional.get("dentro_limite_dimensional") == "SIM"
    anatel_ok = analise_anatel.get("anatel_em_ordem") == "SIM"
    codigo = analise_anatel.get("codigo_anatel_normalizado", "")
    
    res = {
        "classificacao": "DESCARTADO", "motivo_classificacao": "",
        "evidencia_telefonia": indicios["evidencia_telefonia"],
        "evidencia_mini": indicios["evidencia_mini"]
    }

    if indicios["fora_escopo"] == "SIM":
        res["motivo_classificacao"] = f"Fora do escopo pelo título: {indicios['motivo_fora_escopo']}."
        return res

    if not dim_conf:
        if indicios["tem_indicios"] == "SIM":
            res["classificacao"] = "SUSPEITO"
            res["motivo_classificacao"] = "Indícios de telefonia, mas sem dimensões confiáveis."
        else:
            res["motivo_classificacao"] = "Sem dimensões e sem indícios suficientes."
        return res

    if not dentro:
        res["motivo_classificacao"] = "Dimensões corporais maiores que o limite de 12 × 5,5 cm."
        return res

    if indicios["tem_indicios"] != "SIM":
        res["motivo_classificacao"] = "Dimensões reduzidas, mas sem indícios de celular."
        return res

    status_req = analise_anatel.get("situacao_requerimento_normalizada", "")
    if status_req in {"CANCELADA", "SUSPENSA"}:
        res["classificacao"] = "IRREGULAR"
        res["motivo_classificacao"] = f"Homologação {status_req.lower()} na base Anatel."
        return res

    if anatel_ok:
        res["motivo_classificacao"] = "Dimensões no limite e Anatel em conformidade com a base."
        return res

    res["classificacao"] = "IRREGULAR"
    res["motivo_classificacao"] = "Dimensões no limite, mas código Anatel ausente ou divergente da base."
    return res