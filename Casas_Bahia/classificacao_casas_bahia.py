# -*- coding: utf-8 -*-
"""
Regras de classificação para o crawler Casas Bahia baseadas em altura e largura.

Regra operacional:
- Aparelho celular com altura <= 120 mm (12 cm) E largura <= 55 mm (5,5 cm) = IRREGULAR (Mini Celular);
- Aparelho celular com medidas próximas acima desses limites = SUSPEITO;
- Aparelho celular acima dos limites ou sem medidas sem indício forte = DESCARTADO.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


LIMITE_ALTURA_MM = 120.0  # 12 cm
LIMITE_LARGURA_MM = 55.0  # 5,5 cm
LIMITE_SUSPEITA_ALTURA_MM = 130.0
LIMITE_SUSPEITA_LARGURA_MM = 65.0

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
    altura_mm: Optional[float] = None
    largura_mm: Optional[float] = None

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
            "altura_mm": self.altura_mm,
            "largura_mm": self.largura_mm,
        }


def normalizar_texto(valor: Any) -> str:
    if valor is None:
        return ""
    texto = str(valor).replace("\xa0", " ").replace("\u200b", " ")
    return re.sub(r"\s+", " ", texto).strip()


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


def extrair_medida_fisica_mm(*textos: str) -> Dict[str, Any]:
    candidatos: List[Dict[str, Any]] = []
    
    numero = r"(\d{1,3}(?:[\.,]\d{1,2})?)"
    sep = r"\s*(?:x|X|×|\*)\s*"
    unidade = r"(mm|mil[ií]metros?|cm|cent[ií]metros?)"
    padrao_triplo = re.compile(rf"{numero}{sep}{numero}{sep}{numero}\s*{unidade}\b", re.IGNORECASE)
    padrao_duplo = re.compile(rf"{numero}{sep}{numero}\s*{unidade}\b", re.IGNORECASE)

    for prioridade, texto in enumerate(textos):
        texto_norm = normalizar_texto(texto)
        if not texto_norm:
            continue

        # Tenta capturar dimensões no formato Altura x Largura x Espessura ou Altura x Largura
        for padrao in [padrao_triplo, padrao_duplo]:
            for m in padrao.finditer(texto_norm):
                try:
                    g = m.groups()
                    nums = [g[0], g[1]]
                    unidade_txt = g[-1]
                    valores_mm = [_para_mm(_parse_numero(n), unidade_txt) for n in nums]
                    
                    # Ordena do maior para o menor para identificar altura e largura com precisão
                    v_ordenados = sorted(valores_mm, reverse=True)
                    altura = v_ordenados[0]
                    largura = v_ordenados[1] if len(v_ordenados) > 1 else None

                    if 30 <= altura <= 300:
                        candidatos.append({
                            "prioridade": prioridade,
                            "posicao": m.start(),
                            "trecho": _contexto_match(texto_norm, m.start(), m.end(), 100),
                            "altura_mm": round(altura, 2),
                            "largura_mm": round(largura, 2) if largura else None,
                        })
                except Exception:
                    continue

        # Tenta capturar dimensões rotuladas (ex: Altura: 12 cm, Largura: 5 cm)
        padrao_rotulo = re.compile(
            rf"\b(altura|largura|comprimento|height|width|length)\b[^\d\|]{{0,30}}{numero}\s*({unidade})\b",
            re.IGNORECASE,
        )
        alt_rot, larg_rot = None, None
        trechos_rot = []
        pos_rot = 10**9
        for m in padrao_rotulo.finditer(texto_norm):
            pos_rot = min(pos_rot, m.start())
            try:
                val = _para_mm(_parse_numero(m.group(2)), m.group(3))
                rot = m.group(1).lower()
                trechos_rot.append(_contexto_match(texto_norm, m.start(), m.end(), 60))
                if rot in ["altura", "height", "comprimento", "length"]:
                    alt_rot = round(val, 2)
                elif rot in ["largura", "width"]:
                    larg_rot = round(val, 2)
            except Exception:
                continue
        
        if alt_rot or larg_rot:
            candidatos.append({
                "prioridade": prioridade,
                "posicao": pos_rot,
                "trecho": " | ".join(trechos_rot),
                "altura_mm": alt_rot,
                "largura_mm": larg_rot,
            })

    if not candidatos:
        return {"medidas_extraidas": "", "altura_mm": None, "largura_mm": None}

    candidatos.sort(key=lambda c: (c["prioridade"], c["posicao"]))
    melhor = candidatos[0]
    return {
        "medidas_extraidas": melhor["trecho"],
        "altura_mm": melhor.get("altura_mm"),
        "largura_mm": melhor.get("largura_mm"),
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
    termos_aparelho_no_titulo = contem_termo(
        titulo_lower,
        ["dual chip", "dois chips", "2 chips", "chip", "sim card", "gsm", "2g", "3g", "4g", "5g", "lte", "telefone", "celular simples", "telefone celular", "flip phone", "tijolinho", "feature phone"],
    )

    codigo_anatel = extrair_codigo_anatel(texto_completo)
    medida = extrair_medida_fisica_mm(texto_focado, texto_produto[:12000])
    
    medidas_extraidas = medida["medidas_extraidas"]
    altura_mm = medida["altura_mm"]
    largura_mm = medida["largura_mm"]

    tem_indicio_telefonia = bool(termos_tel)
    eh_acessorio = bool(termos_acessorio) and not termos_aparelho_no_titulo
    eh_brinquedo_sem_telefonia = bool(termos_brinquedo) and not termos_tel_forte

    common = dict(
        codigo_anatel=codigo_anatel,
        sem_tela=False,
        medidas_extraidas=medidas_extraidas,
        altura_mm=altura_mm,
        largura_mm=largura_mm,
        altura_cm=round(altura_mm / 10, 2) if altura_mm else None,
        largura_cm=round(largura_mm / 10, 2) if largura_mm else None,
    )

    if termos_fora_escopo and not termos_tel:
        return Classificacao(
            status="DESCARTADO",
            categoria_print="",
            motivos=["Produto fora do escopo de telefonia."],
            evidencias=termos_fora_escopo[:6],
            regra_classificacao="fora_escopo_descartado",
            **common,
        )

    if eh_acessorio:
        return Classificacao(status="DESCARTADO", categoria_print="", motivos=["Produto aparenta ser acessório/peça."], evidencias=termos_acessorio[:6], eh_acessorio=True, regra_classificacao="acessorio_descartado", **common)
    if eh_brinquedo_sem_telefonia:
        return Classificacao(status="DESCARTADO", categoria_print="", motivos=["Produto aparenta ser brinquedo sem chip."], evidencias=termos_brinquedo[:6], regra_classificacao="brinquedo_descartado", **common)
    if not tem_indicio_telefonia:
        return Classificacao(status="DESCARTADO", categoria_print="", motivos=["Sem indício suficiente de celular/telefone."], regra_classificacao="sem_telefonia", **common)

    evidencias: List[str] = []
    if medidas_extraidas:
        evidencias.append(f"Medida capturada: {medidas_extraidas}")
    evidencias.extend(termos_tel[:8])
    if codigo_anatel:
        evidencias.append(f"ANATEL: {codigo_anatel}")

    # Sem medidas físicas explícitas
    if altura_mm is None and largura_mm is None:
        if termos_indicio_mini:
            evidencias.extend(termos_indicio_mini[:6])
            return Classificacao(
                status="SUSPEITO",
                categoria_print="suspeitos",
                motivos=["Medida não localizada, mas há indício forte de mini celular."],
                evidencias=evidencias,
                regra_classificacao="sem_medida_com_indicio_mini",
                sem_medidas=True,
                **common,
            )
        return Classificacao(
            status="DESCARTADO",
            categoria_print="",
            motivos=["Celular sem medida física e sem indício de mini celular."],
            evidencias=evidencias,
            regra_classificacao="sem_medida_sem_indicio_descartado",
            sem_medidas=True,
            **common,
        )

    # Validação rigorosa dos limites especificados (Altura <= 120 mm E Largura <= 55 mm)
    atende_altura = altura_mm is None or altura_mm <= LIMITE_ALTURA_MM
    atende_largura = largura_mm is None or largura_mm <= LIMITE_LARGURA_MM

    if atende_altura and atende_largura:
        motivos = [f"Dimensões dentro do limite de mini celular (Altura: {_formatar_num(altura_mm or 0)} mm, Largura: {_formatar_num(largura_mm or 0)} mm)."]
        if not codigo_anatel:
            motivos.append("Código ANATEL não identificado.")
        return Classificacao(
            status="IRREGULAR",
            categoria_print="irregulares/mini_celular",
            motivos=motivos,
            evidencias=evidencias,
            eh_mini_celular=True,
            regra_classificacao="dimensoes_mini_celular_validas",
            **common,
        )

    # Validação de faixa suspeita (próximo ao limite)
    atende_suspeita_alt = altura_mm is None or altura_mm <= LIMITE_SUSPEITA_ALTURA_MM
    atende_suspeita_larg = largura_mm is None or largura_mm <= LIMITE_SUSPEITA_LARGURA_MM

    if atende_suspeita_alt and atende_suspeita_larg:
        return Classificacao(
            status="SUSPEITO",
            categoria_print="suspeitos",
            motivos=[f"Dimensões próximas ao limite superior (Altura: {_formatar_num(altura_mm or 0)} mm, Largura: {_formatar_num(largura_mm or 0)} mm)."],
            evidencias=evidencias,
            regra_classificacao="dimensoes_proximas_suspeito",
            **common,
        )

    return Classificacao(
        status="DESCARTADO",
        categoria_print="",
        motivos=[f"Dimensões acima do limite máximo permitido (Altura: {_formatar_num(altura_mm or 0)} mm, Largura: {_formatar_num(largura_mm or 0)} mm)."],
        evidencias=evidencias,
        regra_classificacao="dimensoes_acima_limite",
        **common,
    )