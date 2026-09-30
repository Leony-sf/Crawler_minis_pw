from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import pandas as pd

from utils import log, normalizar_chave, normalizar_texto


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


def normalizar_nome_comercial(texto: str) -> str:
    """Aplica as equivalências controladas antes de comparar."""
    t = normalizar_texto(texto)
    if not t:
        return ""
    # Equivalências controladas exigidas
    t = t.replace("pro plus", "pro+")
    t = t.replace("5 g", "5g")
    t = t.replace("4 g", "4g")
    return t


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


def _texto_compativel(anuncio: str, base: str) -> bool:
    anuncio_norm = normalizar_texto(anuncio)
    base_norm = normalizar_texto(base)

    if not anuncio_norm or not base_norm:
        return False

    return (
        anuncio_norm == base_norm
        or anuncio_norm in base_norm
        or base_norm in anuncio_norm
    )


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
    
    # As colunas abaixo agora são buscadas pelo nome exato, conforme documentação
    coluna_modelo = _achar_coluna_exata(df, "Modelo")
    coluna_nome_comercial = _achar_coluna_exata(df, "Nome Comercial")
    
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
    modelo_tecnico: str,
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
        "situacao_requerimento_normalizada": situacao_requerimento_normalizada,
    })

    marca_confere = _texto_compativel(marca, fabricante_base)
    modelo_confere = _texto_compativel(modelo_tecnico, modelo_base)
    
    anuncio_nc_norm = normalizar_nome_comercial(nome_comercial)
    base_nc_norm = normalizar_nome_comercial(nome_comercial_base)
    nome_comercial_confere = False
    
    if anuncio_nc_norm and base_nc_norm:
        nome_comercial_confere = (anuncio_nc_norm in base_nc_norm or base_nc_norm in anuncio_nc_norm)
    elif not base_nc_norm:
        nome_comercial_confere = True

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

    if not marca:
        divergencias.append("marca não capturada no anúncio")
    elif not fabricante_base:
        divergencias.append("marca/fabricante ausente na base")
    elif not marca_confere:
        divergencias.append("marca do anúncio diferente da base")

    if not modelo_tecnico:
        divergencias.append("modelo técnico não capturado no anúncio")
    elif not modelo_base:
        divergencias.append("modelo técnico ausente na base")
    elif not modelo_confere:
        divergencias.append("modelo técnico do anúncio diferente da base")

    if nome_comercial and nome_comercial_base and not nome_comercial_confere:
        divergencias.append("nome comercial do anúncio diferente da base")

    if situacao_requerimento_normalizada in {"CANCELADA", "SUSPENSA"}:
        resultado.update({
            "situacao_anatel": "IRREGULAR",
            "motivo_anatel": (
                "Código exato localizado. Situação do Requerimento: "
                f"'{situacao_requerimento_base}'. "
                "Homologação suspensa ou cancelada não é válida."
            ),
        })
        return resultado

    if situacao_requerimento_normalizada != "EMITIDA":
        resultado.update({
            "situacao_anatel": "REVISAR",
            "motivo_anatel": (
                "Código exato localizado, mas a coluna "
                "'Situação do Requerimento' contém um valor não reconhecido: "
                f"'{situacao_requerimento_base or 'não informado'}'."
            ),
        })
        return resultado

    if divergencias:
        resultado.update({
            "situacao_anatel": "REVISAR",
            "motivo_anatel": (
                "Homologação Emitida e código exato localizado, porém "
                + "; ".join(divergencias)
                + "."
            ),
        })
        return resultado

    resultado.update({
        "anatel_em_ordem": "SIM",
        "situacao_anatel": "REGULAR",
        "motivo_anatel": (
            "Homologação Emitida; código, marca/fabricante, modelo técnico "
            "e nome comercial do anúncio conferem com a base."
        ),
    })
    return resultado