from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .utils import (
    log,
    log_aviso,
    log_ok,
    normalizar_codigo_anatel,
    normalizar_texto,
)


CANDIDATOS_COLUNA_CODIGO = [
    "numero de homologacao",
    "número de homologação",
    "homologacao",
    "homologação",
    "codigo anatel",
    "código anatel",
    "nr homologacao",
    "nr de homologacao",
    "nr de homologação",
    "nº homologacao",
    "nº de homologacao",
    "nº de homologação",
]

CANDIDATOS_COLUNA_FABRICANTE = [
    "fabricante",
    "nome fabricante",
    "nome do fabricante",
    "fornecedor",
]

CANDIDATOS_COLUNA_MARCA = [
    "marca",
    "marca comercial",
]

CANDIDATOS_COLUNA_MODELO = [
    "modelo",
    "modelo comercial",
    "nome modelo",
    "nome do modelo",
    "numero do modelo",
    "número do modelo",
]

CANDIDATOS_COLUNA_VERSAO = [
    "versao",
    "versão",
    "versoes",
    "versões",
    "modelo versao",
    "modelo versão",
    "versao do modelo",
    "versão do modelo",
]

CANDIDATOS_COLUNA_TIPO = [
    "tipo",
    "tipo produto",
    "tipo de produto",
    "produto",
]


def _normalizar_nome_coluna(col: Any) -> str:
    return normalizar_texto(col).replace("º", "o")


def _achar_coluna(df: pd.DataFrame, candidatos: list[str]) -> str | None:
    mapa = {_normalizar_nome_coluna(c): c for c in df.columns}
    candidatos_norm = [normalizar_texto(c) for c in candidatos]

    for candidato in candidatos_norm:
        if candidato in mapa:
            return mapa[candidato]

    for col_norm, col_original in mapa.items():
        if any(candidato in col_norm for candidato in candidatos_norm):
            return col_original

    return None


def carregar_base_anatel(caminho: str | None) -> pd.DataFrame:
    if not caminho:
        log(
            "base",
            "Nenhuma base ANATEL informada. "
            "Sem a base, os produtos serão classificados como IRREGULAR/SEM BASE.",
        )
        return pd.DataFrame()

    path = Path(caminho)

    if not path.exists():
        log("base", f"Base não encontrada: {path}")
        return pd.DataFrame()

    tentativas = [
        {"sep": ";", "encoding": "utf-8-sig"},
        {"sep": ";", "encoding": "latin1"},
        {"sep": ",", "encoding": "utf-8-sig"},
        {"sep": ",", "encoding": "latin1"},
        {"sep": "\t", "encoding": "utf-8-sig"},
        {"sep": "\t", "encoding": "latin1"},
        {"sep": "\t", "encoding": "utf-16"},
        {"sep": None, "encoding": "utf-8-sig", "engine": "python"},
        {"sep": None, "encoding": "latin1", "engine": "python"},
    ]

    ultimo_erro = None

    for kwargs in tentativas:
        try:
            df = pd.read_csv(path, dtype=str, **kwargs).fillna("")
            base = preparar_base(df)

            if not base.empty:
                log("base", f"CSV lido corretamente com parâmetros: {kwargs}")
                return base

            log(
                "base",
                f"Tentativa sem coluna válida. Parâmetros: {kwargs}. "
                f"Colunas lidas: {list(df.columns)[:10]}",
            )

        except Exception as exc:
            ultimo_erro = exc
            log("base", f"Falha ao ler CSV com {kwargs}: {exc}")

    log("base", f"Não consegui ler a base ANATEL corretamente: {ultimo_erro}")
    return pd.DataFrame()


def preparar_base(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    col_codigo = _achar_coluna(df, CANDIDATOS_COLUNA_CODIGO)
    col_fabricante = _achar_coluna(df, CANDIDATOS_COLUNA_FABRICANTE)
    col_marca = _achar_coluna(df, CANDIDATOS_COLUNA_MARCA)
    col_modelo = _achar_coluna(df, CANDIDATOS_COLUNA_MODELO)
    col_versao = _achar_coluna(df, CANDIDATOS_COLUNA_VERSAO)
    col_tipo = _achar_coluna(df, CANDIDATOS_COLUNA_TIPO)

    if not col_codigo:
        log_aviso("base", "Não encontrei coluna de número/código de homologação na base.")
        return pd.DataFrame()

    base = pd.DataFrame()

    base["codigo_anatel_norm"] = df[col_codigo].map(normalizar_codigo_anatel)
    base["fabricante_base"] = df[col_fabricante] if col_fabricante else ""
    base["marca_base"] = df[col_marca] if col_marca else ""
    base["modelo_base"] = df[col_modelo] if col_modelo else ""
    base["versao_base"] = df[col_versao] if col_versao else ""
    base["tipo_base"] = df[col_tipo] if col_tipo else ""

    base = base[base["codigo_anatel_norm"].astype(bool)]
    base = base.drop_duplicates("codigo_anatel_norm")

    log_ok("base", f"Base carregada: {len(base)} códigos únicos.")

    return base


def buscar_codigo_na_base(base: pd.DataFrame, codigo: str) -> dict[str, Any] | None:
    if base is None or base.empty or not codigo:
        return None

    achados = base[base["codigo_anatel_norm"] == codigo]

    if achados.empty:
        return None

    return achados.iloc[0].to_dict()