from __future__ import annotations
import argparse
import sys
from pathlib import Path

from base_anatel import carregar_base_anatel
from crawler_playwright_shopee import rodar_playwright_shopee
from utils import log

def main() -> int:
    # Configura o leitor de argumentos do terminal
    parser = argparse.ArgumentParser(description="Crawler Shopee Unificado")
    parser.add_argument("--query", type=str, default="mini celular", help="Termo de busca")
    parser.add_argument("--limit", type=int, default=5, help="Limite de produtos a processar")
    parser.add_argument("--base", type=str, default="Produtos_Homologados_Anatel.csv", help="Caminho do CSV da Anatel")
    parser.add_argument("--mini-celulares", action="store_true", help="Filtro/Flag de mini celulares")

    args = parser.parse_args()

    log("main", "Iniciando Crawler Shopee Unificado (Padrão Mercado Livre)")
    
    # Carrega a base usando o caminho passado pelo terminal (ou o padrão)
    base = carregar_base_anatel(args.base)

    # Executa passando as variáveis capturadas do terminal
    resumo = rodar_playwright_shopee(
        query=args.query,
        limite=args.limit,
        base_anatel=base
    )

    log("main", "Execução finalizada.")
    print(resumo)
    return 0

if __name__ == "__main__":
    sys.exit(main())