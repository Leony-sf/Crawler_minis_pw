from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime
from pathlib import Path


PACKAGE_DIR = Path(__file__).resolve().parent


def secao(titulo: str, tamanho: int = 90, caractere: str = "=") -> None:
    titulo = str(titulo or "").strip()
    if not titulo:
        print(caractere * tamanho)
        return
    texto = f" {titulo} "
    sobra = max(0, tamanho - len(texto))
    esquerda = sobra // 2
    direita = sobra - esquerda
    print("\n" + caractere * esquerda + texto + caractere * direita)


def log(categoria: str, mensagem: str) -> None:
    print(f"[{str(categoria).strip().lower()}] {mensagem}")


def bloco(categoria: str) -> None:
    print(f"\n[{str(categoria).strip().lower()}]")


def normalizar_texto(txt: object) -> str:
    txt = str(txt or "").replace("\xa0", " ")
    txt = re.sub(r"\s+", " ", txt)
    return txt.strip()


def remover_acentos(txt: object) -> str:
    txt = normalizar_texto(txt).lower()
    txt = unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode("ascii")
    return txt


def normalizar_chave(txt: object) -> str:
    txt = remover_acentos(txt)
    txt = re.sub(r"[^a-z0-9]+", " ", txt)
    return re.sub(r"\s+", " ", txt).strip()


def apenas_alnum(txt: object) -> str:
    return re.sub(r"[^a-z0-9]", "", remover_acentos(txt))


def arquivo_seguro(txt: object, limite: int = 90) -> str:
    txt = remover_acentos(txt)
    txt = re.sub(r"[^a-z0-9_-]+", "_", txt).strip("_")
    if not txt:
        txt = "produto_amazon"
    return txt[:limite]


def gerar_id(*partes: object) -> str:
    bruto = "|".join(normalizar_texto(p).lower() for p in partes if p is not None)
    return hashlib.md5(bruto.encode("utf-8", errors="ignore")).hexdigest()


def agora_iso() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def criar_pastas_saida(base: str | Path | None = None) -> Path:
    """Cria a saída dentro do pacote amazon_crawler por padrão.

    Estrutura:
      amazon_crawler/saidas/<execucao>/prints/regulares/anatel
      amazon_crawler/saidas/<execucao>/prints/regulares/CNPJ
      amazon_crawler/saidas/<execucao>/prints/irregulares/anatel
      amazon_crawler/saidas/<execucao>/prints/irregulares/cpf
    """
    if base is None:
        base = PACKAGE_DIR / "saidas" / f"amazon_playwright_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    base = Path(base)

    pastas = [
        base / "prints" / "regulares" / "anatel",
        base / "prints" / "regulares" / "CNPJ",
        base / "prints" / "irregulares" / "anatel",
        base / "prints" / "irregulares" / "cpf",
    ]
    for pasta in pastas:
        pasta.mkdir(parents=True, exist_ok=True)

    return base
