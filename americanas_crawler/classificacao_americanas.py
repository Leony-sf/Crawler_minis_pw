# -*- coding: utf-8 -*-
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

LIMITE_ALTURA_MM = 120.0
LIMITE_LARGURA_MM = 55.0

TERMOS_TELEFONIA = ["dual sim", "dois chips", "celular", "smartphone", "feature phone", "gsm"]
TERMOS_ACESSORIO = ["capa", "capinha", "película", "carregador", "bateria para", "tela para"]

@dataclass
class Classificacao:
    status: str
    motivos: List[str] = field(default_factory=list)
    evidencias: List[str] = field(default_factory=list)
    maior_dimensao_mm: Optional[float] = None
    altura_mm: Optional[float] = None
    largura_mm: Optional[float] = None
    
    def as_dict(self) -> Dict[str, Any]:
        return {
            "motivo_validacao": "; ".join(self.motivos),
            "maior_dimensao_mm": self.maior_dimensao_mm,
            "altura_mm": self.altura_mm,
            "largura_mm": self.largura_mm,
        }

def _parse_numero(num: str) -> float:
    return float(num.replace(",", "."))

def _para_mm(valor: float, unidade: str) -> float:
    return valor * 10.0 if "cm" in unidade.lower() else valor

def classificar_produto(produto: Dict[str, Any], anatel: Dict[str, Any]) -> Classificacao:
    titulo = str(produto.get("titulo", "")).lower()
    texto = str(produto.get("texto_pagina", "") + " " + titulo).lower()
    
    # Acessórios são checados SOMENTE no título para evitar falsos positivos
    eh_acessorio = any(t in titulo for t in TERMOS_ACESSORIO)
    tem_tel = any(t in texto for t in TERMOS_TELEFONIA)

    if eh_acessorio: return Classificacao(status="DESCARTADO", motivos=["Acessório (detectado pelo título)"])
    if not tem_tel: return Classificacao(status="DESCARTADO", motivos=["Sem indícios de telefonia no texto"])

    altura_mm = produto.get("altura_mm")
    largura_mm = produto.get("largura_mm")
    maior_dimensao_mm = produto.get("maior_dimensao_mm")

    eh_mini = False
    if altura_mm and largura_mm and altura_mm <= LIMITE_ALTURA_MM and largura_mm <= LIMITE_LARGURA_MM:
        eh_mini = True
    elif maior_dimensao_mm and maior_dimensao_mm <= LIMITE_ALTURA_MM:
        eh_mini = True

    if not eh_mini:
        if maior_dimensao_mm is None: return Classificacao(status="SUSPEITO", motivos=["Aparelho celular sem medidas físicas capturadas"])
        return Classificacao(status="DESCARTADO", motivos=[f"Excede o limite dimensional. Maior dimensão: {maior_dimensao_mm}mm"])

    status_anatel = anatel.get("situacao_requerimento_normalizada", "NAO_INFORMADA")
    em_ordem = anatel.get("anatel_em_ordem", "NAO")

    if status_anatel in ["CANCELADA", "SUSPENSA"]:
        return Classificacao(status="IRREGULAR", motivos=["Homologação suspensa/cancelada"], altura_mm=altura_mm, largura_mm=largura_mm)
    elif em_ordem == "SIM":
        return Classificacao(status="DESCARTADO", motivos=["Legalizado com base Anatel"], altura_mm=altura_mm, largura_mm=largura_mm)
    else:
        return Classificacao(status="IRREGULAR", motivos=["Anatel ausente ou divergente com a base"], altura_mm=altura_mm, largura_mm=largura_mm)