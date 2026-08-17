# -*- coding: utf-8 -*-
"""Entrada principal do crawler Carrefour."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from crawler_playwright_carrefour import ConfigCarrefour, executar_crawler_carrefour


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Crawler Carrefour para mini celulares por dimensão física <= 80 mm.")
    parser.add_argument("--txt", default="buscar_carrefour.txt", help="Arquivo TXT com termos de busca.")
    parser.add_argument("--saida", default="saidas_carrefour", help="Pasta de saída.")
    parser.add_argument("--limit", type=int, default=100, help="Quantidade máxima de produtos analisados, incluindo descartados.")
    parser.add_argument("--max-paginas", type=int, default=1, help="Máximo de páginas por termo.")
    parser.add_argument("--headless", action="store_true", help="Executa sem abrir janela do navegador.")
    parser.add_argument("--slow-mo", type=int, default=0, help="Atraso em ms entre ações do Playwright.")
    parser.add_argument("--timeout-ms", type=int, default=30000, help="Timeout em milissegundos.")
    parser.add_argument("--salvar-descartados", action="store_true", help="Também salva produtos descartados no products.parquet.")
    parser.add_argument("--limpar-prints", action="store_true", help="Remove prints antigos antes da execução.")
    parser.add_argument("--pausar-inicio", action="store_true", help="Abre a busca e pausa para login/captcha/CEP antes de coletar.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = ConfigCarrefour(
        txt=args.txt,
        saida=Path(args.saida),
        limit=args.limit,
        max_paginas=args.max_paginas,
        headless=args.headless,
        slow_mo=args.slow_mo,
        timeout_ms=args.timeout_ms,
        salvar_descartados=args.salvar_descartados,
        limpar_prints=args.limpar_prints,
        pausar_inicio=args.pausar_inicio,
    )
    asyncio.run(executar_crawler_carrefour(config))


if __name__ == "__main__":
    main()
