from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


PRODUCT_COLUMNS = [
    "pid",
    "marketplace_id",
    "titulo",
    "link",
    "codigo_anatel",
    "marca",
    "preco",
    "status",
    "motivo_validacao",
    "motivo_irregularidade",
    "warning",
    "modelo",
    "modelo_alfanumerico",
    "modelo_decisivo",
    "classificacao",
    "evidencia_mini",
    "dimensoes_encontradas",
    "codigo_confere_base",
    "marca_confere_base",
    "modelo_confere_base",
    "motivo_anatel",
    "data_hora_captura",
]

COMMENT_COLUMNS = [
    "pid",
    "marketplace_id",
    "url",
    "link",
    "titulo",
    "name",
    "comentario_ordem",
    "comment",
    "comentario",
    "created_at",
    "query_busca",
    "classificacao",
    "status",
    "status_validacao",
    "codigo_anatel_principal",
    "anatel_number",
    "marca",
    "brand",
    "modelo",
    "data_hora_captura",
    "data_hora_captura_iso",
    "referencia_captura",
    "pasta_saida_execucao",
    "caminho_saida_execucao",
]


def normalizar_texto(valor: Any) -> str:
    if valor is None:
        return ""
    texto = str(valor).replace("\xa0", " ").strip().lower()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(
        caractere
        for caractere in texto
        if not unicodedata.combining(caractere)
    )
    return re.sub(r"\s+", " ", texto).strip()


def normalizar_chave(valor: Any) -> str:
    return re.sub(
        r"[^a-z0-9]+",
        "",
        normalizar_texto(valor),
    )


def remover_acentos(valor: Any) -> str:
    return normalizar_texto(valor)


def apenas_alnum(valor: Any) -> str:
    return re.sub(
        r"[^a-zA-Z0-9]+",
        "",
        str(valor or ""),
    )


def arquivo_seguro(
    valor: Any,
    limite: int = 110,
) -> str:
    texto = unicodedata.normalize(
        "NFKD",
        str(valor or "arquivo"),
    )
    texto = "".join(
        caractere
        for caractere in texto
        if not unicodedata.combining(caractere)
    )
    texto = re.sub(
        r'[<>:"/\\|?*\x00-\x1f]+',
        "_",
        texto,
    )
    texto = re.sub(
        r"\s+",
        "_",
        texto,
    ).strip("._ ")
    return (texto or "arquivo")[:limite]


def gerar_id(*valores: Any) -> str:
    base = "||".join(
        str(valor or "")
        for valor in valores
    )
    return hashlib.sha1(
        base.encode(
            "utf-8",
            errors="ignore",
        )
    ).hexdigest()[:16]


def secao(titulo: str) -> None:
    print("\n" + "=" * 72)
    print(str(titulo).upper())
    print("=" * 72)


def bloco(titulo: str) -> None:
    print("\n" + "-" * 72)
    print(str(titulo).upper())
    print("-" * 72)


def log(
    categoria: str,
    mensagem: str,
    nivel: str = "INFO",
) -> None:
    horario = datetime.now().strftime("%H:%M:%S")
    categoria_formatada = (
        str(categoria or "geral")
        .upper()[:16]
        .ljust(16)
    )
    nivel_formatado = (
        str(nivel or "INFO")
        .upper()[:7]
        .ljust(7)
    )
    print(
        f"[{horario}] [{nivel_formatado}] "
        f"{categoria_formatada} {mensagem}"
    )


def ler_termos_txt(
    caminho: str | Path,
) -> list[str]:
    arquivo = Path(caminho).expanduser().resolve()
    if not arquivo.is_file():
        raise FileNotFoundError(
            f"Arquivo TXT não encontrado: {arquivo}"
        )

    termos: list[str] = []
    vistos: set[str] = set()

    for linha in arquivo.read_text(
        encoding="utf-8-sig"
    ).splitlines():
        termo = linha.strip()
        if not termo or termo.startswith("#"):
            continue

        chave = normalizar_texto(termo)
        if chave in vistos:
            continue

        vistos.add(chave)
        termos.append(termo)

    if not termos:
        raise ValueError(
            f"Nenhum termo válido encontrado em: {arquivo}"
        )

    return termos


