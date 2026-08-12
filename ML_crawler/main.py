from __future__ import annotations

import argparse
import sys

from base_anatel import carregar_base_anatel
from crawler_playwright_ml import rodar_playwright_mercadolivre
from utils import ler_termos_txt


def construir_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Crawler Mercado Livre para triagem de mini celulares "
            "com limite de 120 x 55 mm."
        )
    )

    origem = parser.add_mutually_exclusive_group()
    origem.add_argument(
        "--query",
        default="celular",
        help="Termos separados por vírgula.",
    )
    origem.add_argument(
        "--txt",
        help="TXT com um termo de busca por linha.",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limite total de anúncios; 0 significa sem limite.",
    )
    parser.add_argument(
        "--limite-por-query",
        type=int,
        default=0,
        help="Limite por termo; 0 significa sem limite.",
    )
    parser.add_argument(
        "--max-paginas",
        type=int,
        default=0,
        help="Máximo de páginas por termo; 0 significa sem limite.",
    )
    parser.add_argument(
        "--base",
        help="CSV da base de produtos homologados da Anatel.",
    )
    parser.add_argument(
        "--saida",
        help=(
            "Pasta de saída opcional. Sem este argumento, cria "
            "Saidas_Mercadolivre_DD-MM_HH-MM."
        ),
    )
    parser.add_argument(
        "--url",
        help="URL direta de uma listagem do Mercado Livre.",
    )
    parser.add_argument(
        "--compras-internacionais",
        action="store_true",
        help="Ativa o filtro de compras internacionais.",
    )
    parser.add_argument(
        "--sem-comentarios",
        action="store_true",
        help="Não coleta comentários.",
    )
    parser.add_argument(
        "--sem-pausa",
        action="store_true",
        help="Não aguarda ENTER antes da coleta.",
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
        if args.txt:
            consultas = ler_termos_txt(args.txt)
            query_principal = consultas[0]
        else:
            consultas = [
                item.strip()
                for item in str(args.query or "celular").split(",")
                if item.strip()
            ]
            query_principal = consultas[0] if consultas else "celular"

        base = carregar_base_anatel(args.base)

        rodar_playwright_mercadolivre(
            query=query_principal,
            queries=consultas,
            limite=args.limit,
            limite_por_query=args.limite_por_query,
            base_anatel=base,
            url=args.url,
            saida=args.saida,
            max_paginas=args.max_paginas,
            somente_internacional=args.compras_internacionais,
            capturar_comentarios=not args.sem_comentarios,
            pausar_inicio=not args.sem_pausa,
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
