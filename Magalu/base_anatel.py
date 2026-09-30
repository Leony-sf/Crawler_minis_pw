from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pandas as pd

from utils import log, normalizar_chave, normalizar_texto

MARCAS_ALIASES = {
    "xiaomi": ["xiaomi", "redmi", "poco", "pocophone"],
    "motorola": ["motorola", "lenovo"],
    "apple": ["apple"],
    "samsung": ["samsung"],
    "lg": ["lg"],
    "asus": ["asus", "rog"],
    "realme": ["realme"],
    "oppo": ["oppo"],
    "vivo": ["vivo"],
    "huawei": ["huawei"],
    "infinix": ["infinix", "positivo"],
    "multilaser": ["multilaser", "multi"],
}

def normalizar_codigo_anatel(valor: Any) -> str:
    texto = str(valor or "").strip().replace("\xa0", " ")
    if not texto:
        return ""

    decimal = texto.replace(",", ".")
    if "e+" in decimal.lower() or "e-" in decimal.lower():
        try:
            texto = format(Decimal(decimal), "f")
        except InvalidOperation:
            pass

    if re.fullmatch(r"\d+\.0+", texto):
        texto = texto.split(".", 1)[0]

    digitos = re.sub(r"\D", "", texto)
    if not digitos:
        return ""
    if len(digitos) < 12:
        return digitos.zfill(12)
    return digitos[-12:]


def _ler_csv(caminho: str | Path) -> pd.DataFrame:
    path = Path(caminho).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(f"Base Anatel não encontrada: {path}")

    ultimo_erro: Exception | None = None
    tentativas = [
        {"sep": ";", "encoding": "utf-8-sig"},
        {"sep": ";", "encoding": "latin1"},
        {"sep": ",", "encoding": "utf-8-sig"},
        {"sep": ",", "encoding": "latin1"},
    ]

    for kwargs in tentativas:
        try:
            return pd.read_csv(
                path,
                dtype=str,
                keep_default_na=False,
                on_bad_lines="skip",
                **kwargs,
            )
        except Exception as exc:
            ultimo_erro = exc

    raise RuntimeError(f"Falha ao ler a base Anatel: {ultimo_erro}")


def _achar_coluna_exata(
    df: pd.DataFrame,
    nome_esperado: str,
) -> str:
    """Procura um cabeçalho pelo nome normalizado exato."""
    esperado = normalizar_chave(nome_esperado)

    for coluna in df.columns:
        if normalizar_chave(coluna) == esperado:
            return coluna

    return ""


def _achar_coluna(
    df: pd.DataFrame,
    alternativas: list[list[str]],
) -> str:
    normalizadas = {
        coluna: normalizar_chave(coluna)
        for coluna in df.columns
    }

    for termos in alternativas:
        termos_norm = [normalizar_chave(termo) for termo in termos]
        for coluna, chave in normalizadas.items():
            if all(termo in chave for termo in termos_norm):
                return coluna
    return ""


def _marca_equivalente(marca_anuncio: str, marca_base: str) -> bool:
    ma = normalizar_texto(marca_anuncio)
    mb = normalizar_texto(marca_base)
    if not ma or not mb:
        return False
    if ma in mb or mb in ma:
        return True
    
    for key, aliases in MARCAS_ALIASES.items():
        if any(al in ma for al in aliases) and any(al in mb for al in aliases):
            return True
    return False


def _modelo_estrito(modelo_anuncio: str, modelo_base: str) -> bool:
    ma = normalizar_texto(modelo_anuncio)
    mb = normalizar_texto(modelo_base)
    if not ma or not mb:
        return False
    # Comparação exata ou contida estritamente (sem fuzzy/aproximação)
    return ma == mb or mb in ma


def _nome_comercial_equivalente(nome_anuncio: str, nome_base: str) -> bool:
    na = normalizar_texto(nome_anuncio)
    nb = normalizar_texto(nome_base)
    if not na or not nb:
        return False
    
    # Equivalências controladas
    subs = [("pro plus", "pro+"), ("5g", "5 g"), ("4g", "4 g")]
    for de, para in subs:
        na = na.replace(de, para)
        nb = nb.replace(de, para)
        
    return nb in na or na in nb


