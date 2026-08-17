# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote_plus, urljoin, urlsplit, urlunsplit

import pandas as pd

BASE_URL_ALIBABA = "https://www.alibaba.com"

PRODUCT_COLUMNS = [
    "pid", "marketplace_id", "titulo", "link", "codigo_anatel", "marca", "preco",
    "status", "motivo_validacao", "motivo_irregularidade", "warning", "modelo",
    "modelo_alfanumerico", "modelo_decisivo", "classificacao", "evidencia_mini",
    "dimensoes_encontradas", "codigo_confere_base", "marca_confere_base",
    "modelo_confere_base", "motivo_anatel", "data_hora_captura"
]

COMMENT_COLUMNS = [
    "pid", "marketplace_id", "url", "link", "titulo", "name", "comentario_ordem",
    "comment", "comentario", "created_at", "query_busca", "classificacao", "status",
    "status_validacao", "codigo_anatel_principal", "anatel_number", "marca", "brand",
    "modelo", "data_hora_captura", "data_hora_captura_iso", "referencia_captura",
    "pasta_saida_execucao", "caminho_saida_execucao"
]

def limpar_url(url: str) -> str:
    if not url: return ""
    url = url.strip()
    if url.startswith("//"): url = "https:" + url
    if url.startswith("/"): url = urljoin(BASE_URL_ALIBABA, url)
    partes = urlsplit(url)
    return urlunsplit((partes.scheme or "https", partes.netloc, partes.path, "", ""))

def montar_url_busca(termo: str, pagina: int = 1) -> str:
    termo_q = quote_plus(termo)
    return f"{BASE_URL_ALIBABA}/trade/search?fsb=y&IndexArea=product_en&SearchText={termo_q}&page={pagina}"

def normalizar_texto(valor: Any) -> str:
    if valor is None: return ""
    texto = str(valor).replace("\xa0", " ").strip().lower()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto).strip()

def normalizar_chave(valor: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", normalizar_texto(valor))

def arquivo_seguro(valor: Any, limite: int = 110) -> str:
    texto = unicodedata.normalize("NFKD", str(valor or "arquivo"))
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", texto)
    return re.sub(r"\s+", "_", texto).strip("._ ")[:limite] or "arquivo"

def gerar_id(*valores: Any) -> str:
    base = "||".join(str(valor or "") for valor in valores)
    return hashlib.sha1(base.encode("utf-8", errors="ignore")).hexdigest()[:16]

def secao(titulo: str) -> None:
    print("\n" + "=" * 72 + f"\n{str(titulo).upper()}\n" + "=" * 72)

def bloco(titulo: str) -> None:
    print("\n" + "-" * 72 + f"\n{str(titulo).upper()}\n" + "-" * 72)

def log(categoria: str, mensagem: str, nivel: str = "INFO") -> None:
    horario = datetime.now().strftime("%H:%M:%S")
    categoria_formatada = str(categoria or "geral").upper()[:16].ljust(16)
    nivel_formatado = str(nivel or "INFO").upper()[:7].ljust(7)
    print(f"[{horario}] [{nivel_formatado}] {categoria_formatada} {mensagem}")

def ler_termos_txt(caminho: str | Path) -> list[str]:
    arquivo = Path(caminho).expanduser().resolve()
    if not arquivo.is_file(): raise FileNotFoundError(f"TXT não encontrado: {arquivo}")
    termos, vistos = [], set()
    for linha in arquivo.read_text(encoding="utf-8-sig").splitlines():
        termo = linha.strip()
        if not termo or termo.startswith("#"): continue
        chave = normalizar_texto(termo)
        if chave not in vistos:
            vistos.add(chave)
            termos.append(termo)
    if not termos: raise ValueError(f"Nenhum termo válido em: {arquivo}")
    return termos

def criar_pastas_saida_alibaba(base: str | Path | None = None) -> Path:
    raiz = Path(__file__).resolve().parent
    if base:
        saida = Path(base).expanduser()
        if not saida.is_absolute(): saida = raiz / saida
    else:
        nome_base = datetime.now().strftime("Saidas_alibaba_%d-%m_%H-%M")
        saida = raiz / nome_base
        contador = 2
        while saida.exists():
            saida = raiz / f"{nome_base}_{contador:02d}"
            contador += 1
    saida = saida.resolve()
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
    linhas_validas = [l for l in linhas if str(l.get("pid") or "").strip()]
    linhas_normalizadas = [{k: _valor_para_parquet(v) for k, v in l.items()} for l in linhas_validas]
    dataframe = pd.DataFrame(linhas_normalizadas).reindex(columns=colunas_base)
    colunas_numericas = {"altura_cm", "largura_cm", "espessura_cm", "maior_dimensao_cm", "segunda_dimensao_cm", "limite_altura_cm", "limite_largura_cm", "total_comentarios", "comentario_ordem"}
    for coluna in dataframe.columns:
        if coluna in colunas_numericas:
            dataframe[coluna] = pd.to_numeric(dataframe[coluna], errors="coerce").astype("float64")
        else:
            dataframe[coluna] = dataframe[coluna].where(pd.notna(dataframe[coluna]), "").astype("string")
    return dataframe

def salvar_parquet_incremental(pasta_saida: Path, produtos: list[dict[str, Any]], comentarios: list[dict[str, Any]]) -> None:
    preparar_dataframe(produtos, PRODUCT_COLUMNS).to_parquet(pasta_saida / "products.parquet", index=False)
    preparar_dataframe(comentarios, COMMENT_COLUMNS).to_parquet(pasta_saida / "comments.parquet", index=False)