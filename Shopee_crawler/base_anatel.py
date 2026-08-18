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
    if not texto: return ""
    decimal = texto.replace(",", ".")
    if "e+" in decimal.lower() or "e-" in decimal.lower():
        try: texto = format(Decimal(decimal), "f")
        except InvalidOperation: pass
    if re.fullmatch(r"\d+\.0+", texto): texto = texto.split(".", 1)[0]
    digitos = re.sub(r"\D", "", texto)
    if not digitos: return ""
    if len(digitos) < 12: return digitos.zfill(12)
    return digitos[-12:]

def _ler_csv(caminho: str | Path) -> pd.DataFrame:
    path = Path(caminho).expanduser().resolve()
    if not path.is_file(): raise FileNotFoundError(f"Base Anatel não encontrada: {path}")
    tentativas = [
        {"sep": ";", "encoding": "utf-8-sig"}, {"sep": ";", "encoding": "latin1"},
        {"sep": ",", "encoding": "utf-8-sig"}, {"sep": ",", "encoding": "latin1"},
    ]
    for kw in tentativas:
        try:
            return pd.read_csv(path, dtype=str, keep_default_na=False, on_bad_lines="skip", **kw)
        except Exception: pass
    raise RuntimeError("Falha ao ler a base Anatel.")

def _achar_coluna(df: pd.DataFrame, alternativas: list[list[str]]) -> str:
    norm = {c: normalizar_chave(c) for c in df.columns}
    for termos in alternativas:
        t_norm = [normalizar_chave(t) for t in termos]
        for col, chave in norm.items():
            if all(t in chave for t in t_norm): return col
    return ""

def _achar_coluna_exata(df: pd.DataFrame, nome_esperado: str) -> str:
    esp = normalizar_chave(nome_esperado)
    for col in df.columns:
        if normalizar_chave(col) == esp: return col
    return ""

def _texto_compativel(anuncio: str, base: str) -> bool:
    an = normalizar_texto(anuncio)
    bn = normalizar_texto(base)
    if not an or not bn: return False
    return an == bn or an in bn or bn in an

@dataclass
class BaseAnatel:
    dataframe: pd.DataFrame
    coluna_codigo: str
    coluna_fabricante: str = ""
    coluna_modelo: str = ""
    coluna_situacao_requerimento: str = ""

    def buscar_codigo_exato(self, codigo: str) -> pd.DataFrame:
        codigo_norm = normalizar_codigo_anatel(codigo)
        if not codigo_norm or self.dataframe.empty: return self.dataframe.iloc[0:0]
        return self.dataframe[self.dataframe["codigo_anatel_normalizado"] == codigo_norm]

def carregar_base_anatel(caminho: str | Path | None) -> BaseAnatel | None:
    if not caminho:
        log("base anatel", "Base não informada.", nivel="AVISO")
        return None
    df = _ler_csv(caminho)
    if df.empty: raise ValueError("Base vazia.")
    col_cod = _achar_coluna(df, [["numero", "homolog"], ["codigo", "anatel"], ["homologacao"]])
    if not col_cod: raise ValueError("Coluna de homologação não encontrada.")
    col_fab = _achar_coluna(df, [["nome", "fabricante"], ["fabricante"], ["marca"]])
    col_mod = _achar_coluna(df, [["modelo"], ["nome", "modelo"]])
    col_sit = _achar_coluna_exata(df, "Situação do Requerimento")
    
    base = df.copy()
    base["codigo_anatel_normalizado"] = base[col_cod].map(normalizar_codigo_anatel)
    base = base[base["codigo_anatel_normalizado"].astype(str).str.len() == 12].copy()
    base = base.drop_duplicates(subset=["codigo_anatel_normalizado"], keep="first")
    
    log("base anatel", f"Registros carregados: {len(base)}")
    return BaseAnatel(base, col_cod, col_fab, col_mod, col_sit)

def _normalizar_situacao(valor: Any) -> str:
    t = normalizar_texto(valor)
    if "cancelad" in t: return "CANCELADA"
    if "suspens" in t: return "SUSPENSA"
    if "emitid" in t: return "EMITIDA"
    return "NAO_INFORMADA" if not t else "OUTRA"

def analisar_situacao_anatel(codigo: str, marca: str, modelo: str, base: BaseAnatel | None) -> dict[str, str]:
    codigo_norm = normalizar_codigo_anatel(codigo)
    res = {
        "codigo_anatel": str(codigo or ""), "codigo_anatel_normalizado": codigo_norm,
        "codigo_base": "", "codigo_confere_base": "NAO", "marca_confere_base": "NAO",
        "modelo_confere_base": "NAO", "situacao_requerimento_base": "",
        "situacao_requerimento_normalizada": "NAO_INFORMADA", "requerimento_emitido": "NAO",
        "anatel_em_ordem": "NAO", "situacao_anatel": "NAO_INFORMADO",
        "motivo_anatel": "Código Anatel não localizado no anúncio.", "fabricante_base": "", "modelo_base": ""
    }
    
    if not codigo_norm: return res
    if base is None:
        res.update({"situacao_anatel": "NAO_VERIFICADO", "motivo_anatel": "Nenhuma base fornecida."})
        return res

    encontrados = base.buscar_codigo_exato(codigo_norm)
    if encontrados.empty:
        res.update({"situacao_anatel": "IRREGULAR", "motivo_anatel": "Código não possui correspondência na base."})
        return res

    linha = encontrados.iloc[0]
    fab_base = str(linha.get(base.coluna_fabricante) or "") if base.coluna_fabricante else ""
    mod_base = str(linha.get(base.coluna_modelo) or "") if base.coluna_modelo else ""
    sit_base = str(linha.get(base.coluna_situacao_requerimento) or "")
    sit_norm = _normalizar_situacao(sit_base)

    res.update({
        "codigo_base": str(linha.get("codigo_anatel_normalizado") or ""),
        "codigo_confere_base": "SIM", "fabricante_base": fab_base, "modelo_base": mod_base,
        "situacao_requerimento_base": sit_base, "situacao_requerimento_normalizada": sit_norm,
    })

    marca_conf = _texto_compativel(marca, fab_base)
    mod_conf = _texto_compativel(modelo, mod_base)

    res.update({
        "marca_confere_base": "SIM" if marca_conf else "NAO",
        "modelo_confere_base": "SIM" if mod_conf else "NAO",
        "requerimento_emitido": "SIM" if sit_norm == "EMITIDA" else "NAO"
    })

    if sit_norm in {"CANCELADA", "SUSPENSA"}:
        res.update({
            "situacao_anatel": "IRREGULAR",
            "motivo_anatel": f"Situação do Requerimento: '{sit_base}'. Homologação suspensa ou cancelada não é válida."
        })
        return res

    if sit_norm != "EMITIDA" or not marca_conf or not mod_conf:
        res.update({
            "situacao_anatel": "REVISAR",
            "motivo_anatel": "Homologação necessita revisão (dados não conferem integralmente ou status diferente de Emitida)."
        })
        return res

    res.update({
        "anatel_em_ordem": "SIM", "situacao_anatel": "REGULAR",
        "motivo_anatel": "Homologação Emitida; dados do anúncio conferem com a base."
    })
    return res