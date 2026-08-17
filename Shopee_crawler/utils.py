from __future__ import annotations

import os
import re
import shutil
import time
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote_plus, urlsplit, urlunsplit

import pandas as pd


COLUNAS_PRODUCTS_PARQUET = [
    "engine",
    "indice",
    "url",
    "titulo",
    "preco",
    "marca",
    "modelo",
    "versao",
    "fabricante",
    "codigo_anatel_principal",
    "status_validacao",
    "motivo_validacao",
    "fabricante_base",
    "marca_base",
    "modelo_base",
    "versao_base",
    "mini_status",
    "mini_motivo",
    "mini_maior_cm",
    "mini_largura_cm",
    "mini_espessura_cm",
    "mini_evidencia",
    "mini_limite_maior_cm",
    "mini_limite_largura_cm",
    "mini_suspeito_manual",
    "mini_motivos_suspeito",
    "query_origem",
    "pagina_origem",
    "print_path",
    "erro",
]

COLUNAS_COMENTARIOS_PARQUET = [
    "engine",
    "indice_produto",
    "url",
    "titulo",
    "comentarios_total_detectado",
    "comentarios_capturados",
    "comentario_indice",
    "comentario",
    "erro",
]


VERBOSE = os.getenv("CRAWLER_VERBOSE", "0").strip() == "1"


def agora_id() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _hora_log() -> str:
    return datetime.now().strftime("%H:%M:%S")


def linha(titulo: str = "") -> None:
    print()

    if titulo:
        print("-" * 60)
        print(titulo.upper())
        print("-" * 60)
    else:
        print("-" * 60)


def secao(titulo: str) -> None:
    print()
    print("=" * 60)
    print(titulo.upper())
    print("=" * 60)


def log(categoria: str, mensagem: str, nivel: str = "INFO") -> None:
    categoria_fmt = str(categoria or "GERAL").upper()[:10].ljust(10)
    nivel_fmt = str(nivel or "INFO").upper()[:7].ljust(7)

    print(f"[{_hora_log()}] [{nivel_fmt}] {categoria_fmt} {mensagem}")


def log_ok(categoria: str, mensagem: str) -> None:
    log(categoria, mensagem, nivel="OK")


def log_aviso(categoria: str, mensagem: str) -> None:
    log(categoria, mensagem, nivel="AVISO")


def log_erro(categoria: str, mensagem: str) -> None:
    log(categoria, mensagem, nivel="ERRO")


def log_debug(categoria: str, mensagem: str) -> None:
    if VERBOSE:
        log(categoria, mensagem, nivel="DEBUG")


def encurtar_texto(texto: str, limite: int = 100) -> str:
    texto = " ".join(str(texto or "").split())

    if len(texto) <= limite:
        return texto

    return texto[: limite - 3] + "..."


def dormir(segundos: float) -> None:
    if segundos and segundos > 0:
        time.sleep(segundos)


def normalizar_texto(valor: Any) -> str:
    if valor is None:
        return ""

    txt = str(valor).strip().lower()
    txt = unicodedata.normalize("NFKD", txt)
    txt = "".join(ch for ch in txt if not unicodedata.combining(ch))
    txt = re.sub(r"\s+", " ", txt)
    return txt


def somente_digitos(valor: Any) -> str:
    return re.sub(r"\D+", "", str(valor or ""))


def normalizar_codigo_anatel(valor: Any) -> str:
    digitos = somente_digitos(valor)

    if not digitos:
        return ""

    if len(digitos) < 12:
        return digitos.zfill(12)

    return digitos[-12:]


def parece_codigo_anatel(valor: Any) -> bool:
    digitos = somente_digitos(valor)
    return 8 <= len(digitos) <= 12


def construir_url_busca(query: str) -> str:
    termo = quote_plus(query.strip())
    return f"https://shopee.com.br/search?keyword={termo}"


def limpar_url(url: str) -> str:
    if not url:
        return ""

    url = url.strip()

    if url.startswith("//"):
        url = "https:" + url

    if url.startswith("/"):
        url = "https://shopee.com.br" + url

    partes = urlsplit(url)

    return urlunsplit((partes.scheme, partes.netloc, partes.path, "", ""))


