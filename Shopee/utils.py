from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote_plus, urlsplit, urlunsplit

import pandas as pd

VERBOSE = os.getenv("CRAWLER_VERBOSE", "0").strip() == "1"

PRODUCT_COLUMNS = [
    "pid", "marketplace_id", "titulo", "link", "url", "codigo_anatel", "marca",
    "preco", "status", "motivo_validacao", "motivo_irregularidade", "warning",
    "modelo", "modelo_alfanumerico", "modelo_decisivo", "nome_comercial", "classificacao",
    "evidencia_mini", "dimensoes_encontradas", "codigo_confere_base",
    "marca_confere_base", "modelo_confere_base", "nome_comercial_confere_base", "motivo_anatel", "data_hora_captura"
]

COMMENT_COLUMNS = [
    "pid", "marketplace_id", "url", "link", "titulo", "name",
    "comentario_ordem", "comment", "comentario", "created_at",
    "query_busca", "classificacao", "status", "status_validacao",
    "codigo_anatel_principal", "anatel_number", "marca", "brand",
    "modelo", "data_hora_captura", "data_hora_captura_iso",
    "referencia_captura", "pasta_saida_execucao", "caminho_saida_execucao"
]

def _hora_log() -> str:
    return datetime.now().strftime("%H:%M:%S")

def normalizar_texto(valor: Any) -> str:
    if valor is None: return ""
    texto = str(valor).replace("\xa0", " ").strip().lower()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto).strip()

