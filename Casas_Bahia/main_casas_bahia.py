# -*- coding: utf-8 -*-
"""Entrada do crawler Casas Bahia."""

from __future__ import annotations

import argparse
from pathlib import Path

from crawler_playwright_casas_bahia import ConfigCasasBahia, run


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Crawler Casas Bahia — mini celulares")
    parser.add_argument("--txt", default="buscar_casas_bahia.txt", help="Arquivo TXT com termos de busca.")
    parser.add_argument("--saida", default="saidas_casas_bahia", help="Pasta de saída.")
    parser.add_argument("--perfil", default="perfil_casas_bahia", help="Pasta de perfil persistente do navegador.")
    parser.add_argument("--limit", type=int, default=100, help="Limite total de produtos analisados.")
    parser.add_argument("--max-paginas", type=int, default=2, help="Máximo de páginas por termo.")
    parser.add_argument("--headless", action="store_true", help="Executar sem abrir janela.")
    parser.add_argument("--slow-mo", type=int, default=0, help="Atraso em ms entre ações do Playwright.")
    parser.add_argument("--timeout-ms", type=int, default=30000, help="Timeout padrão em milissegundos.")
    parser.add_argument("--salvar-descartados", action="store_true", help="Salvar também produtos descartados no parquet.")
    parser.add_argument("--limpar-prints", action="store_true", help="Limpar pasta de prints antes de iniciar.")
    parser.add_argument("--pausar-inicio", action="store_true", help="Pausar no início para cookies/captcha.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    config = ConfigCasasBahia(
        txt=args.txt,
        saida=Path(args.saida),
        perfil=Path(args.perfil),
        limit=args.limit,
        max_paginas=args.max_paginas,
        headless=args.headless,
        slow_mo=args.slow_mo,
        timeout_ms=args.timeout_ms,
        salvar_descartados=args.salvar_descartados,
        limpar_prints=args.limpar_prints,
        pausar_inicio=args.pausar_inicio,
    )

    run(config)


if __name__ == "__main__":
    main()
