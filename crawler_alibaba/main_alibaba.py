# -*- coding: utf-8 -*-
from __future__ import annotations
import argparse
import asyncio
import sys

from base_anatel_alibaba import carregar_base_anatel
from crawler_playwright_alibaba import executar_crawler_alibaba
from utils_alibaba import ler_termos_txt

def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Crawler Alibaba unificado com regras ML.")
    parser.add_argument("--txt", default="buscar_alibaba.txt", help="TXT de buscas.")
    parser.add_argument("--limit", type=int, default=100, help="Limite de anúncios (0 = sem limite).")
    parser.add_argument("--max-paginas", type=int, default=2, help="Máximo de páginas.")
    parser.add_argument("--base", required=True, help="CSV Anatel.")
    parser.add_argument("--saida", help="Pasta de saída opcional.")
    parser.add_argument("--porta-chrome", type=int, default=9225, help="Porta CDP do Chrome.")
    return parser

def main() -> int:
    args = construir_parser().parse_args()
    try:
        consultas = ler_termos_txt(args.txt)
        base = carregar_base_anatel(args.base)
        asyncio.run(executar_crawler_alibaba(
            queries=consultas,
            base_anatel=base,
            saida=args.saida,
            limite=args.limit,
            max_paginas=args.max_paginas,
            porta_chrome=args.porta_chrome,
        ))
        return 0
    except KeyboardInterrupt:
        print("\nExecução interrompida pelo usuário.")
        return 130
    except Exception as exc:
        print(f"\n[ERRO] {exc}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())