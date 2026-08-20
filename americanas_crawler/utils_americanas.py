# -*- coding: utf-8 -*-
from __future__ import annotations
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import List, Any
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
        raise FileNotFoundError(f"Arquivo TXT não encontrado: {caminho_txt}")

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
    if modo == "busca":
        slug = quote(re.sub(r"\s+", "-", termo.strip().lower()), safe="-")
        url = f"https://www.americanas.com.br/busca/{slug}"
        if pagina > 1:
            url += f"?page={pagina}"
        return url
    url = f"https://www.americanas.com.br/s?q={quote_plus(termo)}"
    if pagina > 1:
        url += f"&page={pagina}"
    return url

def criar_pastas_saida(base: str | Path | None = None) -> Path:
    raiz = Path.cwd()
    if base and str(base) != "saidas_americanas":
        saida = Path(base).expanduser()
        if not saida.is_absolute():
            saida = raiz / saida
    else:
        nome_base = datetime.now().strftime("Saidas_americanas_%d-%m_%H-%M")
        saida = raiz / nome_base
        contador = 2
        while saida.exists():
            saida = raiz / f"{nome_base}_{contador:02d}"
            contador += 1
            
    saida = saida.resolve()
    (saida / "prints" / "irregulares").mkdir(parents=True, exist_ok=True)
    (saida / "prints" / "suspeitos").mkdir(parents=True, exist_ok=True)
    return saida

def escrever_resumo_txt(saida: Path, linhas: List[str]) -> None:
    saida.mkdir(parents=True, exist_ok=True)
    (saida / "resumo.txt").write_text("\n".join(linhas), encoding="utf-8")

# --- Funções de Log ---

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
    categoria_formatada = str(categoria or "geral").upper()[:16].ljust(16)
    nivel_formatado = str(nivel or "INFO").upper()[:7].ljust(7)
    print(f"[{horario}] [{nivel_formatado}] {categoria_formatada} {mensagem}")