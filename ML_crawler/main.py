import argparse
import sys
from pathlib import Path

from mercadolivre_crawler.base_anatel import carregar_base_anatel
from mercadolivre_crawler.crawler_playwright_ml import rodar_playwright_mercadolivre

def main():
    parser = argparse.ArgumentParser(
        description="Crawler do Mercado Livre para Auditoria Anatel / Mini Celulares"
    )

    # Argumentos principais
    parser.add_argument(
        "--query", 
        type=str, 
        default="celular", 
        help="Termos de busca separados por vírgula (ex: 'bm10,i17 pro,telefone dobrável')"
    )
    parser.add_argument(
        "--limit", 
        type=int, 
        default=0, 
        help="Limite TOTAL de anúncios a processar em toda a execução (0 = sem limite)"
    )
    parser.add_argument(
        "--limite-por-query", 
        type=int, 
        default=0, 
        help="Quantidade de anúncios para analisar antes de trocar de termo de busca (0 = sem limite)"
    )
    parser.add_argument(
        "--max-paginas", 
        type=int, 
        default=0, 
        help="Máximo de páginas para navegar por termo de busca (0 = sem limite)"
    )
    parser.add_argument(
        "--base", 
        type=str, 
        help="Caminho para o arquivo CSV da base de dados da Anatel"
    )

    # Filtros e flags de comportamento
    parser.add_argument(
        "--compras-internacionais", 
        action="store_true", 
        help="Ativa o filtro do Mercado Livre para buscar APENAS compras internacionais"
    )
    parser.add_argument(
        "--mini-celulares", 
        action="store_true", 
        help="Ativa os filtros rigorosos de detecção de mini celulares/ilícitos"
    )
    parser.add_argument(
        "--mini-manter-sem-medida", 
        action="store_true", 
        help="Mantém na planilha de suspeitos os anúncios de mini celulares que não possuem dimensões informadas"
    )
    parser.add_argument(
        "--mini-maior-cm", 
        type=float, 
        default=12.0, 
        help="Tamanho máximo tolerado para o maior eixo em cm (padrão: 8.5)"
    )
    parser.add_argument(
        "--mini-largura-cm", 
        type=float, 
        default=5.5, 
        help="Tamanho máximo tolerado para a largura em cm (padrão: 5.5)"
    )

    args = parser.parse_args()

    print("\n" + "="*60)
    print(" INICIANDO AUDITORIA DO MERCADO LIVRE ")
    print("="*60)

    # 1. Carregar a Base da Anatel
    base = None
    if args.base:
        caminho_base = Path(args.base)
        if not caminho_base.exists():
            print(f"\n[ERRO] O arquivo da base Anatel não foi encontrado: {args.base}")
            sys.exit(1)
            
        print(f"[*] Carregando base da Anatel: {args.base}...")
        try:
            base = carregar_base_anatel(args.base)
        except Exception as e:
            print(f"\n[ERRO] Falha ao ler a base da Anatel: {e}")
            sys.exit(1)
    else:
        print("[!] Nenhuma base Anatel fornecida. O bot rodará apenas verificações de texto.")

    # 2. Fatiar os termos de pesquisa por vírgula e limpar espaços extras
    queries_lista = [q.strip() for q in args.query.split(",") if q.strip()]

    # 3. Rodar o Crawler
    try:
        resultados = rodar_playwright_mercadolivre(
            query=args.query,
            queries=queries_lista,
            limite=args.limit,
            limite_por_query=args.limite_por_query,
            base_anatel=base,
            max_paginas=args.max_paginas,
            mini_celulares=args.mini_celulares,
            mini_maior_cm=args.mini_maior_cm,
            mini_largura_cm=args.mini_largura_cm,
            mini_manter_sem_medida=args.mini_manter_sem_medida,
            somente_internacional=args.compras_internacionais,
        )
        print("\n[*] Extração finalizada com sucesso!")
        
    except KeyboardInterrupt:
        print("\n[!] Execução interrompida pelo usuário.")
        sys.exit(0)
    except Exception as e:
        print(f"\n[ERRO] Falha crítica durante o crawler: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()