def criar_pasta_saida(engine: str) -> Path:
    pasta = Path("saidas") / f"shopee_{engine}"

    if pasta.exists():
        shutil.rmtree(pasta)

    (pasta / "prints" / "regulares").mkdir(parents=True, exist_ok=True)
    (pasta / "prints" / "irregulares").mkdir(parents=True, exist_ok=True)

    return pasta


def pasta_print_por_status(pasta_saida: Path, status_validacao: str) -> Path:
    status = str(status_validacao or "").upper().strip()

    if status == "REGULAR":
        pasta = pasta_saida / "prints" / "regulares"
    else:
        pasta = pasta_saida / "prints" / "irregulares"

    pasta.mkdir(parents=True, exist_ok=True)
    return pasta


COLUNAS_NUMERICAS_PRODUCTS = {
    "mini_maior_cm",
    "mini_largura_cm",
    "mini_espessura_cm",
    "mini_limite_maior_cm",
    "mini_limite_largura_cm",
    "indice",
    "pagina_origem",
}


def _valor_parquet_seguro(valor: Any) -> Any:
    if valor is None:
        return ""

    try:
        if pd.isna(valor):
            return ""
    except Exception:
        pass

    if isinstance(valor, (dict, list, tuple, set)):
        try:
            import json
            return json.dumps(valor, ensure_ascii=False)
        except Exception:
            return str(valor)

    return valor


def _dataframe_products_seguro(produtos: list[dict[str, Any]]) -> pd.DataFrame:
    df = pd.DataFrame(produtos)

    for coluna in COLUNAS_PRODUCTS_PARQUET:
        if coluna not in df.columns:
            df[coluna] = ""

    df = df[COLUNAS_PRODUCTS_PARQUET].copy()

    for coluna in df.columns:
        df[coluna] = df[coluna].map(_valor_parquet_seguro)

    for coluna in COLUNAS_NUMERICAS_PRODUCTS:
        if coluna in df.columns:
            df[coluna] = pd.to_numeric(df[coluna], errors="coerce")

    for coluna in df.columns:
        if coluna not in COLUNAS_NUMERICAS_PRODUCTS:
            df[coluna] = df[coluna].fillna("").astype(str)

    return df


def _salvar_products_nome(pasta_saida: Path, produtos: list[dict[str, Any]], nome_arquivo: str) -> Path:
    pasta_saida.mkdir(parents=True, exist_ok=True)
    df = _dataframe_products_seguro(produtos)
    products_path = pasta_saida / nome_arquivo
    df.to_parquet(products_path, index=False)
    return products_path


def salvar_products(pasta_saida: Path, produtos: list[dict[str, Any]]) -> Path:
    return _salvar_products_nome(pasta_saida, produtos, "products.parquet")


def salvar_products_descartados_mini(pasta_saida: Path, produtos: list[dict[str, Any]]) -> Path:
    return _salvar_products_nome(pasta_saida, produtos, "products_descartados_mini.parquet")


def salvar_products_suspeitos_mini(pasta_saida: Path, produtos: list[dict[str, Any]]) -> Path:
    return _salvar_products_nome(pasta_saida, produtos, "products_suspeitos_mini.parquet")


def salvar_comentarios(pasta_saida: Path, comentarios: list[dict[str, Any]]) -> Path:
    pasta_saida.mkdir(parents=True, exist_ok=True)

    df = pd.DataFrame(comentarios)

    for coluna in COLUNAS_COMENTARIOS_PARQUET:
        if coluna not in df.columns:
            df[coluna] = ""

    df = df[COLUNAS_COMENTARIOS_PARQUET].copy()

    comentarios_path = pasta_saida / "comentarios.parquet"
    df.to_parquet(comentarios_path, index=False)

    return comentarios_path


# Compatibilidade caso alguma parte antiga ainda chame salvar_resultados.
def salvar_resultados(pasta_saida: Path, resultados: list[dict[str, Any]]) -> Path:
    return salvar_products(pasta_saida, resultados)


def juntar_textos(valores: Iterable[Any], separador: str = " | ") -> str:
    saida = []

    for valor in valores:
        txt = str(valor or "").strip()

        if txt and txt not in saida:
            saida.append(txt)

    return separador.join(saida)