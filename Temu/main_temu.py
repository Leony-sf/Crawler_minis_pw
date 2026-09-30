from __future__ import annotations
import argparse
import sys

# Importa as funções que criamos nos passos anteriores
from base_anatel import carregar_base_anatel
from crawler_playwright_temu import rodar_playwright_temu

def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Crawler Temu para triagem de mini celulares."
    )
    parser.add_argument(
        "--query",
        default="mini celular",
        help="Termo de busca na Temu.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limite de produtos para capturar (0 = sem limite).",
    )
    parser.add_argument(
        "--base",
        help="CSV da base de produtos homologados da Anatel.",
    )
    parser.add_argument(
        "--porta-chrome",
        type=int,
        default=9225,
        help="Porta do Chrome já aberto com depuração remota. Padrão: 9225.",
    )
    return parser

def main() -> int:
    args = construir_parser().parse_args()

    try:
        base = carregar_base_anatel(args.base) if args.base else None

        rodar_playwright_temu(
            query=args.query,
            limite=args.limit,
            base_anatel=base,
            porta_chrome=args.porta_chrome,
        )
        return 0

    except KeyboardInterrupt:
        print("\nExecução interrompida pelo usuário.")
        return 130
    except Exception as exc:
        print(f"\n[ERRO] {exc}", file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())