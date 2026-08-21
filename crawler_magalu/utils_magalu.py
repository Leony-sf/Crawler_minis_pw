# -*- coding: utf-8 -*-
"""Funções utilitárias do crawler Magalu."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import List
from urllib.parse import quote_plus, urljoin, urlsplit, urlunsplit


BASE_URL_MAGALU = "https://www.magazineluiza.com.br"


def agora_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def slugify(texto: str, max_len: int = 90) -> str:
    texto = (texto or "").strip().lower()
    texto = re.sub(r"https?://", "", texto)
    texto = re.sub(r"[^a-z0-9áéíóúâêôãõç]+", "-", texto, flags=re.IGNORECASE)
    texto = re.sub(r"-+", "-", texto).strip("-")
    if not texto:
        texto = "produto"
    return texto[:max_len].strip("-") or "produto"


def limpar_url(url: str) -> str:
    if not url:
        return ""
    url = url.strip()
    if url.startswith("//"):
        url = "https:" + url
    if url.startswith("/"):
        url = urljoin(BASE_URL_MAGALU, url)
    partes = urlsplit(url)
    return urlunsplit((partes.scheme or "https", partes.netloc, partes.path, "", ""))


def montar_url_busca(termo: str, pagina: int = 1) -> str:
    termo_q = quote_plus(termo.strip())
    return f"{BASE_URL_MAGALU}/busca/{termo_q}/?page={pagina}"


def resolver_arquivo_txt(caminho_txt: str) -> Path:
    entrada = Path(caminho_txt)
    candidatos = []

    if entrada.is_absolute():
        candidatos.append(entrada)
    else:
        cwd = Path.cwd()
        pasta_script = Path(__file__).resolve().parent
        candidatos.extend([cwd / entrada, pasta_script / entrada])

    aliases = ["buscar_magalu.txt", "buscas_magalu.txt"]
    cwd = Path.cwd()
    pasta_script = Path(__file__).resolve().parent
    for nome in aliases:
        candidatos.extend([cwd / nome, pasta_script / nome])

    vistos = []
    for candidato in candidatos:
        candidato = candidato.resolve()
        if candidato in vistos:
            continue
        vistos.append(candidato)
        if candidato.exists() and candidato.is_file():
            return candidato

    lista = "\n".join(f"- {p}" for p in vistos)
    raise FileNotFoundError("Arquivo TXT de buscas não encontrado. Caminhos verificados:\n" + lista)


def carregar_termos_busca(caminho_txt: str) -> List[str]:
    path = resolver_arquivo_txt(caminho_txt)
    termos: List[str] = []
    for linha in path.read_text(encoding="utf-8-sig").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#"):
            continue
        termos.append(linha)
    if not termos:
        raise ValueError(f"O arquivo {path} não possui termos de busca válidos.")
    return termos


def criar_pastas_saida_magalu(base: str | Path | None = None) -> Path:
    raiz = Path(__file__).resolve().parent

    if base:
        saida = Path(base).expanduser()
        if not saida.is_absolute():
            saida = raiz / saida
    else:
        nome_base = datetime.now().strftime("Saidas_magalu_%d-%m_%H-%M")
        saida = raiz / nome_base
        contador = 2

        while saida.exists():
            saida = raiz / f"{nome_base}_{contador:02d}"
            contador += 1

    saida = saida.resolve()

    (saida / "prints" / "irregulares").mkdir(parents=True, exist_ok=True)
    (saida / "prints" / "suspeitos").mkdir(parents=True, exist_ok=True)

    return saida