# -*- coding: utf-8 -*-
"""Utilitários do crawler Carrefour."""

from __future__ import annotations

import re
import shutil
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import List
from urllib.parse import quote_plus, quote


def agora_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def slugify(texto: str, max_len: int = 80) -> str:
    texto = unicodedata.normalize("NFKD", texto or "")
    texto = "".join(ch for ch in texto if not unicodedata.combining(ch))
    texto = re.sub(r"[^a-zA-Z0-9]+", "-", texto).strip("-").lower()
    return (texto[:max_len].strip("-") or "item")


def carregar_termos_busca(caminho_txt: str) -> List[str]:
    caminho = Path(caminho_txt)
    if not caminho.exists():
        caminho_local = Path(__file__).resolve().parent / caminho_txt
        if caminho_local.exists():
            caminho = caminho_local
    if not caminho.exists():
        alternativas = [
            Path(__file__).resolve().parent / "buscar_carrefour.txt",
            Path.cwd() / "buscar_carrefour.txt",
            Path.cwd() / "buscas_carrefour.txt",
        ]
        for alt in alternativas:
            if alt.exists():
                caminho = alt
                break
    if not caminho.exists():
        raise FileNotFoundError(
            f"Arquivo TXT não encontrado: {caminho_txt}. Coloque buscar_carrefour.txt ao lado do main_carrefour.py."
        )

    termos: List[str] = []
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#"):
            continue
        termos.append(linha)
    if not termos:
        raise ValueError("O arquivo TXT não possui termos de busca válidos.")
    return termos


def montar_url_busca(termo: str, pagina: int = 1, modo: str = "s") -> str:
    """
    Carrefour costuma indexar buscas no formato /s/<termo>?map=ft&page=N.
    Também deixamos fallbacks por /busca/<termo> e /busca?termo=<termo>.
    """
    termo_limpo = re.sub(r"\s+", " ", termo.strip())

    if modo == "busca":
        slug = quote(re.sub(r"\s+", "-", termo_limpo.lower()), safe="-")
        url = f"https://www.carrefour.com.br/busca/{slug}"
        if pagina > 1:
            url += f"?page={pagina}"
        return url

    if modo == "query":
        url = f"https://www.carrefour.com.br/busca?termo={quote_plus(termo_limpo)}"
        if pagina > 1:
            url += f"&page={pagina}"
        return url

    termo_url = quote(termo_limpo, safe="")
    return f"https://www.carrefour.com.br/s/{termo_url}?map=ft&page={pagina}"


def preparar_saida(saida: Path, limpar_prints: bool = False) -> None:
    """Mantém a saída limpa: parquet + resumo + prints, sem CSV/JSON/comentários."""
    saida.mkdir(parents=True, exist_ok=True)

    if limpar_prints:
        prints = saida / "prints"
        if prints.exists():
            shutil.rmtree(prints, ignore_errors=True)

    (saida / "prints" / "irregulares" / "menor_80mm").mkdir(parents=True, exist_ok=True)
    (saida / "prints" / "suspeitos").mkdir(parents=True, exist_ok=True)
    (saida / "suspeitos").mkdir(parents=True, exist_ok=True)

    arquivos_antigos = [
        "products.csv", "comments.csv", "comments.parquet", "resumo.csv", "resumo.json",
        "suspeitos_sem_medidas.parquet",
    ]
    for nome in arquivos_antigos:
        alvo = saida / nome
        if alvo.exists():
            alvo.unlink()

    pastas_antigas = [
        saida / "json",
        saida / "prints" / "descartados",
        saida / "prints" / "irregulares" / "mini_celulares",
        saida / "prints" / "irregulares" / "tela_ate_5_polegadas",
        saida / "prints" / "irregulares" / "tela_ate_3_polegadas",
        saida / "prints" / "irregulares" / "sem_medidas",
        saida / "prints" / "irregulares" / "revisar_medidas",
        saida / "prints" / "irregulares" / "sem_anatel",
        saida / "suspeitos_sem_medidas",
        saida / "suspeitos_tela_proxima_3",
        saida / "suspeitos_sem_tela",
        saida / "prints" / "suspeitos" / "tela_proxima_3_polegadas",
        saida / "prints" / "suspeitos" / "sem_tela",
        saida / "prints" / "debug_busca_sem_links",
    ]
    for pasta in pastas_antigas:
        if pasta.exists():
            shutil.rmtree(pasta, ignore_errors=True)


def escrever_resumo_txt(saida: Path, linhas: List[str]) -> None:
    saida.mkdir(parents=True, exist_ok=True)
    (saida / "resumo.txt").write_text("\n".join(linhas), encoding="utf-8")
