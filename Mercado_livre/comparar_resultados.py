from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def carregar(caminho: str | Path) -> pd.DataFrame:
    path = Path(caminho).expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)

    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    if path.suffix.lower() == ".csv":
        return pd.read_csv(path, dtype=str, keep_default_na=False)

    raise ValueError("Use arquivo .parquet ou .csv.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compara duas execuções do crawler Mercado Livre."
    )
    parser.add_argument("--anterior", required=True)
    parser.add_argument("--atual", required=True)
    parser.add_argument(
        "--saida",
        default="comparacao_resultados.xlsx",
    )
    args = parser.parse_args()

    anterior = carregar(args.anterior)
    atual = carregar(args.atual)

    chave = "url" if "url" in anterior.columns and "url" in atual.columns else "id_produto"

    colunas = [
        chave,
        "titulo",
        "classificacao",
        "situacao_anatel",
        "data_hora_captura",
    ]
    colunas_anterior = [c for c in colunas if c in anterior.columns]
    colunas_atual = [c for c in colunas if c in atual.columns]

    comparacao = anterior[colunas_anterior].merge(
        atual[colunas_atual],
        on=chave,
        how="outer",
        suffixes=("_anterior", "_atual"),
        indicator=True,
    )

    saida = Path(args.saida).expanduser().resolve()
    comparacao.to_excel(saida, index=False)
    print(f"Comparação salva em: {saida}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
