from __future__ import annotations

import argparse
import sys
from pathlib import Path
from pprint import pprint

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from amazon_crawler.base_anatel import carregar_base_anatel
from amazon_crawler.crawler_playwright_amazon import rodar_playwright_amazon
from amazon_crawler.utils import log, secao

def _ler_queries_txt(caminho: str | Path | None) -> list[str]:
    if not caminho:
        return []

    caminho = Path(caminho).expanduser().resolve()
    if not caminho.is_file():
        raise FileNotFoundError(f"Arquivo de buscas não encontrado: {caminho}")

    consultas: list[str] = []
    vistos: set[str] = set()

    for linha in caminho.read_text(encoding="utf-8-sig").splitlines():
        q = linha.strip()
        if not q or q.startswith("#"):
            continue

        chave = " ".join(q.lower().split())
        if chave in vistos:
            continue

        vistos.add(chave)
        consultas.append(q)

    if not consultas:
        raise ValueError(f"O arquivo de buscas está vazio ou só possui comentários: {caminho}")

    return consultas

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Crawler Amazon Playwright com validação ANATEL (Padrão Mercado Livre)"
    )

    origem = parser.add_mutually_exclusive_group(required=True)
    origem.add_argument(
        "--txt",
        help="Arquivo .txt com uma busca por linha (Obrigatório).",
    )
    origem.add_argument(
        "--url",
        help="URL direta de listagem (Ignora o TXT).",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Quantidade máxima TOTAL de produtos a analisar. Use 0 para sem limite.",
    )
    parser.add_argument(
        "--base",
        help="Caminho do CSV Produtos_Homologados_Anatel.csv.",
    )
    parser.add_argument(
        "--saida",
        help="Pasta de saída opcional.",
    )
    parser.add_argument(
        "--max-paginas",
        type=int,
        default=0,
        help="Máximo de páginas da listagem POR BUSCA. Use 0 para sem limite.",
    )
    parser.add_argument(
        "--sem-vendedor",
        action="store_true",
        help="Desativa a análise de vendedor.",
    )
    parser.add_argument(
        "--prefix-len",
        type=int,
        default=5,
        help="Quantidade de dígitos do prefixo usado na validação ANATEL.",
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

    return parser.parse_args()

def main() -> None:
    args = parse_args()

    try:
        if args.url:
            consultas = []
            query_principal = "URL Direta"
        else:
            consultas = _ler_queries_txt(args.txt)
            query_principal = consultas[0]

        secao("Início do crawler Amazon")
        log("main", f"Busca principal: {query_principal}")
        log("main", f"URL direta: {args.url or 'não informada'}")
        log("main", f"Arquivo TXT: {args.txt or 'não informado'}")
        log("main", f"Limite total: {'sem limite' if args.limit <= 0 else args.limit}")
        log("main", f"Máximo de páginas: {'sem limite' if args.max_paginas <= 0 else args.max_paginas}")
        log("main", f"Análise de vendedor: {'NÃO' if args.sem_vendedor else 'SIM'}")
        log("main", "Filtro de dimensões 12x5,5cm: ATIVADO (Obrigatório)")

        base = carregar_base_anatel(args.base, prefix_len=args.prefix_len)

        resumo = rodar_playwright_amazon(
            query=query_principal,
            queries=consultas,
            limite=args.limit,
            base_anatel=base,
            url=args.url,
            saida=args.saida,
            max_paginas=args.max_paginas,
            analisar_vendedor=not args.sem_vendedor,
            pausar_inicio=not args.sem_pausa,
            porta_chrome=args.porta_chrome,
        )

        secao("Resumo final")
        pprint(resumo)

    except KeyboardInterrupt:
        print("\n[interrompido] Execução cancelada pelo usuário.")
    except Exception as exc:
        print(f"\n[erro fatal] {type(exc).__name__}: {exc}")
        raise

if __name__ == "__main__":
    main()