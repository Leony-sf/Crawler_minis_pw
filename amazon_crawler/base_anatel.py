from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
from typing import Optional

import pandas as pd

from .utils import bloco, log, normalizar_chave, normalizar_texto, remover_acentos


def normalizar_homologacao_base(valor: object) -> str:
    """Normaliza número de homologação para 12 dígitos.

    Trata zeros à esquerda e valores eventualmente salvos em notação científica
    pelo Excel, como 1,56482E+11 ou 1.56482E+11.
    """
    if pd.isna(valor):
        return ""

    txt = str(valor).strip().replace("\xa0", " ")
    if not txt:
        return ""

    txt_decimal = txt.replace(",", ".")
    if "e+" in txt_decimal.lower() or "e-" in txt_decimal.lower():
        try:
            txt = format(Decimal(txt_decimal), "f")
        except InvalidOperation:
            pass

    if re.fullmatch(r"\d+\.0+", txt):
        txt = txt.split(".", 1)[0]

    digitos = re.sub(r"\D", "", txt)
    if not digitos:
        return ""
    return digitos.zfill(12)


def _ler_csv_robusto(caminho: str | Path) -> pd.DataFrame:
    caminho = Path(caminho)
    tentativas = [
        {"sep": ";", "encoding": "utf-8-sig"},
        {"sep": ";", "encoding": "latin1"},
        {"sep": ",", "encoding": "utf-8-sig"},
        {"sep": ",", "encoding": "latin1"},
    ]
    ultimo_erro: Exception | None = None
    for kwargs in tentativas:
        try:
            return pd.read_csv(
                caminho,
                dtype=str,
                on_bad_lines="skip",
                keep_default_na=False,
                **kwargs,
            )
        except Exception as exc:  # pragma: no cover - fallback operacional
            ultimo_erro = exc
    raise RuntimeError(f"Não consegui ler o CSV da base: {caminho}. Erro: {ultimo_erro}")


def _achar_coluna(df: pd.DataFrame, alternativas: list[list[str]]) -> str:
    colunas_norm = {col: normalizar_chave(col) for col in df.columns}
    for termos in alternativas:
        termos_norm = [normalizar_chave(t) for t in termos]
        for col, col_norm in colunas_norm.items():
            if all(t in col_norm for t in termos_norm):
                return col
    return ""


@dataclass
class BaseAnatel:
    df: pd.DataFrame
    prefix_len: int = 5
    coluna_homologacao: str = ""
    coluna_fabricante: str = ""
    coluna_modelo: str = ""

    def linhas_por_codigo(self, codigo_12: str) -> pd.DataFrame:
        if not codigo_12 or self.df.empty:
            return self.df.iloc[0:0]
        if codigo_12 in self.df.index:
            linhas = self.df.loc[[codigo_12]] if not isinstance(self.df.loc[codigo_12], pd.DataFrame) else self.df.loc[codigo_12]
            return linhas if isinstance(linhas, pd.DataFrame) else linhas.to_frame().T
        return self.df.iloc[0:0]

    def linhas_por_prefixo(self, codigo_12: str) -> pd.DataFrame:
        if not codigo_12 or self.df.empty:
            return self.df.iloc[0:0]
        pref = codigo_12[: self.prefix_len]
        return self.df[self.df["homologacao_key"].astype(str).str.startswith(pref)]

    def candidatos_para_codigo(self, codigo_12: str) -> tuple[str, pd.DataFrame]:
        """Retorna ('exato'|'prefixo'|'nenhum', linhas candidatas)."""
        exatas = self.linhas_por_codigo(codigo_12)
        if not exatas.empty:
            return "exato", exatas
        prefixo = self.linhas_por_prefixo(codigo_12)
        if not prefixo.empty:
            return "prefixo", prefixo
        return "nenhum", self.df.iloc[0:0]


def carregar_base_anatel(caminho: Optional[str] = None, prefix_len: int = 5) -> BaseAnatel | None:
    """Carrega e prepara a base ANATEL.

    Se nenhum caminho for informado, retorna None para permitir execução em modo SEM_BASE.
    """
    if not caminho:
        log("base", "Nenhum CSV da ANATEL informado. Produtos ficarão como SEM_BASE quando houver código.")
        return None

    df = _ler_csv_robusto(caminho)
    if df.empty:
        raise ValueError("CSV da ANATEL está vazio.")

    # Prioridade absoluta para o nome oficial da base enviada pelo usuário.
    # Isso evita escolher coluna errada quando o CSV tiver vários campos com termos parecidos.
    if "Número de Homologação" in df.columns:
        col_hom = "Número de Homologação"
    else:
        col_hom = _achar_coluna(
            df,
            [
                ["numero", "homolog"],
                ["n", "homolog"],
                ["homologacao"],
                ["homologa"],
            ],
        )
    if not col_hom:
        raise ValueError(f"Não encontrei a coluna de homologação. Colunas: {list(df.columns)}")

    col_fab = _achar_coluna(
        df,
        [
            ["nome", "fabricante"],
            ["fabricante"],
        ],
    )
    col_modelo = _achar_coluna(
        df,
        [
            ["modelo"],
            ["nome", "modelo"],
        ],
    )

    base = df.copy()
    base["__homologacao_original"] = base[col_hom].astype(str)
    base["homologacao_key"] = base[col_hom].apply(normalizar_homologacao_base)
    base = base[base["homologacao_key"].astype(str).str.len().between(8, 14)].copy()
    base["homologacao_key"] = base["homologacao_key"].astype(str).str.zfill(12)
    base["Numero de Homologacao"] = base["homologacao_key"]

    if col_fab:
        base["fabricante_base"] = base[col_fab].apply(normalizar_texto)
    else:
        base["fabricante_base"] = ""

    if col_modelo:
        base["modelo_base"] = base[col_modelo].apply(normalizar_texto)
    else:
        base["modelo_base"] = ""

    base = base.drop_duplicates(subset=["homologacao_key", "fabricante_base", "modelo_base"], keep="first")
    base = base.set_index("homologacao_key", drop=False)

    bloco("base")
    log("base", f"Arquivo: {Path(caminho).resolve()}")
    log("base", f"Linhas válidas: {len(base)}")
    log("base", f"Coluna homologação: {col_hom}")
    log("base", f"Coluna fabricante/marca: {col_fab or 'não encontrada'}")
    log("base", f"Coluna modelo: {col_modelo or 'não encontrada'}")
    log("base", f"Regra: código exato OU prefixo de {prefix_len} dígitos")

    return BaseAnatel(
        df=base,
        prefix_len=prefix_len,
        coluna_homologacao=col_hom,
        coluna_fabricante=col_fab,
        coluna_modelo=col_modelo,
    )