def normalizar_chave(valor: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", normalizar_texto(valor))

def arquivo_seguro(valor: Any, limite: int = 110) -> str:
    texto = normalizar_texto(valor)
    texto = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", texto)
    return re.sub(r"\s+", "_", texto).strip("._ ")[:limite]

def gerar_id(*valores: Any) -> str:
    base = "||".join(str(v or "") for v in valores)
    return hashlib.sha1(base.encode("utf-8", errors="ignore")).hexdigest()[:16]

def log(categoria: str, mensagem: str, nivel: str = "INFO") -> None:
    cat_fmt = str(categoria or "GERAL").upper()[:10].ljust(10)
    niv_fmt = str(nivel or "INFO").upper()[:7].ljust(7)
    print(f"[{_hora_log()}] [{niv_fmt}] {cat_fmt} {mensagem}")

def log_ok(categoria: str, mensagem: str) -> None:
    log(categoria, mensagem, nivel="OK")

def log_aviso(categoria: str, mensagem: str) -> None:
    log(categoria, mensagem, nivel="AVISO")

def log_erro(categoria: str, mensagem: str) -> None:
    log(categoria, mensagem, nivel="ERRO")

def log_debug(categoria: str, mensagem: str) -> None:
    if VERBOSE:
        log(categoria, mensagem, nivel="DEBUG")

def secao(titulo: str) -> None:
    print("\n" + "=" * 72)
    print(str(titulo).upper())
    print("=" * 72)

def bloco(titulo: str) -> None:
    print("\n" + "-" * 72)
    print(str(titulo).upper())
    print("-" * 72)

def linha(titulo: str = "") -> None:
    print()
    if titulo:
        print("-" * 60)
        print(titulo.upper())
        print("-" * 60)
    else:
        print("-" * 60)

def encurtar_texto(texto: str, limite: int = 100) -> str:
    texto = " ".join(str(texto or "").split())
    if len(texto) <= limite:
        return texto
    return texto[: limite - 3] + "..."

def criar_pastas_saida(base: str | Path | None = None) -> Path:
    nome_base = datetime.now().strftime("Saidas_shopee_%d-%m_%H-%M")
    raiz = Path(__file__).resolve().parent
    saida = raiz / nome_base
    contador = 2
    while saida.exists():
        saida = raiz / f"{nome_base}_{contador:02d}"
        contador += 1
    saida.resolve().mkdir(parents=True, exist_ok=True)
    (saida / "prints" / "irregulares").mkdir(parents=True, exist_ok=True)
    (saida / "prints" / "suspeitos").mkdir(parents=True, exist_ok=True)
    (saida / "prints" / "regulares").mkdir(parents=True, exist_ok=True)
    (saida / "prints" / "nao_classificados").mkdir(parents=True, exist_ok=True)
    return saida

def pasta_print_por_status(pasta_saida: Path, status_validacao: str) -> Path:
    status = str(status_validacao or "").upper().strip()
    if status == "REGULAR":
        pasta = pasta_saida / "prints" / "regulares"
    elif status in ["SUSPEITO", "SUSPEITO_MANUAL"]:
        pasta = pasta_saida / "prints" / "suspeitos"
    elif status == "NAO_CLASSIFICADO":
        pasta = pasta_saida / "prints" / "nao_classificados"
    else:
        pasta = pasta_saida / "prints" / "irregulares"
    pasta.mkdir(parents=True, exist_ok=True)
    return pasta

def metadados_captura(pasta_saida: Path, momento: datetime | None = None) -> dict[str, str]:
    momento = momento or datetime.now().astimezone()
    return {
        "data_hora_captura": momento.strftime("%d/%m/%Y %H:%M:%S"),
        "data_hora_captura_iso": momento.isoformat(timespec="seconds"),
        "referencia_captura": f"Produto capturado em {momento.strftime('%d/%m/%Y às %H:%M:%S')}",
        "pasta_saida_execucao": pasta_saida.name,
        "caminho_saida_execucao": str(pasta_saida.resolve()),
    }

def _valor_para_parquet(valor: Any) -> Any:
    if isinstance(valor, (dict, list, tuple, set)):
        return json.dumps(valor, ensure_ascii=False, sort_keys=True)
    return valor

def preparar_dataframe(linhas: list[dict[str, Any]], colunas_base: list[str]) -> pd.DataFrame:
    for linha in linhas:
        link_correto = linha.get("url") or linha.get("link") or ""
        linha["url"] = link_correto
        linha["link"] = link_correto

    linhas_validas = [l for l in linhas if str(l.get("pid") or l.get("indice") or "").strip()]
    linhas_norm = [{k: _valor_para_parquet(v) for k, v in l.items()} for l in linhas_validas]
    df = pd.DataFrame(linhas_norm)
    
    for col in colunas_base:
        if col not in df.columns:
            df[col] = ""
            
    df = df.reindex(columns=colunas_base)
    for col in df.columns:
        if col in ["comentario_ordem", "indice", "pagina_origem", "comentarios_total_detectado", "comentarios_capturados", "comentario_indice"]:
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
        else:
            df[col] = df[col].where(pd.notna(df[col]), "").astype("string")
    return df

def salvar_parquet_incremental(pasta_saida: Path, produtos: list[dict[str, Any]], comentarios: list[dict[str, Any]]) -> None:
    df_prod = preparar_dataframe(produtos, PRODUCT_COLUMNS)
    df_prod.to_parquet(pasta_saida / "products.parquet", index=False)
    df_com = preparar_dataframe(comentarios, COMMENT_COLUMNS)
    df_com.to_parquet(pasta_saida / "comments.parquet", index=False)

def salvar_products(pasta_saida: Path, produtos: list[dict[str, Any]]) -> Path:
    path = pasta_saida / "products.parquet"
    preparar_dataframe(produtos, PRODUCT_COLUMNS).to_parquet(path, index=False)
    return path

def salvar_products_descartados_mini(pasta_saida: Path, produtos: list[dict[str, Any]]) -> Path:
    path = pasta_saida / "products_descartados_mini.parquet"
    preparar_dataframe(produtos, PRODUCT_COLUMNS).to_parquet(path, index=False)
    return path

def salvar_products_suspeitos_mini(pasta_saida: Path, produtos: list[dict[str, Any]]) -> Path:
    path = pasta_saida / "products_suspeitos_mini.parquet"
    preparar_dataframe(produtos, PRODUCT_COLUMNS).to_parquet(path, index=False)
    return path

def salvar_comentarios(pasta_saida: Path, comentarios: list[dict[str, Any]]) -> Path:
    path = pasta_saida / "comments.parquet"
    preparar_dataframe(comentarios, COMMENT_COLUMNS).to_parquet(path, index=False)
    return path

def juntar_textos(valores: Iterable[Any], separador: str = " | ") -> str:
    res = []
    for v in valores:
        txt = str(v or "").strip()
        if txt and txt not in res:
            res.append(txt)
    return separador.join(res)

def construir_url_busca(query: str) -> str:
    termo = quote_plus(query.strip())
    return f"https://shopee.com.br/search?keyword={termo}"

def limpar_url(url: str) -> str:
    if not url: return ""
    url = url.strip()
    if url.startswith("//"): url = "https:" + url
    if url.startswith("/"): url = "https://shopee.com.br" + url
    p = urlsplit(url)
    return urlunsplit((p.scheme, p.netloc, p.path, "", ""))

def ler_termos_txt(caminho: str | Path) -> list[str]:
    arquivo = Path(caminho).expanduser().resolve()
    if not arquivo.is_file(): raise FileNotFoundError(f"Arquivo não encontrado: {arquivo}")
    termos = []
    for linha in arquivo.read_text(encoding="utf-8-sig").splitlines():
        termo = linha.strip()
        if termo and not termo.startswith("#"):
            termos.append(termo)
    return termos