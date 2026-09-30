from __future__ import annotations
import re
import unicodedata
from dataclasses import dataclass, asdict
from typing import Any, Dict, Iterable, List, Optional, Tuple

LIMITE_COMPRIMENTO_CM = 12.0
LIMITE_LARGURA_CM = 5.5
MARGEM_PROXIMA_CM = 1.0

MARCAS_GRANDES = {
    "apple", "iphone", "samsung", "galaxy", "motorola", "xiaomi", "redmi", "poco","huawei", "nokia", "lg", "sony", "asus",
    "lenovo","google", "blackberry"
}

TERMOS_CELULAR = {
    "celular", "telefone", "telefone movel", "telefone móvel", "smartphone",
    "mobile phone", "cell phone", "cellphone", "phone", "gsm", "2g", "3g", "4g",
    "dual sim", "sim card", "nano sim", "micro sim", "chip", "accept sim",
    "tarjeta sim", "cartao sim", "cartão sim", "bluetooth dialer",
}

TERMOS_MINI = {
    "mini celular", "mini telefone", "mini phone", "mini mobile", "small phone",
    "smallest phone", "tiny phone", "pocket phone", "card phone", "credit card phone",
    "ultra thin phone", "ultra small", "micro phone", "telefone pequeno",
    "celular pequeno", "mini smartphone", "aeku", "kuh", "q8 mini", "v8 mini", "t2 mini",
    "bm10", "bm20", "bm30", "bm50", "bm70", "bm90", "bm100", "bm200", "bm310",
    "bt11", "bt22", "b25", "b30", "j8", "j9", "j10", "long-cz j8", "long-cz j9",
    "k10", "k33", "k66", "soyes s10", "soyes xs", "soyes 7s", "melrose s9", "melrose s10",
    "l8star", "l8 star", "gtstar", "gt star", "zanco", "zanco tiny", "servo phone",
    "servo", "anica", "aizku", "kechaoda", "soyes", "melrose", "long-cz"
}

TERMOS_FUNCIONAIS = {
    "dual sim", "sim card", "cartao sim", "cartão sim", "aceita chip", "accept sim",
    "gsm", "bluetooth dialer", "dialer", "call", "make calls", "phone call",
    "telefone desbloqueado", "unlocked phone", "feature phone", "keypad phone",
}

TERMOS_ACESSORIO = {
    "case", "capa", "cover", "pelicula", "película", "glass", "screen protector",
    "lcd", "display", "touch screen", "digitizer", "battery", "bateria",
    "charger", "carregador", "cable", "cabo", "fone", "earphone", "headphone",
    "holder", "suporte", "strap", "cordao", "cordão", "adapter", "adaptador",
    "camera lens", "film", "skin", "sticker", "adesivo", "bag", "bolsa",
}

@dataclass
class DimensaoEncontrada:
    bruto: str
    comprimento_cm: float
    largura_cm: float
    altura_cm: Optional[float] = None

    @property
    def menores_dois_lados(self) -> Tuple[float, float]:
        valores = [self.comprimento_cm, self.largura_cm]
        if self.altura_cm is not None:
            valores.append(self.altura_cm)
        valores = sorted(v for v in valores if v and v > 0)
        if len(valores) >= 2:
            return valores[0], valores[1]
        if len(valores) == 1:
            return valores[0], valores[0]
        return 999.0, 999.0

@dataclass
class ResultadoClassificacao:
    status: str
    manter: bool
    suspeito: bool
    motivo: str
    categoria_print: str
    possui_medida: bool
    dimensoes: List[Dict[str, Any]]
    termos_encontrados: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

def normalizar_texto(texto: Optional[str]) -> str:
    if not texto:
        return ""
    texto = unicodedata.normalize("NFKD", str(texto))
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    texto = texto.lower()
    texto = re.sub(r"\s+", " ", texto)
    return texto.strip()

def contem_termo(texto_norm: str, termos: Iterable[str]) -> bool:
    return any(normalizar_texto(t) in texto_norm for t in termos)

