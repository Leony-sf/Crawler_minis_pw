from __future__ import annotations
import sys
from pathlib import Path

from base_anatel import carregar_base_anatel
from crawler_playwright_shopee import rodar_playwright_shopee
from utils import log

def main() -> int:
    log("main", "Iniciando Crawler Shopee Unificado (Padrão Mercado Livre)")
    
    # Substitua pelo caminho do seu CSV real
    caminho_base = "Produtos_Homologados_Anatel.csv"
    base = carregar_base_anatel(caminho_base)

    resumo = rodar_playwright_shopee(
        query="mini celular",
        limite=5,
        base_anatel=base
    )

    log("main", "Execução finalizada.")
    print(resumo)
    return 0

if __name__ == "__main__":
    sys.exit(main())