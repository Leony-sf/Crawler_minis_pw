from __future__ import annotations
import argparse
import sys
from pathlib import Path

from base_anatel import carregar_base_anatel
from crawler_playwright_shopee import rodar_playwright_shopee
from utils import log, ler_termos_txt # Importamos a função de ler o txt aqui

def main() -> int:
    # Configura o leitor de argumentos do terminal
    parser = argparse.ArgumentParser(description="Crawler Shopee Unificado")
    parser.add_argument("--query", type=str, default="mini celular", help="Termo de busca único")
    parser.add_argument("--txt", type=str, default="", help="Caminho para arquivo txt com lista de buscas") # Nova tag
    parser.add_argument("--limit", type=int, default=5, help="Limite de produtos a processar por execução")
    parser.add_argument("--base", type=str, default="Produtos_Homologados_Anatel.csv", help="Caminho do CSV da Anatel")
    parser.add_argument("--mini-celulares", action="store_true", help="Filtro/Flag de mini celulares")
    parser.add_argument("--login-manual", action="store_true", help="Pausa o crawler no início para login e aceite de cookies na Shopee.")

    args = parser.parse_args()

    log("main", "Iniciando Crawler Shopee Unificado (Padrão Mercado Livre)")
    
    # Se o usuário passou um arquivo txt, nós lemos ele
    lista_buscas = None
    if args.txt:
        try:
            lista_buscas = ler_termos_txt(args.txt)
            log("main", f"Carregados {len(lista_buscas)} termos de busca do arquivo {args.txt}")
        except Exception as e:
            log("erro", f"Falha ao ler o arquivo txt: {e}")
            return 1

    # Carrega a base usando o caminho passado pelo terminal
    base = carregar_base_anatel(args.base)

    # Executa passando a lista de buscas
    resumo = rodar_playwright_shopee(
        query=args.query,
        limite=args.limit,
        base_anatel=base,
        queries=lista_buscas, # Repassando a lista para o crawler
        esperar_login=args.login_manual 
    )

    log("main", "Execução finalizada.")
    print(resumo)
    return 0

if __name__ == "__main__":
    sys.exit(main())