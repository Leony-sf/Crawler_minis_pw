import os
import pandas as pd
from typing import List, Dict, Any

# Colunas padrão exigidas pelo dashboard Qlik
QLIK_COLUMNS = [
    "marketplace", "query", "title", "price", 
    "seller", "url", "anatel_code", "is_valid_anatel", 
    "is_accessory", "scraped_at"
]

def save_to_qlik_format(data: List[Dict[str, Any]], output_dir: str = "output", filename_prefix: str = "resultado"):
    """Exporta os resultados processados em CSV e Parquet mantendo a ordem exata das colunas."""
    if not data:
        print("Nenhum dado para exportar.")
        return

    os.makedirs(output_dir, exist_ok=True)
    df = pd.DataFrame(data)

    # Garante todas as colunas
    for col in QLIK_COLUMNS:
        if col not in df.columns:
            df[col] = None

    df = df[QLIK_COLUMNS]

    csv_path = os.path.join(output_dir, f"{filename_prefix}.csv")
    parquet_path = os.path.join(output_dir, f"{filename_prefix}.parquet")

    df.to_csv(csv_path, index=False, encoding="utf-8-sig", sep=";")
    df.to_parquet(parquet_path, index=False)

    print(f"[Qlik Export] Arquivos gerados com sucesso:")
    print(f" -> {csv_path}")
    print(f" -> {parquet_path}")