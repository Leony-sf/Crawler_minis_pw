# -*- coding: utf-8 -*-
from __future__ import annotations
import argparse
import asyncio
import sys
from pathlib import Path

from base_anatel_alibaba import carregar_base_anatel
from crawler_playwright_alibaba import executar_crawler_alibaba, ConfigAlibaba

def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Crawler Alibaba unificado com regras ML.")
    parser.add_argument("--txt", default="buscar_alibaba.txt", help="TXT de buscas.")
    parser.add_argument("--limit", type=int, default=100, help="Limite de anúncios (0 = sem limite).")
    parser.add_argument("--max-paginas", type=int, default=2, help="Máximo de páginas.")
    parser.add_argument("--base", required=True, help="CSV Anatel.")
    parser.add_argument("--saida", help="Pasta de saída opcional.")
    parser.add_argument("--porta-chrome", type=int, default=9225, help="Porta CDP do Chrome.")
    parser.add_argument("--sem-pausa", action="store_true", help="Não aguarda ENTER antes da coleta.")
    return parser

def main() -> int:
    args = construir_parser().parse_args()
    try:
        # Carrega a base da Anatel
        base = carregar_base_anatel(args.base)
        
        # Cria a configuração (passando None no args.saida ativa a criação automática de pasta com data e hora)
        config = ConfigAlibaba(
            txt=args.txt,
            saida=args.saida,  # <--- A mágica está aqui!
            limit=args.limit,
            max_paginas=args.max_paginas,
            base_anatel=base,
            pausar_inicio=not args.sem_pausa
        )
        
        # Roda o crawler
        asyncio.run(executar_crawler_alibaba(config))
        return 0
    except KeyboardInterrupt:
        print("\nExecução interrompida pelo usuário.")
        return 130
    except Exception as exc:
        print(f"\n[ERRO] {exc}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    sys.exit(main())