def termos_presentes(texto_norm: str, termos: Iterable[str]) -> List[str]:
    achados = []
    for termo in sorted(termos, key=len, reverse=True):
        termo_norm = normalizar_texto(termo)
        if termo_norm and termo_norm in texto_norm:
            achados.append(termo)
    return achados

def _num(valor: str) -> float:
    return float(valor.replace(",", "."))

def _converter_para_cm(valor: float, unidade: str) -> float:
    unidade = unidade.lower().strip()
    if unidade in {"mm", "milimetro", "milimetros", "milímetro", "milímetros"}:
        return valor / 10.0
    if unidade in {'in', 'inch', 'inches', '"'}:
        return valor * 2.54
    return valor

def extrair_dimensoes(texto: str) -> List[DimensaoEncontrada]:
    if not texto:
        return []
    t = normalizar_texto(texto)
    achados: List[DimensaoEncontrada] = []
    padrao_unidade_final = re.compile(
        r"(?P<a>\d{1,3}(?:[\.,]\d+)?)\s*(?:x|\*|×|by)\s*"
        r"(?P<b>\d{1,3}(?:[\.,]\d+)?)"
        r"(?:\s*(?:x|\*|×|by)\s*(?P<c>\d{1,3}(?:[\.,]\d+)?))?\s*"
        r"(?P<u>cm|mm|in|inch|inches|\")\b"
    )
    padrao_unidade_por_lado = re.compile(
        r"(?P<a>\d{1,3}(?:[\.,]\d+)?)\s*(?P<ua>cm|mm|in|inch|inches|\")\s*"
        r"(?:x|\*|×|by)\s*"
        r"(?P<b>\d{1,3}(?:[\.,]\d+)?)\s*(?P<ub>cm|mm|in|inch|inches|\")"
        r"(?:\s*(?:x|\*|×|by)\s*(?P<c>\d{1,3}(?:[\.,]\d+)?)\s*(?P<uc>cm|mm|in|inch|inches|\"))?"
    )

    for m in padrao_unidade_final.finditer(t):
        unidade = m.group("u")
        a = _converter_para_cm(_num(m.group("a")), unidade)
        b = _converter_para_cm(_num(m.group("b")), unidade)
        c = _converter_para_cm(_num(m.group("c")), unidade) if m.group("c") else None
        if _dimensao_fisica_plausivel(a, b, c):
            achados.append(DimensaoEncontrada(m.group(0), a, b, c))

    for m in padrao_unidade_por_lado.finditer(t):
        a = _converter_para_cm(_num(m.group("a")), m.group("ua"))
        b = _converter_para_cm(_num(m.group("b")), m.group("ub"))
        c = _converter_para_cm(_num(m.group("c")), m.group("uc")) if m.group("c") and m.group("uc") else None
        if _dimensao_fisica_plausivel(a, b, c):
            bruto = m.group(0)
            if not any(abs(d.comprimento_cm - a) < 0.01 and abs(d.largura_cm - b) < 0.01 for d in achados):
                achados.append(DimensaoEncontrada(bruto, a, b, c))
    return achados

def _dimensao_fisica_plausivel(a: float, b: float, c: Optional[float]) -> bool:
    valores = [v for v in [a, b, c] if v is not None]
    if len(valores) < 2:
        return False
    if any(v <= 0 or v > 80 for v in valores):
        return False
    return True

def medida_menor_ou_proxima(dimensao: DimensaoEncontrada) -> Tuple[bool, str]:
    lado1, lado2 = dimensao.menores_dois_lados
    limite1 = LIMITE_LARGURA_CM
    limite2 = LIMITE_COMPRIMENTO_CM
    menor_que_proposta = lado1 <= limite1 and lado2 <= limite2
    proxima = lado1 <= (limite1 + MARGEM_PROXIMA_CM) and lado2 <= (limite2 + MARGEM_PROXIMA_CM)

    if menor_que_proposta:
        return True, f"medida menor/igual à proposta ({lado2:.1f} x {lado1:.1f} cm)"
    if proxima:
        return True, f"medida próxima à proposta ({lado2:.1f} x {lado1:.1f} cm)"
    return False, f"medida encontrada fora do perfil ({lado2:.1f} x {lado1:.1f} cm)"

