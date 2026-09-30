# -*- coding: utf-8 -*-
"""
Regras de classificação para o crawler Magalu.

Regra operacional atualizada por dimensões:
- Aparelho celular com altura <= 120 mm (12 cm) E largura <= 55 mm (5,5 cm) = IRREGULAR (Mini Celular);
- Aparelho celular com dimensões ligeiramente acima = SUSPEITO;
- Aparelho celular sem medida física localizada = REVISAR;
- Aparelho celular com dimensões maiores = DESCARTADO;
- Acessórios/peças/brinquedos sem indício real de telefonia são descartados.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# Novos limites solicitados: 12 cm de altura por 5,5 cm de largura
LIMITE_ALTURA_MAX_MM = 120.0  # 12 cm
LIMITE_LARGURA_MAX_MM = 55.0  # 5,5 cm
MARGEM_SUSPEITA_MM = 10.0     # Margem para faixa suspeita

TERMOS_TELEFONIA = [
    "dual sim", "single sim", "dois chips", "2 chips", "chip", "sim card",
    "nano sim", "micro sim", "gsm", "2g", "3g", "4g", "5g", "lte", "volte",
    "celular", "telefone celular", "telefone móvel", "telefone movel", "smartphone",
    "feature phone", "mobile phone", "cell phone", "cellphone", "flip phone",
    "telefone simples", "celular simples", "celular antigo", "tijolinho",
    "chamada", "ligações", "ligacoes", "realiza chamada", "discagem",
]

TERMOS_TELEFONIA_FORTE = [
    "dual sim", "dois chips", "2 chips", "sim card", "gsm", "lte", "volte",
    "celular", "telefone celular", "smartphone", "mobile phone", "cell phone",
    "feature phone", "flip phone", "celular simples", "tijolinho",
]

TERMOS_ACESSORIO = [
    "capa", "capinha", "case", "cover", "película", "pelicula", "vidro temperado",
    "screen protector", "tempered glass", "carregador", "cabo usb", "fonte",
    "bateria", "bateria para", "tela para", "display para", "lcd para",
    "peça", "peca", "peças", "pecas", "conector", "flex", "placa", "suporte",
    "fone de ouvido", "headphone", "headset", "adaptador", "carteira", "bolsa",
]

TERMOS_BRINQUEDO = [
    "brinquedo", "infantil educativo", "educativo", "toy phone", "kids toy",
    "children toy", "mini smartphone infantil", "telefone infantil",
]

PADROES_ANATEL = [
    re.compile(r"\bANATEL\b[^\d]{0,45}(\d{8,13})", re.IGNORECASE),
    re.compile(r"\b(\d{5}[-\s]?\d{2}[-\s]?\d{4})\b"),
]


@dataclass
class Classificacao:
    status: str
    categoria_print: str
    motivos: List[str] = field(default_factory=list)
    evidencias: List[str] = field(default_factory=list)
    codigo_anatel: str = ""

    tela_extraida: str = ""
    tela_polegadas: Optional[float] = None
    tela_mini: bool = False
    tela_suspeita: bool = False
    tela_grande: bool = False

    eh_mini_celular: bool = False
    eh_acessorio: bool = False
    sem_tela: bool = False
    regra_classificacao: str = ""

    medidas_extraidas: str = ""
    altura_cm: Optional[float] = None
    largura_cm: Optional[float] = None
    medida_proxima_ou_menor: bool = False
    sem_medidas: bool = False

    maior_dimensao_mm: Optional[float] = None
    altura_mm: Optional[float] = None
    largura_mm: Optional[float] = None
    comprimento_mm: Optional[float] = None

    def as_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "categoria_print": self.categoria_print,
            "motivo": "; ".join(self.motivos),
            "evidencias": "; ".join(self.evidencias),
            "codigo_anatel": self.codigo_anatel,
            "tela_extraida": self.tela_extraida,
            "tela_polegadas": self.tela_polegadas,
            "tela_mini": self.tela_mini,
            "tela_suspeita": self.tela_suspeita,
            "tela_grande": self.tela_grande,
            "eh_mini_celular": self.eh_mini_celular,
            "eh_acessorio": self.eh_acessorio,
            "sem_tela": self.sem_tela,
            "regra_classificacao": self.regra_classificacao,
            "medidas_extraidas": self.medidas_extraidas,
            "altura_cm": self.altura_cm,
            "largura_cm": self.largura_cm,
            "medida_proxima_ou_menor": self.medida_proxima_ou_menor,
            "sem_medidas": self.sem_medidas,
            "maior_dimensao_mm": self.maior_dimensao_mm,
            "altura_mm": self.altura_mm,
            "largura_mm": self.largura_mm,
            "comprimento_mm": self.comprimento_mm,
        }


def normalizar_texto(valor: Any) -> str:
    if valor is None:
        return ""
    texto = str(valor).replace("\xa0", " ").replace("\u200b", " ")
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()


def contem_termo(texto_lower: str, termos: List[str]) -> List[str]:
    return [termo for termo in termos if termo.lower() in texto_lower]


def _parse_numero(num: str) -> float:
    return float(num.replace(",", "."))


def _formatar_num(valor: float) -> str:
    valor = round(float(valor), 2)
    if valor.is_integer():
        return str(int(valor))
    return str(valor).replace(".", ",")


def _para_mm(valor: float, unidade: str) -> float:
    unidade = unidade.lower().strip()
    if unidade in ["cm", "centimetro", "centimetros", "centímetro", "centímetros"]:
        return valor * 10.0
    return valor


def extrair_codigo_anatel(texto: str) -> str:
    texto = normalizar_texto(texto)
    for padrao in PADROES_ANATEL:
        for match in padrao.finditer(texto):
            codigo = re.sub(r"\D", "", match.group(1))
            if 8 <= len(codigo) <= 13:
                return codigo
    return ""


def _contexto_match(texto: str, inicio: int, fim: int, margem: int = 85) -> str:
    ini = max(0, inicio - margem)
    fim2 = min(len(texto), fim + margem)
    return normalizar_texto(texto[ini:fim2])


def _contexto_eh_dimensao_fisica(contexto_lower: str) -> bool:
    termos_dimensao = [
        "tamanho do produto", "dimensão", "dimensao", "dimensões", "dimensoes",
        "altura", "largura", "profundidade", "comprimento", "peso", "embalagem",
        "package", "dimension", "dimensions", "height", "width", "length", "l x w x h",
    ]
    return any(t in contexto_lower for t in termos_dimensao)


def extrair_tela_polegadas(*textos: str) -> Tuple[str, Optional[float], bool, bool, bool]:
    numero = r"(\d{1,2}(?:[\.,]\d{1,2})?)"
    unidade = r"(?:\"|''|polegadas?|pol\.?|inch|inches|in\.?)"
    padroes = [
        re.compile(rf"(?:tamanho\s+da\s+tela|tela|display|visor|screen|touchscreen|lcd)[^\d]{{0,45}}{numero}\s*{unidade}", re.IGNORECASE),
    ]
    for texto in textos:
        texto_norm = normalizar_texto(texto)
        if not texto_norm:
            continue
        for padrao in padroes:
            m = padrao.search(texto_norm)
            if m:
                try:
                    val = _parse_numero(m.group(1))
                    return m.group(0), val, val <= 3.0, 3.0 < val <= 3.5, val > 3.5
                except Exception:
                    pass
    return "", None, False, False, False


def _parece_medida_valida(valores_mm: List[float]) -> bool:
    if not valores_mm:
        return False
    maior = max(valores_mm)
    menor = min(valores_mm)
    if maior < 40 or maior > 260:
        return False
    if len(valores_mm) >= 3 and menor < 3:
        return False
    return True


def _extrair_dimensoes_grupo(texto: str, prioridade: int) -> List[Dict[str, Any]]:
    candidatos: List[Dict[str, Any]] = []
    numero = r"(\d{1,3}(?:[\.,]\d{1,2})?)"
    sep = r"\s*(?:x|X|×|\*)\s*"
    unidade = r"(mm|mil[ií]metros?|cm|cent[ií]metros?)"

    padrao = re.compile(rf"{numero}{sep}{numero}(?:{sep}{numero})?\s*{unidade}\b", re.IGNORECASE)

    for m in padrao.finditer(texto):
        nums = [m.group(1), m.group(2)]
        if m.group(4):
            nums.append(m.group(3))
            unidade_txt = m.group(4)
        else:
            unidade_txt = m.group(3)

        try:
            valores_mm = [_para_mm(_parse_numero(n), unidade_txt) for n in nums]
        except Exception:
            continue

        contexto = _contexto_match(texto, m.start(), m.end(), margem=100)
        if not _parece_medida_valida(valores_mm):
            continue

        maior = round(max(valores_mm), 2)
        valores_ordenados = sorted(valores_mm, reverse=True)

        candidatos.append({
            "prioridade": prioridade,
            "posicao": m.start(),
            "trecho": contexto,
            "maior_dimensao_mm": maior,
            "altura_mm": round(valores_ordenados[0], 2) if valores_ordenados else None,
            "largura_mm": round(valores_ordenados[1], 2) if len(valores_ordenados) >= 2 else None,
            "comprimento_mm": round(valores_ordenados[0], 2) if valores_ordenados else None,
            "valores_mm": [round(v, 2) for v in valores_mm],
        })
    return candidatos


def _extrair_dimensoes_rotuladas(texto: str, prioridade: int) -> List[Dict[str, Any]]:
    candidatos: List[Dict[str, Any]] = []
    numero = r"(\d{1,3}(?:[\.,]\d{1,2})?)"
    unidade = r"(mm|mil[ií]metros?|cm|cent[ií]metros?)"

    padrao = re.compile(rf"\b(altura|comprimento|profundidade|height|length|largura|width)\b[^\d]{{0,35}}{numero}\s*{unidade}\b", re.IGNORECASE)

    encontrados: Dict[str, float] = {}
    contexto_unificado: List[str] = []
    primeira_pos = 10**9

    for m in padrao.finditer(texto):
        rotulo = m.group(1).lower()
        try:
            valor_mm = _para_mm(_parse_numero(m.group(2)), m.group(3))
        except Exception:
            continue

        if not (3 <= valor_mm <= 260):
            continue

        primeira_pos = min(primeira_pos, m.start())
        contexto_unificado.append(_contexto_match(texto, m.start(), m.end(), margem=60))

        if rotulo in ["altura", "height"]:
            encontrados["altura_mm"] = round(valor_mm, 2)
        elif rotulo in ["comprimento", "profundidade", "length"]:
            encontrados["comprimento_mm"] = round(valor_mm, 2)
        elif rotulo in ["largura", "width"]:
            encontrados["largura_mm"] = round(valor_mm, 2)

    dimensoes_principais = [v for k, v in encontrados.items() if v is not None]
    if dimensoes_principais:
        maior = round(max(dimensoes_principais), 2)
        candidatos.append({
            "prioridade": prioridade,
            "posicao": primeira_pos,
            "trecho": " | ".join(contexto_unificado[:4]),
            "maior_dimensao_mm": maior,
            "altura_mm": encontrados.get("altura_mm"),
            "largura_mm": encontrados.get("largura_mm"),
            "comprimento_mm": encontrados.get("comprimento_mm"),
            "valores_mm": list(encontrados.values()),
        })
    return candidatos


def extrair_medida_fisica_mm(*textos: str) -> Dict[str, Any]:
    candidatos: List[Dict[str, Any]] = []
    for prioridade, texto in enumerate(textos):
        texto_norm = normalizar_texto(texto)
        if not texto_norm:
            continue
        candidatos.extend(_extrair_dimensoes_grupo(texto_norm, prioridade))
        candidatos.extend(_extrair_dimensoes_rotuladas(texto_norm, prioridade))

    if not candidatos:
        return {"medidas_extraidas": "", "maior_dimensao_mm": None, "altura_mm": None, "largura_mm": None, "comprimento_mm": None}

    candidatos.sort(key=lambda c: (c["prioridade"], c["posicao"], c["maior_dimensao_mm"]))
    melhor = candidatos[0]
    return {
        "medidas_extraidas": melhor["trecho"],
        "maior_dimensao_mm": melhor["maior_dimensao_mm"],
        "altura_mm": melhor.get("altura_mm"),
        "largura_mm": melhor.get("largura_mm"),
        "comprimento_mm": melhor.get("comprimento_mm"),
    }


def _classificacao_base(*, status: str, categoria_print: str, motivos: List[str], evidencias: List[str], codigo_anatel: str,
                        tela_txt: str, tela_pol: Optional[float], tela_mini: bool, tela_suspeita: bool, tela_grande: bool,
                        eh_mini_celular: bool, eh_acessorio: bool, sem_tela: bool, regra: str, medidas_extraidas: str = "",
                        maior_dimensao_mm: Optional[float] = None, altura_mm: Optional[float] = None, largura_mm: Optional[float] = None,
                        comprimento_mm: Optional[float] = None) -> Classificacao:
    altura_cm = round(altura_mm / 10, 2) if altura_mm is not None else None
    largura_cm = round(largura_mm / 10, 2) if largura_mm is not None else None

    return Classificacao(
        status=status,
        categoria_print=categoria_print,
        motivos=motivos,
        evidencias=sorted(set(evidencias), key=evidencias.index),
        codigo_anatel=codigo_anatel,
        tela_extraida=tela_txt,
        tela_polegadas=tela_pol,
        tela_mini=tela_mini,
        tela_suspeita=tela_suspeita,
        tela_grande=tela_grande,
        eh_mini_celular=eh_mini_celular,
        eh_acessorio=eh_acessorio,
        sem_tela=sem_tela,
        regra_classificacao=regra,
        medidas_extraidas=medidas_extraidas,
        altura_cm=altura_cm,
        largura_cm=largura_cm,
        medida_proxima_ou_menor=bool(altura_mm is not None and altura_mm <= LIMITE_ALTURA_MAX_MM + MARGEM_SUSPEITA_MM),
        sem_medidas=altura_mm is None and largura_mm is None,
        maior_dimensao_mm=maior_dimensao_mm,
        altura_mm=altura_mm,
        largura_mm=largura_mm,
        comprimento_mm=comprimento_mm,
    )


def classificar_produto(produto: Dict[str, Any]) -> Classificacao:
    titulo = normalizar_texto(produto.get("titulo"))
    texto_card = normalizar_texto(produto.get("texto_card"))
    detalhes = normalizar_texto(produto.get("detalhes"))
    ficha_tecnica = normalizar_texto(produto.get("ficha_tecnica"))
    texto_produto = normalizar_texto(produto.get("texto_pagina"))

    texto_focado = " ".join([titulo, texto_card, detalhes, ficha_tecnica])
    texto_focado_lower = texto_focado.lower()
    titulo_lower = titulo.lower()
    texto_completo = " ".join([texto_focado, texto_produto[:15000]])

    termos_tel = contem_termo(texto_focado_lower, TERMOS_TELEFONIA)
    termos_tel_forte = contem_termo(texto_focado_lower, TERMOS_TELEFONIA_FORTE)
    termos_acessorio = contem_termo(titulo_lower, TERMOS_ACESSORIO)
    termos_brinquedo = contem_termo(texto_focado_lower, TERMOS_BRINQUEDO)
    termos_aparelho_no_titulo = contem_termo(titulo_lower, ["dual chip", "dois chips", "2 chips", "chip", "sim card", "gsm", "celular", "smartphone", "telefone"])

    codigo_anatel = extrair_codigo_anatel(texto_completo)
    tela_txt, tela_pol, tela_mini, tela_suspeita, tela_grande = extrair_tela_polegadas(texto_focado, ficha_tecnica)

    medida = extrair_medida_fisica_mm(texto_focado, ficha_tecnica, detalhes, texto_produto[:12000])
    medidas_extraidas = medida["medidas_extraidas"]
    maior_dimensao_mm = medida["maior_dimensao_mm"]
    altura_mm = medida["altura_mm"] or maior_dimensao_mm
    largura_mm = medida["largura_mm"]
    comprimento_mm = medida["comprimento_mm"]

    if bool(termos_acessorio) and not termos_aparelho_no_titulo:
        return _classificacao_base(
            status="DESCARTADO", categoria_print="", motivos=["Produto aparenta ser acessório/peça."],
            evidencias=termos_acessorio[:6], codigo_anatel=codigo_anatel, tela_txt=tela_txt, tela_pol=tela_pol,
            tela_mini=tela_mini, tela_suspeita=tela_suspeita, tela_grande=tela_grande, eh_mini_celular=False,
            eh_acessorio=True, sem_tela=tela_pol is None, regra="acessorio_descartado", medidas_extraidas=medidas_extraidas,
            maior_dimensao_mm=maior_dimensao_mm, altura_mm=altura_mm, largura_mm=largura_mm, comprimento_mm=comprimento_mm
        )

    if bool(termos_brinquedo) and not termos_tel_forte:
        return _classificacao_base(
            status="DESCARTADO", categoria_print="", motivos=["Produto aparenta ser brinquedo sem indício real de telefonia."],
            evidencias=termos_brinquedo[:6], codigo_anatel=codigo_anatel, tela_txt=tela_txt, tela_pol=tela_pol,
            tela_mini=tela_mini, tela_suspeita=tela_suspeita, tela_grande=tela_grande, eh_mini_celular=False,
            eh_acessorio=False, sem_tela=tela_pol is None, regra="brinquedo_descartado", medidas_extraidas=medidas_extraidas,
            maior_dimensao_mm=maior_dimensao_mm, altura_mm=altura_mm, largura_mm=largura_mm, comprimento_mm=comprimento_mm
        )

    if not termos_tel:
        return _classificacao_base(
            status="DESCARTADO", categoria_print="", motivos=["Sem indício suficiente de celular/telefone com chip."],
            evidencias=[], codigo_anatel=codigo_anatel, tela_txt=tela_txt, tela_pol=tela_pol, tela_mini=tela_mini,
            tela_suspeita=tela_suspeita, tela_grande=tela_grande, eh_mini_celular=False, eh_acessorio=False,
            sem_tela=tela_pol is None, regra="sem_telefonia", medidas_extraidas=medidas_extraidas,
            maior_dimensao_mm=maior_dimensao_mm, altura_mm=altura_mm, largura_mm=largura_mm, comprimento_mm=comprimento_mm
        )

    evidencias: List[str] = []
    if medidas_extraidas:
        evidencias.append(f"Medida capturada: {medidas_extraidas}")
    evidencias.extend(termos_tel[:8])
    if codigo_anatel:
        evidencias.append(f"ANATEL: {codigo_anatel}")

    # Se não encontrou medidas físicas
    if altura_mm is None and largura_mm is None:
        return _classificacao_base(
            status="REVISAR", categoria_print="suspeitos",
            motivos=["Aparelho celular localizado, mas a medida física não foi capturada automaticamente."],
            evidencias=evidencias, codigo_anatel=codigo_anatel, tela_txt=tela_txt, tela_pol=tela_pol,
            tela_mini=False, tela_suspeita=False, tela_grande=False, eh_mini_celular=False, eh_acessorio=False,
            sem_tela=tela_pol is None, regra="celular_sem_medida_fisica_localizada", medidas_extraidas="",
            maior_dimensao_mm=None, altura_mm=None, largura_mm=None, comprimento_mm=None
        )

    # Aplicação da Nova Regra: Altura <= 120mm E Largura <= 55mm (ou equivalente se faltar largura)
    atende_altura = altura_mm <= LIMITE_ALTURA_MAX_MM
    atende_largura = largura_mm is None or largura_mm <= LIMITE_LARGURA_MAX_MM

    if atende_altura and atende_largura:
        motivos = [f"Dimensões dentro do limite de mini celular: Altura <= {LIMITE_ALTURA_MAX_MM} mm e Largura <= {LIMITE_LARGURA_MAX_MM} mm."]
        if not codigo_anatel:
            motivos.append("Código ANATEL não identificado no anúncio.")
        return _classificacao_base(
            status="IRREGULAR", categoria_print="irregulares/mini_celular_12x55cm",
            motivos=motivos, evidencias=evidencias, codigo_anatel=codigo_anatel, tela_txt=tela_txt, tela_pol=tela_pol,
            tela_mini=True, tela_suspeita=False, tela_grande=False, eh_mini_celular=True, eh_acessorio=False,
            sem_tela=tela_pol is None, regra="dimensao_inferior_12x55cm_irregular", medidas_extraidas=medidas_extraidas,
            maior_dimensao_mm=maior_dimensao_mm, altura_mm=altura_mm, largura_mm=largura_mm, comprimento_mm=comprimento_mm
        )

    # Faixa Suspeita (pouco acima do limite até a margem)
    if altura_mm <= LIMITE_ALTURA_MAX_MM + MARGEM_SUSPEITA_MM:
        return _classificacao_base(
            status="SUSPEITO", categoria_print="suspeitos",
            motivos=[f"Dimensões ligeiramente acima do limite de mini celular (Altura: {altura_mm} mm)."],
            evidencias=evidencias, codigo_anatel=codigo_anatel, tela_txt=tela_txt, tela_pol=tela_pol,
            tela_mini=False, tela_suspeita=True, tela_grande=False, eh_mini_celular=False, eh_acessorio=False,
            sem_tela=tela_pol is None, regra="dimensao_suspeita", medidas_extraidas=medidas_extraidas,
            maior_dimensao_mm=maior_dimensao_mm, altura_mm=altura_mm, largura_mm=largura_mm, comprimento_mm=comprimento_mm
        )

    # Descartado por ser maior que o limite estipulado
    return _classificacao_base(
        status="DESCARTADO", categoria_print="",
        motivos=[f"Dimensões acima do limite máximo estabelecido (Altura: {altura_mm} mm)."],
        evidencias=evidencias, codigo_anatel=codigo_anatel, tela_txt=tela_txt, tela_pol=tela_pol,
        tela_mini=False, tela_suspeita=False, tela_grande=True, eh_mini_celular=False, eh_acessorio=False,
        sem_tela=tela_pol is None, regra="dimensao_acima_limite", medidas_extraidas=medidas_extraidas,
        maior_dimensao_mm=maior_dimensao_mm, altura_mm=altura_mm, largura_mm=largura_mm, comprimento_mm=comprimento_mm
    )

# [Mantenha todos os imports, constantes e funções até a classificar_produto]

def classificar_produto(produto: Dict[str, Any], anatel_info: Dict[str, Any] = None) -> Classificacao:
    if anatel_info is None:
        anatel_info = {}
        
    titulo = normalizar_texto(produto.get("titulo"))
    texto_card = normalizar_texto(produto.get("texto_card"))
    detalhes = normalizar_texto(produto.get("detalhes"))
    ficha_tecnica = normalizar_texto(produto.get("ficha_tecnica"))
    texto_produto = normalizar_texto(produto.get("texto_pagina"))

    texto_focado = " ".join([titulo, texto_card, detalhes, ficha_tecnica])
    texto_focado_lower = texto_focado.lower()
    titulo_lower = titulo.lower()
    texto_completo = " ".join([texto_focado, texto_produto[:15000]])

    termos_tel = contem_termo(texto_focado_lower, TERMOS_TELEFONIA)
    termos_tel_forte = contem_termo(texto_focado_lower, TERMOS_TELEFONIA_FORTE)
    termos_acessorio = contem_termo(titulo_lower, TERMOS_ACESSORIO)
    termos_brinquedo = contem_termo(texto_focado_lower, TERMOS_BRINQUEDO)
    termos_aparelho_no_titulo = contem_termo(titulo_lower, ["dual chip", "dois chips", "2 chips", "chip", "sim card", "gsm", "celular", "smartphone", "telefone"])

    codigo_anatel = produto.get("codigo_anatel_principal") or extrair_codigo_anatel(texto_completo)
    tela_txt, tela_pol, tela_mini, tela_suspeita, tela_grande = extrair_tela_polegadas(texto_focado, ficha_tecnica)

    medida = extrair_medida_fisica_mm(texto_focado, ficha_tecnica, detalhes, texto_produto[:12000])
    medidas_extraidas = medida["medidas_extraidas"]
    maior_dimensao_mm = medida["maior_dimensao_mm"]
    altura_mm = medida["altura_mm"] or maior_dimensao_mm
    largura_mm = medida["largura_mm"]
    comprimento_mm = medida["comprimento_mm"]

    if bool(termos_acessorio) and not termos_aparelho_no_titulo:
        return _classificacao_base(
            status="DESCARTADO", categoria_print="", motivos=["Produto aparenta ser acessório/peça."],
            evidencias=termos_acessorio[:6], codigo_anatel=codigo_anatel, tela_txt=tela_txt, tela_pol=tela_pol,
            tela_mini=tela_mini, tela_suspeita=tela_suspeita, tela_grande=tela_grande, eh_mini_celular=False,
            eh_acessorio=True, sem_tela=tela_pol is None, regra="acessorio_descartado", medidas_extraidas=medidas_extraidas,
            maior_dimensao_mm=maior_dimensao_mm, altura_mm=altura_mm, largura_mm=largura_mm, comprimento_mm=comprimento_mm
        )

    if bool(termos_brinquedo) and not termos_tel_forte:
        return _classificacao_base(
            status="DESCARTADO", categoria_print="", motivos=["Produto aparenta ser brinquedo sem indício real de telefonia."],
            evidencias=termos_brinquedo[:6], codigo_anatel=codigo_anatel, tela_txt=tela_txt, tela_pol=tela_pol,
            tela_mini=tela_mini, tela_suspeita=tela_suspeita, tela_grande=tela_grande, eh_mini_celular=False,
            eh_acessorio=False, sem_tela=tela_pol is None, regra="brinquedo_descartado", medidas_extraidas=medidas_extraidas,
            maior_dimensao_mm=maior_dimensao_mm, altura_mm=altura_mm, largura_mm=largura_mm, comprimento_mm=comprimento_mm
        )

    if not termos_tel:
        return _classificacao_base(
            status="DESCARTADO", categoria_print="", motivos=["Sem indício suficiente de celular/telefone com chip."],
            evidencias=[], codigo_anatel=codigo_anatel, tela_txt=tela_txt, tela_pol=tela_pol, tela_mini=tela_mini,
            tela_suspeita=tela_suspeita, tela_grande=tela_grande, eh_mini_celular=False, eh_acessorio=False,
            sem_tela=tela_pol is None, regra="sem_telefonia", medidas_extraidas=medidas_extraidas,
            maior_dimensao_mm=maior_dimensao_mm, altura_mm=altura_mm, largura_mm=largura_mm, comprimento_mm=comprimento_mm
        )

    evidencias: List[str] = []
    if medidas_extraidas:
        evidencias.append(f"Medida capturada: {medidas_extraidas}")
    evidencias.extend(termos_tel[:8])
    if codigo_anatel:
        evidencias.append(f"ANATEL: {codigo_anatel}")

    if altura_mm is None and largura_mm is None:
        return _classificacao_base(
            status="REVISAR", categoria_print="suspeitos",
            motivos=["Aparelho celular localizado, mas a medida física não foi capturada automaticamente."],
            evidencias=evidencias, codigo_anatel=codigo_anatel, tela_txt=tela_txt, tela_pol=tela_pol,
            tela_mini=False, tela_suspeita=False, tela_grande=False, eh_mini_celular=False, eh_acessorio=False,
            sem_tela=tela_pol is None, regra="celular_sem_medida_fisica_localizada", medidas_extraidas="",
            maior_dimensao_mm=None, altura_mm=None, largura_mm=None, comprimento_mm=None
        )

    atende_altura = altura_mm <= LIMITE_ALTURA_MAX_MM
    atende_largura = largura_mm is None or largura_mm <= LIMITE_LARGURA_MAX_MM

    if atende_altura and atende_largura:
        anatel_em_ordem = (anatel_info.get("anatel_em_ordem") == "SIM")
        status_req = anatel_info.get("situacao_requerimento_normalizada")

        if status_req in {"CANCELADA", "SUSPENSA"}:
            motivos = [f"Dimensões de mini celular, mas homologação consta como {status_req} na Anatel."]
            return _classificacao_base(
                status="IRREGULAR", categoria_print="irregulares",
                motivos=motivos, evidencias=evidencias, codigo_anatel=codigo_anatel, tela_txt=tela_txt, tela_pol=tela_pol,
                tela_mini=True, tela_suspeita=False, tela_grande=False, eh_mini_celular=True, eh_acessorio=False,
                sem_tela=tela_pol is None, regra="homologacao_suspensa_cancelada", medidas_extraidas=medidas_extraidas,
                maior_dimensao_mm=maior_dimensao_mm, altura_mm=altura_mm, largura_mm=largura_mm, comprimento_mm=comprimento_mm
            )
            
        if anatel_em_ordem:
            motivos = ["Dimensões dentro do limite, porém o código Anatel, a marca e o modelo estão em conformidade com a base."]
            return _classificacao_base(
                status="DESCARTADO", categoria_print="",
                motivos=motivos, evidencias=evidencias, codigo_anatel=codigo_anatel, tela_txt=tela_txt, tela_pol=tela_pol,
                tela_mini=True, tela_suspeita=False, tela_grande=False, eh_mini_celular=True, eh_acessorio=False,
                sem_tela=tela_pol is None, regra="anatel_em_ordem", medidas_extraidas=medidas_extraidas,
                maior_dimensao_mm=maior_dimensao_mm, altura_mm=altura_mm, largura_mm=largura_mm, comprimento_mm=comprimento_mm
            )

        motivos = [f"Dimensões dentro do limite de mini celular: Altura <= {LIMITE_ALTURA_MAX_MM} mm e Largura <= {LIMITE_LARGURA_MAX_MM} mm."]
        if not anatel_info.get("codigo_anatel_normalizado"):
            motivos.append("Código Anatel não identificado ou irregular.")
            
        return _classificacao_base(
            status="IRREGULAR", categoria_print="irregulares",
            motivos=motivos, evidencias=evidencias, codigo_anatel=codigo_anatel, tela_txt=tela_txt, tela_pol=tela_pol,
            tela_mini=True, tela_suspeita=False, tela_grande=False, eh_mini_celular=True, eh_acessorio=False,
            sem_tela=tela_pol is None, regra="dimensao_inferior_12x55cm_irregular", medidas_extraidas=medidas_extraidas,
            maior_dimensao_mm=maior_dimensao_mm, altura_mm=altura_mm, largura_mm=largura_mm, comprimento_mm=comprimento_mm
        )

    if altura_mm <= LIMITE_ALTURA_MAX_MM + MARGEM_SUSPEITA_MM:
        return _classificacao_base(
            status="SUSPEITO", categoria_print="suspeitos",
            motivos=[f"Dimensões ligeiramente acima do limite de mini celular (Altura: {altura_mm} mm)."],
            evidencias=evidencias, codigo_anatel=codigo_anatel, tela_txt=tela_txt, tela_pol=tela_pol,
            tela_mini=False, tela_suspeita=True, tela_grande=False, eh_mini_celular=False, eh_acessorio=False,
            sem_tela=tela_pol is None, regra="dimensao_suspeita", medidas_extraidas=medidas_extraidas,
            maior_dimensao_mm=maior_dimensao_mm, altura_mm=altura_mm, largura_mm=largura_mm, comprimento_mm=comprimento_mm
        )

    return _classificacao_base(
        status="DESCARTADO", categoria_print="",
        motivos=[f"Dimensões acima do limite máximo estabelecido (Altura: {altura_mm} mm)."],
        evidencias=evidencias, codigo_anatel=codigo_anatel, tela_txt=tela_txt, tela_pol=tela_pol,
        tela_mini=False, tela_suspeita=False, tela_grande=True, eh_mini_celular=False, eh_acessorio=False,
        sem_tela=tela_pol is None, regra="dimensao_acima_limite", medidas_extraidas=medidas_extraidas,
        maior_dimensao_mm=maior_dimensao_mm, altura_mm=altura_mm, largura_mm=largura_mm, comprimento_mm=comprimento_mm
    )