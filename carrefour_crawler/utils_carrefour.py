from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

PRODUCT_COLUMNS = [
    "pid", "marketplace_id", "marketplace", "titulo", "link",
    "codigo_anatel", "codigo_anatel_principal", "marca", "preco",
    "status", "motivo_validacao", "motivo_irregularidade", "warning",
    "modelo", "modelo_alfanumerico", "modelo_decisivo", "classificacao",
    "evidencia_mini", "dimensoes_encontradas", "codigo_confere_base",
    "marca_confere_base", "modelo_confere_base", "motivo_anatel",
    "data_hora_captura", "data_hora_captura_iso", "referencia_captura",
    "pasta_saida_execucao", "caminho_saida_execucao", "print_path"
]

COMMENT_COLUMNS = [
    "pid", "marketplace_id", "url", "link", "titulo", "name",
    "comentario_ordem", "comment", "comentario", "created_at",
    "query_busca", "classificacao", "status", "status_validacao",
    "codigo_anatel_principal", "anatel_number", "marca", "brand",
    "modelo", "data_hora_captura", "data_hora_captura_iso",
    "referencia_captura", "pasta_saida_execucao", "caminho_saida_execucao"
]

def normalizar_texto(valor: Any) -> str:
    if valor is None: return ""
    texto = str(valor).replace("\xa0", " ").strip().lower()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto).strip()

def normalizar_chave(valor: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", normalizar_texto(valor))

def remover_acentos(valor: Any) -> str:
    return normalizar_texto(valor)

def gerar_id(*valores: Any) -> str:
    base = "||".join(str(valor or "") for valor in valores)
    return hashlib.sha1(base.encode("utf-8", errors="ignore")).hexdigest()[:16]

def secao(titulo: str) -> None:
    print("\n" + "=" * 72)
    print(str(titulo).upper())
    print("=" * 72)

def bloco(titulo: str) -> None:
    print("\n" + "-" * 72)
    print(str(titulo).upper())
    print("-" * 72)

def log(categoria: str, mensagem: str, nivel: str = "INFO") -> None:
    horario = datetime.now().strftime("%H:%M:%S")
    cat_fmt = str(categoria or "geral").upper()[:16].ljust(16)
    niv_fmt = str(nivel or "INFO").upper()[:7].ljust(7)
    print(f"[{horario}] [{niv_fmt}] {cat_fmt} {mensagem}")

def criar_pastas_saida(base: str | Path | None = None) -> Path:
    raiz = Path(__file__).resolve().parent
    if base:
        saida = Path(base).expanduser()
        if not saida.is_absolute(): saida = raiz / saida
    else:
        nome_base = datetime.now().strftime("Saidas_carrefour-%d_%m-%H_%M")
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
    linhas_norm = [{k: _valor_para_parquet(v) for k, v in l.items()} for l in linhas_validas]
    df = pd.DataFrame(linhas_norm).reindex(columns=colunas_base)
    
    for col in df.columns:
        if col == "comentario_ordem":
            df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
        else:
            df[col] = df[col].where(pd.notna(df[col]), "").astype("string")
    return df

def salvar_parquet_incremental(pasta_saida: Path, produtos: list[dict[str, Any]], comentarios: list[dict[str, Any]]) -> None:
    preparar_dataframe(produtos, PRODUCT_COLUMNS).to_parquet(pasta_saida / "products.parquet", index=False)
    preparar_dataframe(comentarios, COMMENT_COLUMNS).to_parquet(pasta_saida / "comentarios.parquet", index=False)

def carregar_termos_busca(caminho_txt: str) -> list[str]:
    caminho = Path(caminho_txt)
    if not caminho.exists(): raise FileNotFoundError(f"Arquivo TXT não encontrado: {caminho_txt}")
    termos = [linha.strip() for linha in caminho.read_text(encoding="utf-8").splitlines() if linha.strip() and not linha.startswith("#")]
    if not termos: raise ValueError("O arquivo TXT não possui termos de busca válidos.")
    return termos