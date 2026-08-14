from __future__ import annotations

import argparse
import sys
import os

# Aponta para a pasta do Mercado Livre para reaproveitar as lógicas
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'ML_crawler')))

from base_anatel import carregar_base_anatel
from crawler_playwright_aliexpress import executar_sync
from utils_aliexpress import ler_buscas


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Crawler AliExpress integrado com a validação dimensional e Anatel do Mercado Livre."
    )
    parser.add_argument(
        "--txt",
        default="buscar_aliexpress.txt",
        help="Arquivo .txt com uma busca por linha.",
    )
    parser.add_argument(
        "--query",
        action="append",
        default=[],
        help="Busca adicional via terminal.",
    )
    parser.add_argument("--limit", type=int, default=50, help="Quantidade máxima de produtos visitados.")
    parser.add_argument("--max-paginas", type=int, default=1, help="Quantidade máxima de páginas por busca.")
    parser.add_argument("--saida", default=None, help="Deixe vazio para gerar pasta automática com data/hora.")
    parser.add_argument("--headless", action="store_true", help="Rodar sem abrir janela do navegador.")
    parser.add_argument("--sem-pausa-login", action="store_true", help="Não pausar para login/captcha antes de iniciar.")
    parser.add_argument("--perfil", default="perfil_aliexpress", help="Pasta de perfil persistente do navegador.")
    parser.add_argument("--base", help="CSV da base de produtos homologados da Anatel.")
    
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    queries = ler_buscas(args.txt, args.query)

    if not queries:
        queries = [
            "mini celular", "celular pequeno", "celular chave", "celular formato chave",
            "mini telefone", "micro celular", "tiny phone", "small mobile phone",
            "bluetooth dialer phone", "mini smartphone", "celular de bolso"
        ]
        print("[busca] Nenhum TXT/query encontrado. Usando buscas padrão genéricas.")

    base = carregar_base_anatel(args.base)

    executar_sync(
        queries=queries,
        saida=args.saida,
        limit=args.limit,
        max_paginas=args.max_paginas,
        headless=args.headless,
        pausa_login=not args.sem_pausa_login,
        user_data_dir=args.perfil,
        base_anatel=base
    )


if __name__ == "__main__":
    main()