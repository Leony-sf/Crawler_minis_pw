from __future__ import annotations
import asyncio
import hashlib
import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List
import pandas as pd

PRODUCT_COLUMNS = [
    "pid", "marketplace_id", "titulo", "link", "codigo_anatel", "marca", "preco",
    "status", "motivo_validacao", "motivo_irregularidade", "warning", "modelo",
    "modelo_alfanumerico", "modelo_decisivo", "classificacao", "evidencia_mini",
    "dimensoes_encontradas", "codigo_confere_base", "marca_confere_base",
    "modelo_confere_base", "motivo_anatel", "data_hora_captura",
]

COMMENT_COLUMNS = [
    "pid", "marketplace_id", "url", "link", "titulo", "name", "comentario_ordem",
    "comment", "comentario", "created_at", "query_busca", "classificacao", "status",
    "status_validacao", "codigo_anatel_principal", "anatel_number", "marca", "brand",
    "modelo", "data_hora_captura", "data_hora_captura_iso", "referencia_captura",
    "pasta_saida_execucao", "caminho_saida_execucao",
]

def slugify(texto: str, limite: int = 90) -> str:
    texto = unicodedata.normalize("NFKD", str(texto or ""))
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    texto = re.sub(r"[^a-z0-9]+", "_", texto.lower().strip())
    return re.sub(r"_+", "_", texto).strip("_")[:limite] or "produto"

def hash_curto(texto: str, tamanho: int = 8) -> str:
    return hashlib.sha1(str(texto or "").encode("utf-8", errors="ignore")).hexdigest()[:tamanho]

def gerar_id(*valores: Any) -> str:
    base = "||".join(str(valor or "") for valor in valores)
    return hashlib.sha1(base.encode("utf-8", errors="ignore")).hexdigest()[:16]

def criar_pastas_saida(base: str | Path | None = None) -> Path:
    raiz = Path(__file__).resolve().parent
    if base:
        saida = Path(base).expanduser()
        if not saida.is_absolute():
            saida = raiz / saida
    else:
        nome_base = datetime.now().strftime("Saidas_aliexpress_%d-%m_%H-%M")
        saida = raiz / nome_base
        contador = 2
        while saida.exists():
            saida = raiz / f"{nome_base}_{contador:02d}"
            contador += 1
    saida = saida.resolve()
    
    # Cria ESTRITAMENTE as pastas padrão
    (saida / "prints" / "irregulares").mkdir(parents=True, exist_ok=True)
    (saida / "prints" / "suspeitos").mkdir(parents=True, exist_ok=True)
    return saida

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
    linhas_validas = [linha for linha in linhas if str(linha.get("pid") or "").strip()]
    linhas_normalizadas = [{chave: _valor_para_parquet(valor) for chave, valor in linha.items()} for linha in linhas_validas]
    if not linhas_normalizadas:
        return pd.DataFrame(columns=colunas_base)
        
    dataframe = pd.DataFrame(linhas_normalizadas).reindex(columns=colunas_base)
    colunas_numericas = {"comentario_ordem"}
    for coluna in dataframe.columns:
        if coluna in colunas_numericas:
            dataframe[coluna] = pd.to_numeric(dataframe[coluna], errors="coerce").astype("float64")
        else:
            dataframe[coluna] = dataframe[coluna].where(pd.notna(dataframe[coluna]), "").astype("string")
    return dataframe

def salvar_parquet_incremental(pasta_saida: Path, produtos: list[dict[str, Any]], comentarios: list[dict[str, Any]]) -> None:
    df_produtos = preparar_dataframe(produtos, PRODUCT_COLUMNS)
    df_produtos.to_parquet(pasta_saida / "products.parquet", index=False)
    
    df_comentarios = preparar_dataframe(comentarios, COMMENT_COLUMNS)
    df_comentarios.to_parquet(pasta_saida / "comments.parquet", index=False)

def _candidatos_txt(caminho_txt: str | None) -> List[Path]:
    script_dir = Path(__file__).resolve().parent
    cwd = Path.cwd()
    nomes = [str(caminho_txt)] if caminho_txt else []
    nomes.extend(n for n in ["buscar_aliexpress.txt", "buscas_aliexpress.txt"] if n not in nomes)
    candidatos = []
    for nome in nomes:
        p = Path(nome).expanduser()
        if p.is_absolute():
            candidatos.append(p)
        else:
            candidatos.extend([cwd / p, script_dir / p, script_dir.parent / p])
    return [p for i, p in enumerate(candidatos) if p not in candidatos[:i]]

def ler_buscas(caminho_txt: str | None, queries_cli: Iterable[str] | None = None) -> List[str]:
    buscas = []
    for candidato in _candidatos_txt(caminho_txt):
        if candidato.exists() and candidato.is_file():
            for linha in candidato.read_text(encoding="utf-8").splitlines():
                if linha.strip() and not linha.startswith("#"):
                    buscas.append(linha.strip())
            break
    if queries_cli:
        buscas.extend(str(q).strip() for q in queries_cli if str(q).strip())
    
    saida = []
    for q in buscas:
        if q.lower() not in [s.lower() for s in saida]:
            saida.append(q)
    return saida

async def espera_curta(segundos: float = 0.8) -> None:
    await asyncio.sleep(segundos)

async def rolar_pagina(page, passos: int = 5, pausa: float = 0.6) -> None:
    for _ in range(passos):
        await page.mouse.wheel(0, 900)
        await asyncio.sleep(pausa)