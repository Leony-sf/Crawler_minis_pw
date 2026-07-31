from __future__ import annotations

import argparse
import sys
from pathlib import Path
from pprint import pprint

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from Shopee_crawler.base_anatel import carregar_base_anatel
from Shopee_crawler.crawler_playwright_shopee import rodar_playwright_shopee
from Shopee_crawler.utils import log, secao


def parse_args():
    parser = argparse.ArgumentParser(
        description="Crawler Shopee com validação ANATEL"
    )

    parser.add_argument(
        "--max-pages",
        type=int,
        default=3,
        help="Quantidade máxima de páginas da busca da Shopee para percorrer.",
    )

    parser.add_argument(
        "--query",
        default="smartphone",
        help="Termo de busca na Shopee.",
    )

    parser.add_argument(
        "--url",
        default=None,
        help="URL direta de listagem. Se informada, ignora --query.",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Quantidade máxima de produtos a analisar.",
    )

    parser.add_argument(
        "--base",
        default=None,
        help="Caminho do CSV da base Produtos_Homologados_Anatel.csv.",
    )

    parser.add_argument(
        "--headless",
        action="store_true",
        help="Roda o navegador sem interface visual. Para Shopee, recomendo NÃO usar.",
    )

    parser.add_argument(
        "--login-manual",
        action="store_true",
        help="Força abrir a tela de login da Shopee e pausar para login manual.",
    )

    parser.add_argument(
        "--queries-file",
        default=None,
        help="Arquivo .txt com uma busca por linha. Se informado, roda todas as buscas e deduplica os links.",
    )

    parser.add_argument(
        "--mini-celulares",
        action="store_true",
        help="Ativa filtro para mini celulares com limite dimensional.",
    )

    parser.add_argument(
        "--mini-maior-cm",
        "--mini-maior-eixo-cm",
        dest="mini_maior_cm",
        type=float,
        default=12.0,
        help="Maior eixo permitido para mini celular em centímetros. Padrão: 8,5 cm.",
    )

    parser.add_argument(
        "--mini-largura-cm",
        type=float,
        default=5.5,
        help="Largura máxima permitida para mini celular em centímetros. Padrão: 5,5 cm.",
    )

    parser.add_argument(
        "--mini-manter-sem-medida",
        action="store_true",
        help="Mantém na planilha principal anúncios que parecem mini celular, mas não informam medida explícita.",
    )


    return parser.parse_args()



def carregar_queries_txt(caminho: str | None) -> list[str]:
    if not caminho:
        return []

    path = Path(caminho)

    if not path.exists():
        raise FileNotFoundError(f"Arquivo de buscas não encontrado: {path}")

    queries: list[str] = []
    vistos: set[str] = set()

    for linha in path.read_text(encoding="utf-8-sig").splitlines():
        termo = linha.strip()

        if not termo or termo.startswith("#"):
            continue

        chave = termo.lower()

        if chave in vistos:
            continue

        vistos.add(chave)
        queries.append(termo)

    if not queries:
        raise ValueError(f"Arquivo de buscas está vazio ou só possui comentários: {path}")

    return queries

def main():
    args = parse_args()

    queries = carregar_queries_txt(args.queries_file)

    secao("Início do crawler Shopee")

    if queries:
        log("main", f"Arquivo de buscas: {args.queries_file}")
        log("main", f"Buscas carregadas: {len(queries)}")
    else:
        log("main", f"Busca: {args.query}")

    log("main", f"Limite total: {args.limit}")
    log("main", f"Máximo de páginas por busca: {args.max_pages}")

    if args.base:
        log("main", f"Base: {args.base}")
    else:
        log("main", "Base: não informada")

    if args.mini_celulares:
        log("main", "Modo mini celulares: ativado")
        log("main", f"Limites mini: maior eixo <= {args.mini_maior_cm} cm | largura <= {args.mini_largura_cm} cm")

    secao("Base ANATEL")
    base = carregar_base_anatel(args.base)

    resumo = rodar_playwright_shopee(
        query=args.query,
        queries=queries,
        limite=args.limit,
        base_anatel=base,
        headless=args.headless,
        url=args.url,
        login_manual=args.login_manual,
        max_paginas=args.max_pages,
        mini_celulares=args.mini_celulares,
        mini_maior_cm=args.mini_maior_cm,
        mini_largura_cm=args.mini_largura_cm,
        mini_manter_sem_medida=args.mini_manter_sem_medida,
    )

    secao("Resumo final")
    pprint(resumo)


if __name__ == "__main__":
    main()