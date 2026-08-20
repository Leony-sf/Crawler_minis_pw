# -*- coding: utf-8 -*-
from __future__ import annotations
import argparse
import asyncio
from pathlib import Path
from crawler_playwright_americanas import ConfigAmericanas, executar_crawler_americanas
from utils_americanas import criar_pastas_saida
try:
    from base_anatel import carregar_base_anatel
except ImportError:
    carregar_base_anatel = lambda x: None

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Crawler Americanas.com Padronizado.")
    parser.add_argument("--txt", default="buscar_americanas.txt", help="Arquivo TXT com termos.")
    parser.add_argument("--saida", default="saidas_americanas", help="Pasta de saída.")
    parser.add_argument("--limit", type=int, default=100, help="Máximo de produtos analisados.")
    parser.add_argument("--max-paginas", type=int, default=1, help="Máximo de páginas por termo.")
    parser.add_argument("--headless", action="store_true", help="Ocultar navegador.")
    parser.add_argument("--slow-mo", type=int, default=0, help="Atraso em ms.")
    parser.add_argument("--timeout-ms", type=int, default=30000, help="Timeout em ms.")
    parser.add_argument("--salvar-descartados", action="store_true", help="Salva descartados.")
    parser.add_argument("--pausar-inicio", action="store_true", help="Pausa para captcha.")
    parser.add_argument("--base", help="CSV da base Anatel.")
    return parser.parse_args()

def main() -> None:
    args = parse_args()
    pasta_saida = criar_pastas_saida(args.saida)
    base_anatel = carregar_base_anatel(args.base) if args.base else None

    config = ConfigAmericanas(
        txt=args.txt,
        saida=pasta_saida,
        limit=args.limit,
        max_paginas=args.max_paginas,
        headless=args.headless,
        slow_mo=args.slow_mo,
        timeout_ms=args.timeout_ms,
        salvar_descartados=args.salvar_descartados,
        pausar_inicio=args.pausar_inicio,
        base_anatel=base_anatel,
    )
    asyncio.run(executar_crawler_americanas(config))

if __name__ == "__main__":
    main()