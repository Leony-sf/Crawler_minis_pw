# -*- coding: utf-8 -*-
"""Orquestrador principal do crawler Magalu via CLI."""

import argparse
from pathlib import Path
from base_anatel import BaseAnatel
from crawler_playwright_magalu import ConfigMagalu, run


def main():
    parser = argparse.ArgumentParser(description="Crawler Magalu - Padrão CLI")
    parser.add_argument("--query", type=str, default="mini celular", help="Termo de busca no Magalu")
    parser.add_argument("--limit", type=int, default=100, help="Limite de anúncios únicos a coletar")
    parser.add_argument("--max-paginas", type=int, default=10, help="Número máximo de páginas/rolagens")
    parser.add_argument("--base", type=str, default="", help="Caminho para o arquivo CSV de homologação Anatel")
    parser.add_argument("--pausar-inicio", action="store_true", help="Pausar no início para resolução manual de captcha/login")
    parser.add_argument("--mini-celulares", action="store_true", help="Ativar regra específica para mini celulares")
    parser.add_argument("--mini-manter-sem-medida", action="store_true", help="Manter itens sem medida explícita de tamanho")
    parser.add_argument("--mini-largura-cm", type=float, default=5.5, help="Largura limite em cm para considerar mini celular")

    args = parser.parse_args()

    # Carrega a base Anatel se o caminho foi fornecido
    base_anatel = None
    if args.base:
        caminho_base = Path(args.base).expanduser().resolve()
        if caminho_base.is_file():
            # Passa o caminho e o nome da coluna de código do CSV da Anatel
            base_anatel = BaseAnatel(caminho_base, "Codigo")
        else:
            print(f"⚠️ Aviso: Arquivo da base Anatel não encontrado em: {caminho_base}")

    # Cria/Atualiza dinamicamente o arquivo de termos de busca com a query informada via CLI
    arquivo_txt = Path("buscar_magalu.txt")
    arquivo_txt.write_text(args.query, encoding="utf-8")

    # Configura o objeto de execução do crawler
    config = ConfigMagalu(
        txt=str(arquivo_txt),
        limit=args.limit,
        max_paginas=args.max_paginas,
        base_anatel=base_anatel,
        pausar_inicio=args.pausar_inicio,
        headless=False
    )

    # Executa o crawler do Magalu
    run(config)


if __name__ == "__main__":
    main()