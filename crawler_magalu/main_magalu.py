# -*- coding: utf-8 -*-
"""Entrada principal do crawler Magalu."""

from __future__ import annotations

import argparse
from pathlib import Path

from crawler_playwright_magalu import ConfigMagalu, run
from base_anatel import carregar_base_anatel


def montar_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Crawler Magalu para captura de anúncios suspeitos de mini celulares.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--txt", default="buscar_magalu.txt", help="Arquivo TXT com termos de busca.")
    parser.add_argument("--saida", help="Pasta de saída. Se vazio, cria com data e hora automática.")
    parser.add_argument("--base", help="CSV da base de produtos homologados da Anatel.")
    parser.add_argument("--limit", type=int, default=100, help="Máximo de registros salvos.")
    parser.add_argument("--max-paginas", type=int, default=2, help="Máximo de páginas de busca por termo.")
    parser.add_argument("--headless", action="store_true", help="Rodar sem abrir janela do navegador.")
    parser.add_argument("--slow-mo", type=int, default=0, help="Atraso do Playwright em ms entre ações.")
    parser.add_argument("--timeout-ms", type=int, default=30000, help="Timeout padrão das páginas.")
    parser.add_argument("--salvar-descartados", action="store_true", help="Também salvar produtos descartados no Parquet.")
    parser.add_argument("--limpar-prints", action="store_true", help="Apagar prints antigos antes de iniciar.")
    parser.add_argument("--pausar-inicio", action="store_true", help="Pausar no início para CEP/login/captcha manual.")
    return parser


def main() -> None:
    args = montar_parser().parse_args()
    base_anatel_carregada = carregar_base_anatel(args.base) if args.base else None

    config = ConfigMagalu(
        txt=args.txt,
        saida=Path(args.saida) if args.saida else None,
        base_anatel=base_anatel_carregada,
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