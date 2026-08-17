# Crawler Amazon Playwright + ANATEL

Estrutura igual à ideia do crawler Mercado Livre, separada em arquivos:

```text
amazon_crawler/
├── __init__.py
├── base_anatel.py
├── crawler_playwright_amazon.py
├── extracao.py
├── requirements.txt
└── utils.py
```

## Instalação

```bash
pip install -r amazon_crawler/requirements.txt
playwright install chromium
```

## Rodar por termo de busca

```bash
python amazon_crawler/crawler_playwright_amazon.py --base-anatel base_anatel.csv --query "smartphone" --max-pages 2 --headful
```

## Rodar por URL direta

```bash
python amazon_crawler/crawler_playwright_amazon.py --base-anatel base_anatel.csv --start-url "https://www.amazon.com.br/s?k=celular" --max-pages 2 --headful
```

## Saídas

```text
amazon_output/
├── products.parquet
├── comments.parquet
├── products_debug.csv
├── comments_debug.csv
└── prints/
    ├── regular/
    ├── irregular/
    └── aviso/
```

## Lógica de classificação

- Sem código ANATEL no anúncio: `IRREGULAR`.
- Código inválido ou não normalizável: `IRREGULAR`.
- Código normalizado não encontrado na base: `IRREGULAR`.
- Código encontrado, mas marca/fabricante diverge da base: `IRREGULAR`.
- Código encontrado, mas modelo diverge da base: `IRREGULAR`.
- Código, marca/fabricante e modelo compatíveis: `REGULAR`.
- Match único por prefixo de 5 dígitos: `AVISO`, caso marca e modelo estejam compatíveis.
