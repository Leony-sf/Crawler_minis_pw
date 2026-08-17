from __future__ import annotations

import argparse
import sys
from pathlib import Path
from pprint import pprint


# ============================================================
# Permite rodar tanto:
# python main.py
# quanto:
# python -m amazon_crawler.main
# ============================================================

CURRENT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = CURRENT_DIR.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


from amazon_crawler.base_anatel import carregar_base_anatel
from amazon_crawler.crawler_playwright_amazon import rodar_playwright_amazon
from amazon_crawler.utils import log, secao


def _ler_queries_txt(caminho: str | Path | None) -> list[str]:
    """Lê um arquivo .txt com uma busca por linha.

    Linhas vazias e linhas começando com # são ignoradas.
    O arquivo pode ficar fora da pasta do crawler; basta passar o caminho correto.
    """
    if not caminho:
        return []

    caminho = Path(caminho)
    if not caminho.exists():
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
        description="Crawler Amazon Playwright com validação ANATEL"
    )

    parser.add_argument(
        "--query",
        default="celular",
        help="Termo de busca na Amazon.",
    )

    parser.add_argument(
        "--queries-file",
        default=None,
        help="Arquivo .txt com uma busca por linha. Se informado, executa todas as buscas do arquivo.",
    )

    parser.add_argument(
        "--url",
        default=None,
        help="URL direta de listagem. Se informada, ignora --query e --queries-file.",
    )

    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Quantidade máxima TOTAL de produtos a analisar. Use 0 para não limitar por produto.",
    )

    parser.add_argument(
        "--base",
        default=None,
        help="Caminho do CSV Produtos_Homologados_Anatel.csv.",
    )

    parser.add_argument(
        "--headless",
        action="store_true",
        help="Roda o navegador sem interface visual.",
    )

    parser.add_argument(
        "--saida",
        default=None,
        help="Pasta de saída. Se omitida, cria uma pasta com data/hora em saidas/.",
    )

    parser.add_argument(
        "--max-paginas",
        type=int,
        default=0,
        help="Máximo de páginas da listagem POR BUSCA. Use 0 para rodar até não existir próxima página.",
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
        "--mini-celulares",
        action="store_true",
        help="Ativa filtro para mini celulares com limite de tamanho e fila de suspeitos manuais.",
    )

    parser.add_argument(
        "--mini-maior-cm",
        "--mini-maior-eixo-cm",
        dest="mini_maior_cm",
        type=float,
        default=12.0,
        help="Maior dimensão/eixo permitido para mini celular em centímetros. Padrão: 12,0 cm.",
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


def run_crawler(args: argparse.Namespace) -> dict:
    consultas = [] if args.url else _ler_queries_txt(args.queries_file)

    secao("Início do crawler Amazon")
    if consultas:
        log("main", f"Arquivo de buscas: {args.queries_file}")
        log("main", f"Buscas carregadas: {len(consultas)}")
        for i, consulta in enumerate(consultas[:10], start=1):
            log("main", f"Busca {i}: {consulta}")
        if len(consultas) > 10:
            log("main", f"... +{len(consultas) - 10} buscas")
    else:
        log("main", f"Busca: {args.query}")

    log("main", f"URL direta: {args.url or 'não informada'}")
    log("main", f"Limite total: {'sem limite' if args.limit <= 0 else args.limit}")
    log("main", f"Máximo de páginas por busca: {'sem limite' if args.max_paginas <= 0 else args.max_paginas}")
    log("main", f"Base: {args.base or 'não informada'}")
    log("main", f"Análise de vendedor: {'NÃO' if args.sem_vendedor else 'SIM'}")
    if args.mini_celulares:
        log("main", "Modo mini celulares: ativado")
        log("main", f"Limites mini: maior eixo <= {args.mini_maior_cm} cm | largura <= {args.mini_largura_cm} cm")
        log("main", "Suspeitos manuais: products_suspeitos_mini.parquet")

    secao("Base ANATEL")
    base = carregar_base_anatel(args.base, prefix_len=args.prefix_len)

    resumo = rodar_playwright_amazon(
        query=args.query,
        queries=consultas,
        limite=args.limit,
        base_anatel=base,
        headless=args.headless,
        url=args.url,
        saida=args.saida,
        max_paginas=args.max_paginas,
        analisar_vendedor=not args.sem_vendedor,
        mini_celulares=args.mini_celulares,
        mini_maior_cm=args.mini_maior_cm,
        mini_largura_cm=args.mini_largura_cm,
        mini_manter_sem_medida=args.mini_manter_sem_medida,
    )

    return resumo


def main() -> None:
    args = parse_args()

    try:
        resumo = run_crawler(args)

        secao("Resumo final")
        pprint(resumo)

    except KeyboardInterrupt:
        print("\n[interrompido] Execução cancelada pelo usuário.")

    except Exception as exc:
        print(f"\n[erro fatal] {type(exc).__name__}: {exc}")
        raise


if __name__ == "__main__":
    main()