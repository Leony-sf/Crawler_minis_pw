import argparse
from core.base_anatel import AnatelValidator, normalize_item
from core.exporter import save_to_qlik_format

# Exemplo de mapeamento para as funções de busca existentes nos subdiretórios
MARKETPLACE_MAP = {
    "ml": "Mercado_livre",
    "amazon": "Amazon",
    "shopee": "Shopee",
    "magalu": "Magalu",
    "casas_bahia": "Casas_Bahia",
    "carrefour": "Carrefour",
    "americanas": "Americanas",
    "aliexpress": "Aliexpress",
    "alibaba": "Alibaba",
    "temu": "Temu"
}

def run_crawler(marketplace: str, query: str, limit: int = 20):
    """Função stub para integração com o crawler real de cada pasta."""
    print(f"-> Executando busca no [{marketplace}] para a query '{query}' (limite: {limit})...")
    
    # Aqui é chamado a função principal de extração de cada pasta
    # Retorno de exemplo:
    return [
        {
            "marketplace": marketplace,
            "query": query,
            "title": f"Mini Celular L8star BM10 - {marketplace.upper()}",
            "price": "129,90",
            "seller": "Vendedor Exemplo",
            "url": f"https://{marketplace}.com/item-exemplo",
            "anatel_code": "012345678901",
            "is_valid_anatel": True
        }
    ]

def main():
    parser = argparse.ArgumentParser(description="Orquestrador Central de Crawlers de Marketplaces")
    parser.add_argument("--marketplaces", "-m", type=str, required=True, 
                        help="Lista separada por vírgula (ex: ml,amazon,shopee)")
    parser.add_argument("--query", "-q", type=str, required=True, 
                        help="Termo de busca (ex: 'mini celular')")
    parser.add_argument("--limit", "-l", type=int, default=50, 
                        help="Limite de anúncios por marketplace")

    args = parser.parse_args()
    selected_mks = [m.strip().lower() for m in args.marketplaces.split(",")]

    validator = AnatelValidator()
    all_results = []

    for mk in selected_mks:
        if mk in MARKETPLACE_MAP:
            raw_items = run_crawler(mk, args.query, limit=args.limit)
            for item in raw_items:
                norm = normalize_item(item)
                norm["is_valid_anatel"] = validator.is_homologated(norm["anatel_code"])
                all_results.append(norm)
        else:
            print(f"Aviso: Marketplace '{mk}' não é reconhecido. Opções: {list(MARKETPLACE_MAP.keys())}")

    # Exporta no formato para o Qlik
    save_to_qlik_format(all_results, filename_prefix=f"coleta_{args.query.replace(' ', '_')}")

if __name__ == "__main__":
    main()