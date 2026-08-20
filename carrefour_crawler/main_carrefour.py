# -*- coding: utf-8 -*-
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Agora ele vai conseguir importar isso, desde que o base_anatel.py esteja na mesma pasta
from base_anatel import carregar_base_anatel
from crawler_playwright_carrefour import rodar_playwright_carrefour
from utils_carrefour import carregar_termos_busca


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Crawler Carrefour padronizado.")
    parser.add_argument("--query", default="celular", help="Termos separados por vírgula.")
    parser.add_argument("--txt", help="TXT com um termo de busca por linha.")
    parser.add_argument("--limit", type=int, default=0, help="Limite total de anúncios (0 = sem limite).")
    parser.add_argument("--max-paginas", type=int, default=0, help="Máximo de páginas por termo.")
    parser.add_argument("--base", help="Caminho para o CSV da base de produtos homologados da Anatel.")
    parser.add_argument("--saida", help="Pasta de saída opcional.")
    parser.add_argument("--url", help="URL direta de uma listagem do Carrefour.")
    parser.add_argument("--sem-pausa", action="store_true", help="Não aguarda ENTER antes da coleta.")
    parser.add_argument("--porta-chrome", type=int, default=9225, help="Porta do Chrome (uso opcional).")
    return parser


def main() -> int:
    args = construir_parser().parse_args()

    try:
        if args.txt:
            consultas = carregar_termos_busca(args.txt)
            query_principal = consultas[0]
        else:
            consultas = [
                item.strip()
                for item in str(args.query or "celular").split(",")
                if item.strip()
            ]
            query_principal = consultas[0] if consultas else "celular"

        # Carrega a base da Anatel usando o mesmo padrão do ML
        base = carregar_base_anatel(args.base) if args.base else None

        # Roda o bot assíncrono do Carrefour
        asyncio.run(
            rodar_playwright_carrefour(
                query=query_principal,
                queries=consultas,
                limite=args.limit,
                base_anatel=base,
                url=args.url,
                saida=args.saida,
                max_paginas=args.max_paginas,
                pausar_inicio=not args.sem_pausa,
                porta_chrome=args.porta_chrome,
            )
        )
        return 0

    except KeyboardInterrupt:
        print("\nExecução interrompida pelo usuário.")
        return 130
    except Exception as exc:
        print(f"\n[ERRO] {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())