@dataclass
class BaseAnatel:
    dataframe: pd.DataFrame
    coluna_codigo: str
    coluna_fabricante: str = ""
    coluna_modelo: str = ""
    coluna_nome_comercial: str = ""
    coluna_situacao_requerimento: str = ""

    def buscar_codigo_exato(self, codigo: str) -> pd.DataFrame:
        codigo_norm = normalizar_codigo_anatel(codigo)
        if not codigo_norm or self.dataframe.empty:
            return self.dataframe.iloc[0:0]

        return self.dataframe[
            self.dataframe["codigo_anatel_normalizado"] == codigo_norm
        ]

    def buscar_prefixo(self, codigo: str) -> pd.DataFrame:
        codigo_norm = normalizar_codigo_anatel(codigo)
        if not codigo_norm or self.dataframe.empty:
            return self.dataframe.iloc[0:0]

        prefixo = codigo_norm[:5]
        return self.dataframe[
            self.dataframe[
                "codigo_anatel_normalizado"
            ].str.startswith(prefixo)
        ]


def carregar_base_anatel(
    caminho: str | Path | None,
) -> BaseAnatel | None:
    if not caminho:
        log(
            "base anatel",
            "Base não informada; a conformidade Anatel não poderá ser "
            "confirmada.",
            nivel="AVISO",
        )
        return None

    df = _ler_csv(caminho)
    if df.empty:
        raise ValueError("A base Anatel está vazia.")

    coluna_codigo = _achar_coluna(df, [
        ["numero", "homolog"],
        ["codigo", "anatel"],
        ["homologacao"],
        ["homolog"],
    ])
    if not coluna_codigo:
        raise ValueError(
            "Não foi encontrada coluna de homologação. "
            f"Colunas disponíveis: {list(df.columns)}"
        )

    coluna_fabricante = _achar_coluna(df, [
        ["nome", "fabricante"],
        ["fabricante"],
        ["marca"],
    ])
    coluna_modelo = _achar_coluna(df, [
        ["modelo"],
        ["nome", "modelo"],
    ])
    coluna_nome_comercial = _achar_coluna(df, [
        ["nome", "comercial"],
        ["comercial"],
    ])
    coluna_situacao_requerimento = _achar_coluna_exata(
        df,
        "Situação do Requerimento",
    )
    if not coluna_situacao_requerimento:
        raise ValueError(
            "A coluna EXATA 'Situação do Requerimento' não foi encontrada. "
            "A coluna 'Código de Situação do Requerimento' não será usada."
        )

    base = df.copy()
    base["codigo_anatel_normalizado"] = base[coluna_codigo].map(
        normalizar_codigo_anatel
    )
    base = base[
        base["codigo_anatel_normalizado"].astype(str).str.len() == 12
    ].copy()

    base = base.drop_duplicates(
        subset=["codigo_anatel_normalizado"],
        keep="first",
    )

    log("base anatel", f"Registros válidos carregados: {len(base)}")
    return BaseAnatel(
        dataframe=base,
        coluna_codigo=coluna_codigo,
        coluna_fabricante=coluna_fabricante,
        coluna_modelo=coluna_modelo,
        coluna_nome_comercial=coluna_nome_comercial,
        coluna_situacao_requerimento=coluna_situacao_requerimento,
    )


def _normalizar_situacao_requerimento(valor: Any) -> str:
    texto = normalizar_texto(valor)

    if "cancelad" in texto:
        return "CANCELADA"
    if "suspens" in texto:
        return "SUSPENSA"
    if "emitid" in texto:
        return "EMITIDA"
    if not texto:
        return "NAO_INFORMADA"
    return "OUTRA"


