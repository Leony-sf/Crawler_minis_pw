# -*- coding: utf-8 -*-
"""
Regras de classificação para o crawler Carrefour baseadas em dimensões físicas.

Regra operacional ajustada:
- Aparelho celular com altura <= 120 mm (12 cm) E largura <= 55 mm (5,5 cm) = IRREGULAR (Mini Celular);
- Aparelho celular com altura próxima (até 130 mm) ou largura próxima (até 60 mm) = SUSPEITO;
- Aparelho celular sem medida física localizada = DESCARTADO, exceto quando houver indício forte;
- Aparelho celular com dimensões acima dos limites = DESCARTADO.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


# Novos limites configurados: 12 cm de altura e 5,5 cm de largura
LIMITE_ALTURA_IRREGULAR_MM = 120.0  # 12 cm
LIMITE_LARGURA_IRREGULAR_MM = 55.0   # 5,5 cm

LIMITE_ALTURA_SUSPEITA_MM = 130.0   # Margem de suspeita para altura
LIMITE_LARGURA_SUSPEITA_MM = 60.0    # Margem de suspeita para largura

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

TERMOS_INDICIO_FORTE_MINI = [
    "mini celular", "mini telefone", "mini mobile", "mini phone", "mini cellphone",
    "menor celular", "menor telefone", "smallest phone", "tiny phone", "micro celular",
    "card phone", "bluetooth dialer", "discador bluetooth", "ponto eletrônico",
    "telefone espião", "telefone espiao", "fone discador", "headset dialer",
    "l8star", "gtstar", "bm70", "bm30", "bm10", "bm50", "k8 mini",
    "soyes xs", "soyes xs11", "melrose s9x",
]

TERMOS_ACESSORIO = [
    "capa", "capinha", "case", "cover", "película", "pelicula", "vidro temperado",
    "screen protector", "tempered glass", "carregador", "cabo usb", "fonte",
    "bateria", "bateria para", "tela para", "display para", "lcd para",
    "peça", "peca", "peças", "pecas", "conector", "flex", "placa", "suporte",
    "fone de ouvido", "headphone", "headset", "adaptador", "carteira", "bolsa",
]

TERMOS_PRODUTO_FORA_DO_ESCOPO = [
    "chocolate", "amendoim", "amêndoa", "amendoas", "biscoito", "bolacha",
    "leite", "lacta", "garoto", "nestlé", "nestle", "café", "cafe",
    "açúcar", "acucar", "arroz", "feijão", "feijao", "macarrão", "macarrao",
    "molho", "tempero", "salgadinho", "suco", "refrigerante", "vinho",
    "cerveja", "ração", "racao", "shampoo", "condicionador", "sabonete",
    "fralda", "detergente", "desinfetante", "limpador", "desodorante",
    "perfume", "creme dental", "escova dental",
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
    eh_mini_celular: bool = False
    eh_acessorio: bool = False
    sem_tela: bool = False
    regra_classificacao: str = ""
    medidas_extraidas: str = ""
    altura_cm: Optional[float] = None
    largura_cm: Optional[float] = None
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
            "eh_mini_celular": self.eh_mini_celular,
            "eh_acessorio": self.eh_acessorio,
            "sem_tela": self.sem_tela,
            "regra_classificacao": self.regra_classificacao,
            "medidas_extraidas": self.medidas_extraidas,
            "altura_cm": self.altura_cm,
            "largura_cm": self.largura_cm,
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


def extrair_tela_polegadas(*textos: str) -> Tuple[str, Optional[float], bool]:
    numero = r"(\d{1,2}(?:[\.,]\d{1,2})?)"
    unidade = r"(?:\"|''|polegadas?|pol\.?|inch|inches|in\.?)"
    padroes = [
        re.compile(rf"(?:tamanho\s+da\s+tela|tela|display|visor|screen)[^\d]{{0,45}}{numero}\s*{unidade}", re.IGNORECASE),
    ]
    for texto in textos:
        texto_norm = normalizar_texto(texto)
        if not texto_norm:
            continue
        for padrao in padroes:
            for m in padrao.finditer(texto_norm):
                try:
                    valor = _parse_numero(m.group(1))
                    if 0.5 <= valor <= 8.5:
                        return m.group(0), round(valor, 2), False
                except Exception:
                    continue
    return "", None, True


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
        if not valores_mm:
            continue
        valores_ordenados = sorted(valores_mm, reverse=True)
        # Atribui altura como o maior valor e largura como o segundo maior valor do grupo
        altura = valores_ordenados[0]
        largura = valores_ordenados[1] if len(valores_ordenados) >= 2 else valores_ordenados[0]
        candidatos.append({
            "prioridade": prioridade,
            "posicao": m.start(),
            "trecho": _contexto_match(texto, m.start(), m.end(), 100),
            "altura_mm": round(altura, 2),
            "largura_mm": round(largura, 2),
            "maior_dimensao_mm": round(max(valores_mm), 2),
        })
    return candidatos


def _extrair_dimensoes_rotuladas(texto: str, prioridade: int) -> List[Dict[str, Any]]:
    candidatos: List[Dict[str, Any]] = []
    numero = r"(\d{1,3}(?:[\.,]\d{1,2})?)"
    unidade = r"(?:mm|mil[ií]metros?|cm|cent[ií]metros?)"
    encontrados: Dict[str, float] = {}
    contextos: List[str] = []

    padrao = re.compile(
        rf"\b(altura|comprimento|length|largura|width)\b[^\d\|]{{0,45}}?{numero}\s*({unidade})\b",
        re.IGNORECASE,
    )
    for m in padrao.finditer(texto):
        try:
            val = _para_mm(_parse_numero(m.group(2)), m.group(3))
            rot = m.group(1).lower()
            if rot in ["altura", "comprimento", "length"]:
                encontrados["altura_mm"] = round(val, 2)
            elif rot in ["largura", "width"]:
                encontrados["largura_mm"] = round(val, 2)
            contextos.append(_contexto_match(texto, m.start(), m.end(), 80))
        except Exception:
            continue

    if encontrados:
        candidatos.append({
            "prioridade": prioridade,
            "posicao": 0,
            "trecho": " | ".join(contextos),
            "altura_mm": encontrados.get("altura_mm"),
            "largura_mm": encontrados.get("largura_mm"),
            "maior_dimensao_mm": max(encontrados.values()) if encontrados else None,
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
        return {"medidas_extraidas": "", "altura_mm": None, "largura_mm": None, "maior_dimensao_mm": None}
    candidatos.sort(key=lambda c: (c["prioridade"], c["posicao"]))
    melhor = candidatos[0]
    return {
        "medidas_extraidas": melhor["trecho"],
        "altura_mm": melhor.get("altura_mm"),
        "largura_mm": melhor.get("largura_mm"),
        "maior_dimensao_mm": melhor.get("maior_dimensao_mm"),
    }


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

    termos_fora_escopo = contem_termo(texto_focado_lower, TERMOS_PRODUTO_FORA_DO_ESCOPO)
    termos_tel = contem_termo(texto_focado_lower, TERMOS_TELEFONIA)
    termos_tel_forte = contem_termo(texto_focado_lower, TERMOS_TELEFONIA_FORTE)
    termos_indicio_mini = contem_termo(texto_focado_lower, TERMOS_INDICIO_FORTE_MINI)
    termos_acessorio = contem_termo(titulo_lower, TERMOS_ACESSORIO)
    termos_brinquedo = contem_termo(texto_focado_lower, TERMOS_BRINQUEDO)

    codigo_anatel = extrair_codigo_anatel(texto_completo)
    _, tela_pol, sem_tela = extrair_tela_polegadas(texto_focado, ficha_tecnica)
    medida = extrair_medida_fisica_mm(texto_focado, ficha_tecnica, texto_produto[:12000])
    
    medidas_extraidas = medida["medidas_extraidas"]
    altura_mm = medida["altura_mm"]
    largura_mm = medida["largura_mm"]
    maior_dimensao_mm = medida["maior_dimensao_mm"]

    tem_indicio_telefonia = bool(termos_tel)
    eh_acessorio = bool(termos_acessorio) and not any(t in titulo_lower for t in ["chip", "gsm", "celular", "telefone"])
    eh_brinquedo = bool(termos_brinquedo) and not termos_tel_forte

    common = dict(
        codigo_anatel=codigo_anatel,
        tela_polegadas=tela_pol,
        sem_tela=sem_tela,
        medidas_extraidas=medidas_extraidas,
        altura_mm=altura_mm,
        largura_mm=largura_mm,
        maior_dimensao_mm=maior_dimensao_mm,
    )

    if termos_fora_escopo and not termos_tel:
        return Classificacao(status="DESCARTADO", categoria_print="", motivos=["Produto fora do escopo."], eh_acessorio=False, regra_classificacao="fora_escopo", **common)
    if eh_acessorio:
        return Classificacao(status="DESCARTADO", categoria_print="", motivos=["Acessório ou peça."], eh_acessorio=True, regra_classificacao="acessorio", **common)
    if eh_brinquedo:
        return Classificacao(status="DESCARTADO", categoria_print="", motivos=["Brinquedo infantil."], regra_classificacao="brinquedo", **common)
    if not tem_indicio_telefonia:
        return Classificacao(status="DESCARTADO", categoria_print="", motivos=["Sem indício de telefonia."], regra_classificacao="sem_telefonia", **common)

    evidencias = [f"Medida: {medidas_extraidas}"] if medidas_extraidas else []

    if altura_mm is None or largura_mm is None:
        if termos_indicio_mini:
            return Classificacao(
                status="SUSPEITO",
                categoria_print="suspeitos",
                motivos=["Medida não localizada, mas possui indício forte de mini celular."],
                evidencias=termos_indicio_mini,
                regra_classificacao="sem_medida_com_indicio",
                **common
            )
        return Classificacao(status="DESCARTADO", categoria_print="", motivos=["Sem medida física localizada."], regra_classificacao="sem_medida", **common)

    # Verificação estrita dos limites solicitados: Altura <= 120mm e Largura <= 55mm
    if altura_mm <= LIMITE_ALTURA_IRREGULAR_MM and largura_mm <= LIMITE_LARGURA_IRREGULAR_MM:
        motivos = [f"Dimensões dentro do limite de mini celular: Altura {_formatar_num(altura_mm)} mm, Largura {_formatar_num(largura_mm)} mm."]
        return Classificacao(
            status="IRREGULAR",
            categoria_print="irregulares/mini_celular",
            motivos=motivos,
            evidencias=evidencias,
            eh_mini_celular=True,
            regra_classificacao="dentro_limite_mini_celular",
            **common
        )

    # Margem de suspeita caso fiquem ligeiramente acima
    if altura_mm <= LIMITE_ALTURA_SUSPEITA_MM and largura_mm <= LIMITE_LARGURA_SUSPEITA_MM:
        motivos = [f"Dimensões próximas ao limite: Altura {_formatar_num(altura_mm)} mm, Largura {_formatar_num(largura_mm)} mm."]
        return Classificacao(
            status="SUSPEITO",
            categoria_print="suspeitos",
            motivos=motivos,
            evidencias=evidencias,
            regra_classificacao="dimensao_proxima_limite",
            **common
        )

    return Classificacao(
        status="DESCARTADO",
        categoria_print="",
        motivos=[f"Dimensões acima do limite máximo: Altura {_formatar_num(altura_mm)} mm, Largura {_formatar_num(largura_mm)} mm."],
        regra_classificacao="dimensao_acima_limite",
        **common
    )