from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pandas as pd

from .utils import bloco, log, normalizar_chave, normalizar_texto


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


def _achar_coluna_exata(df: pd.DataFrame, nome_esperado: str) -> str:
    esperado = normalizar_chave(nome_esperado)
    for coluna in df.columns:
        if normalizar_chave(coluna) == esperado:
            return coluna
    return ""


def _achar_coluna(df: pd.DataFrame, alternativas: list[list[str]]) -> str:
    normalizadas = {col: normalizar_chave(col) for col in df.columns}
    for termos in alternativas:
        termos_norm = [normalizar_chave(t) for t in termos]
        for col, col_norm in normalizadas.items():
            if all(t in col_norm for t in termos_norm):
                return col
    return ""


@dataclass
class BaseAnatel:
    dataframe: pd.DataFrame
    coluna_codigo: str
    coluna_fabricante: str = ""
    coluna_modelo: str = ""
    coluna_situacao_requerimento: str = ""

    def buscar_codigo_exato(self, codigo: str) -> pd.DataFrame:
        codigo_norm = normalizar_codigo_anatel(codigo)
        if not codigo_norm or self.dataframe.empty:
            return self.dataframe.iloc[0:0]

        return self.dataframe[self.dataframe["codigo_anatel_normalizado"] == codigo_norm]


def carregar_base_anatel(caminho: str | Path | None, prefix_len: int = 5) -> BaseAnatel | None:
    if not caminho:
        log("base anatel", "Base não informada; a conformidade Anatel não poderá ser confirmada.", nivel="AVISO")
        return None

    df = _ler_csv(caminho)
    if df.empty:
        raise ValueError("A base Anatel está vazia.")

    col_hom = _achar_coluna(df, [["numero", "homolog"], ["codigo", "anatel"], ["homologacao"], ["homolog"]])
    if not col_hom:
        raise ValueError(f"Não foi encontrada coluna de homologação. Colunas: {list(df.columns)}")

    col_fab = _achar_coluna(df, [["nome", "fabricante"], ["fabricante"], ["marca"]])
    col_modelo = _achar_coluna(df, [["modelo"], ["nome", "modelo"]])
    col_situacao = _achar_coluna_exata(df, "Situação do Requerimento")
    
    if not col_situacao:
        raise ValueError("A coluna EXATA 'Situação do Requerimento' não foi encontrada.")

    base = df.copy()
    base["codigo_anatel_normalizado"] = base[col_hom].map(normalizar_codigo_anatel)
    base = base[base["codigo_anatel_normalizado"].astype(str).str.len() == 12].copy()
    base = base.drop_duplicates(subset=["codigo_anatel_normalizado"], keep="first")

    log("base anatel", f"Registros válidos carregados: {len(base)}")
    return BaseAnatel(
        dataframe=base,
        coluna_codigo=col_hom,
        coluna_fabricante=col_fab,
        coluna_modelo=col_modelo,
        coluna_situacao_requerimento=col_situacao,
    )