def classificar_produto(produto: Dict[str, Any], manter_brinquedos: bool = False) -> ResultadoClassificacao:
    titulo = produto.get("titulo") or produto.get("title") or ""
    texto_total = " ".join(
        str(produto.get(campo) or "")
        for campo in [
            "titulo", "title", "descricao_curta", "detalhes", "texto_pagina",
            "categoria", "modelo", "marca", "atributos",
        ]
    )
    texto_norm = normalizar_texto(texto_total)
    titulo_norm = normalizar_texto(titulo)

    mini_terms = termos_presentes(texto_norm, TERMOS_MINI)
    celular_terms = termos_presentes(texto_norm, TERMOS_CELULAR)
    funcionais = termos_presentes(texto_norm, TERMOS_FUNCIONAIS)
    termos = sorted(set(mini_terms + celular_terms + funcionais))

    tem_mini = bool(mini_terms)
    tem_celular = bool(celular_terms)
    tem_funcional = bool(funcionais)
    acessorio = contem_termo(titulo_norm, TERMOS_ACESSORIO) and not (tem_mini and tem_funcional)
    marca_grande = contem_termo(titulo_norm, MARCAS_GRANDES)

    dimensoes = extrair_dimensoes(texto_total)
    possui_medida = bool(dimensoes)

    if marca_grande:
        return ResultadoClassificacao(
            status="DESCARTADO", manter=False, suspeito=False,
            motivo="marca de smartphone comum detectada (ex: Xiaomi, Samsung, Apple)",
            categoria_print="", possui_medida=possui_medida,
            dimensoes=[asdict(d) for d in dimensoes], termos_encontrados=termos,
        )

    if acessorio:
        return ResultadoClassificacao(
            status="DESCARTADO", manter=False, suspeito=False,
            motivo="aparenta ser acessório/peça, não aparelho celular",
            categoria_print="", possui_medida=possui_medida,
            dimensoes=[asdict(d) for d in dimensoes], termos_encontrados=termos,
        )

    candidato = tem_mini or (tem_celular and tem_funcional)

    if candidato:
        if dimensoes:
            motivos_dim = []
            suspeito_por_dim = False
            for d in dimensoes:
                ok, motivo_dim = medida_menor_ou_proxima(d)
                motivos_dim.append(motivo_dim)
                suspeito_por_dim = suspeito_por_dim or ok

            if suspeito_por_dim:
                return ResultadoClassificacao(
                    status="IRREGULAR", manter=True, suspeito=True,
                    motivo="; ".join(motivos_dim),
                    categoria_print="irregulares", possui_medida=True,
                    dimensoes=[asdict(d) for d in dimensoes], termos_encontrados=termos,
                )
            
            return ResultadoClassificacao(
                status="SUSPEITO", manter=True, suspeito=True,
                motivo="candidato forte a mini celular, mas medida encontrada não ficou abaixo/próxima do limite: " + "; ".join(motivos_dim),
                categoria_print="suspeitos", possui_medida=True,
                dimensoes=[asdict(d) for d in dimensoes], termos_encontrados=termos,
            )
        else:
            return ResultadoClassificacao(
                status="SUSPEITO", manter=True, suspeito=True,
                motivo="candidato forte a mini celular/celular pequeno sem medidas informadas.",
                categoria_print="suspeitos", possui_medida=False,
                dimensoes=[], termos_encontrados=termos,
            )

    return ResultadoClassificacao(
        status="DESCARTADO", manter=False, suspeito=False,
        motivo="sem indício rigoroso de mini celular/funções de rede",
        categoria_print="", possui_medida=possui_medida,
        dimensoes=[asdict(d) for d in dimensoes], termos_encontrados=termos,
    )