def _nome_saida_base() -> str:
    return datetime.now().strftime(
        "Saidas_mercadolivre_%d-%m_%H-%M"
    )


def criar_pastas_saida(
    base: str | Path | None = None,
) -> Path:
    raiz = Path(__file__).resolve().parent

    if base:
        saida = Path(base).expanduser()
        if not saida.is_absolute():
            saida = raiz / saida
    else:
        nome_base = _nome_saida_base()
        saida = raiz / nome_base
        contador = 2

        while saida.exists():
            saida = raiz / (
                f"{nome_base}_{contador:02d}"
            )
            contador += 1

    saida = saida.resolve()

    (saida / "prints" / "irregulares").mkdir(
        parents=True,
        exist_ok=True,
    )
    (saida / "prints" / "suspeitos").mkdir(
        parents=True,
        exist_ok=True,
    )

    return saida


def metadados_captura(
    pasta_saida: Path,
    momento: datetime | None = None,
) -> dict[str, str]:
    momento = momento or datetime.now().astimezone()

    return {
        "data_hora_captura": momento.strftime(
            "%d/%m/%Y %H:%M:%S"
        ),
        "data_hora_captura_iso": momento.isoformat(
            timespec="seconds"
        ),
        "referencia_captura": (
            "Produto capturado em "
            f"{momento.strftime('%d/%m/%Y às %H:%M:%S')}"
        ),
        "pasta_saida_execucao": pasta_saida.name,
        "caminho_saida_execucao": str(
            pasta_saida.resolve()
        ),
    }


def _valor_para_parquet(valor: Any) -> Any:
    if isinstance(
        valor,
        (dict, list, tuple, set),
    ):
        return json.dumps(
            valor,
            ensure_ascii=False,
            sort_keys=True,
        )
    return valor


def preparar_dataframe(
    linhas: list[dict[str, Any]],
    colunas_base: list[str],
) -> pd.DataFrame:
    linhas_validas = [
        linha
        for linha in linhas
        if str(linha.get("pid") or "").strip()
    ]

    linhas_normalizadas = [
        {
            chave: _valor_para_parquet(valor)
            for chave, valor in linha.items()
        }
        for linha in linhas_validas
    ]

    dataframe = pd.DataFrame(
        linhas_normalizadas,
    )
    dataframe = dataframe.reindex(
        columns=colunas_base,
    )

    colunas_numericas = {
        "altura_cm",
        "largura_cm",
        "espessura_cm",
        "maior_dimensao_cm",
        "segunda_dimensao_cm",
        "limite_altura_cm",
        "limite_largura_cm",
        "total_comentarios",
        "comentario_ordem",
    }

    for coluna in dataframe.columns:
        if coluna in colunas_numericas:
            dataframe[coluna] = pd.to_numeric(
                dataframe[coluna],
                errors="coerce",
            ).astype("float64")
        else:
            dataframe[coluna] = (
                dataframe[coluna]
                .where(
                    pd.notna(dataframe[coluna]),
                    "",
                )
                .astype("string")
            )

    return dataframe


def salvar_parquet_incremental(
    pasta_saida: Path,
    produtos: list[dict[str, Any]],
    comentarios: list[dict[str, Any]],
) -> None:
    dataframe_produtos = preparar_dataframe(
        produtos,
        PRODUCT_COLUMNS,
    )
    dataframe_produtos.to_parquet(
        pasta_saida / "products.parquet",
        index=False,
    )

    dataframe_comentarios = preparar_dataframe(
        comentarios,
        COMMENT_COLUMNS,
    )
    dataframe_comentarios.to_parquet(
        pasta_saida / "comments.parquet",
        index=False,
    )



def juntar_textos(
    valores: Iterable[Any],
    separador: str = " | ",
) -> str:
    resultado: list[str] = []

    for valor in valores:
        texto = str(valor or "").strip()
        if texto and texto not in resultado:
            resultado.append(texto)

    return separador.join(resultado)