def analisar_situacao_anatel(
    codigo: str,
    marca: str,
    modelo: str,
    nome_comercial: str,
    base: BaseAnatel | None,
) -> dict[str, str]:
    codigo_norm = normalizar_codigo_anatel(codigo)

    resultado = {
        "codigo_anatel": str(codigo or ""),
        "codigo_anatel_normalizado": codigo_norm,
        "codigo_base": "",
        "codigo_confere_base": "NAO",
        "marca_confere_base": "NAO",
        "modelo_confere_base": "NAO",
        "nome_comercial_confere_base": "NAO",
        "situacao_requerimento_base": "",
        "situacao_requerimento_normalizada": "NAO_INFORMADA",
        "requerimento_emitido": "NAO",
        "anatel_em_ordem": "NAO",
        "situacao_anatel": "NAO_INFORMADO",
        "motivo_anatel": "Código Anatel não localizado no anúncio.",
        "fabricante_base": "",
        "modelo_base": "",
        "nome_comercial_base": "",
    }

    if not codigo_norm:
        return resultado

    if base is None:
        resultado.update({
            "situacao_anatel": "NAO_VERIFICADO",
            "motivo_anatel": (
                "Código encontrado no anúncio, mas nenhuma base Anatel "
                "foi fornecida para a conferência."
            ),
        })
        return resultado

    encontrados = base.buscar_codigo_exato(codigo_norm)
    if encontrados.empty:
        resultado.update({
            "situacao_anatel": "IRREGULAR",
            "motivo_anatel": (
                "Código do anúncio não possui correspondência exata "
                "na base Anatel."
            ),
        })
        return resultado

    linha = encontrados.iloc[0]
    fabricante_base = (
        str(linha.get(base.coluna_fabricante) or "")
        if base.coluna_fabricante
        else ""
    )
    modelo_base = (
        str(linha.get(base.coluna_modelo) or "")
        if base.coluna_modelo
        else ""
    )
    nome_comercial_base = (
        str(linha.get(base.coluna_nome_comercial) or "")
        if base.coluna_nome_comercial
        else ""
    )

    situacao_requerimento_base = str(
        linha.get(base.coluna_situacao_requerimento) or ""
    )
    situacao_requerimento_normalizada = (
        _normalizar_situacao_requerimento(situacao_requerimento_base)
    )

    resultado.update({
        "codigo_base": str(
            linha.get("codigo_anatel_normalizado") or ""
        ),
        "codigo_confere_base": "SIM",
        "fabricante_base": fabricante_base,
        "modelo_base": modelo_base,
        "nome_comercial_base": nome_comercial_base,
        "situacao_requerimento_base": situacao_requerimento_base,
        "situacao_requerimento_normalizada": (
            situacao_requerimento_normalizada
        ),
    })

    # Aqui é onde o nome comercial (e as outras variáveis) são finalmente usadas!
    marca_confere = _marca_equivalente(marca, fabricante_base)
    modelo_confere = _modelo_estrito(modelo, modelo_base)
    nome_comercial_confere = _nome_comercial_equivalente(nome_comercial, nome_comercial_base) if nome_comercial_base else True

    resultado.update({
        "marca_confere_base": "SIM" if marca_confere else "NAO",
        "modelo_confere_base": "SIM" if modelo_confere else "NAO",
        "nome_comercial_confere_base": "SIM" if nome_comercial_confere else "NAO",
        "requerimento_emitido": (
            "SIM"
            if situacao_requerimento_normalizada == "EMITIDA"
            else "NAO"
        ),
    })

    divergencias: list[str] = []

    if not marca_confere:
        divergencias.append("marca do anúncio incompatível com a base")
    if not modelo_confere:
        divergencias.append("modelo técnico do anúncio incompatível com a base")
    if nome_comercial_base and not nome_comercial_confere:
        divergencias.append("nome comercial do anúncio incompatível com a base")

    if situacao_requerimento_normalizada in {"CANCELADA", "SUSPENSA"}:
        resultado.update({
            "situacao_anatel": "IRREGULAR",
            "motivo_anatel": (
                f"Situação do Requerimento: '{situacao_requerimento_base}'. "
                "Homologação suspensa ou cancelada não é válida."
            ),
        })
        return resultado

    if situacao_requerimento_normalizada != "EMITIDA":
        resultado.update({
            "situacao_anatel": "NAO_CLASSIFICADO",
            "motivo_anatel": (
                "Situação do Requerimento não reconhecida ou pendente: "
                f"'{situacao_requerimento_base or 'não informado'}'."
            ),
        })
        return resultado

    if divergencias:
        resultado.update({
            "situacao_anatel": "NAO_CLASSIFICADO",
            "motivo_anatel": (
                "Homologação Emitida, porém: "
                + "; ".join(divergencias)
                + "."
            ),
        })
        return resultado

    resultado.update({
        "anatel_em_ordem": "SIM",
        "situacao_anatel": "REGULAR",
        "motivo_anatel": (
            "Homologação Emitida; código, marca, modelo e nome comercial "
            "do anúncio conferem com a base."
        ),
    })
    return resultado