# Crawler_minis_pw — Sistema Multiplataforma de Web Scraping e Auditoria Anatel

Sistema automatizado para monitoramento, extração de dados e auditoria de regularidade de smartphones e dispositivos móveis em grandes marketplaces nacionais e internacionais, com foco na conformidade com a Anatel e detecção de produtos disfarçados.

---

## Visão Geral do Projeto

O **Crawler_minis_pw** é uma arquitetura modular desenvolvida em **Python** utilizando **Playwright** para automação de navegadores. O sistema realiza varreduras em larga escala em e-commerces para capturar metadados de anúncios, cruzar as informações com a base de dados oficial de produtos homologados da **Agência Nacional de Telecomunicações (Anatel)** e gerar relatórios analíticos estruturados (em formato Parquet) acompanhados de evidências visuais (prints).

O ecossistema foi projetado de forma independente por marketplace, garantindo isolamento de regras de negócio, facilidade de manutenção e alta resiliência contra mecanismos anti-bot.

---

## Arquitetura e Estrutura do Repositório

O projeto segue um padrão modular em que cada marketplace possui seus próprios scripts especializados de execução, navegação, extração, classificação e arquivos de busca:

```text
crawler_minis_pw/
├── Alibaba/              # Módulo de automação e regras para Alibaba
├── AliExpress/           # Módulo de automação e regras para AliExpress
├── Amazon/               # Módulo de automação e regras para Amazon
├── Americanas/           # Módulo de automação e regras para Americanas
├── Carrefour/            # Módulo de automação e regras para Carrefour
├── Casas_Bahia/          # Módulo de automação e regras para Casas Bahia
├── Magalu/               # Módulo de automação e regras para Magalu
├── Mercado_livre/        # Módulo de referência arquitetural (Mercado Livre)
├── Shopee/               # Módulo de automação e regras para Shopee
├── Temu/                 # Módulo de integração para Temu
├── requirements.txt      # Dependências globais do projeto
└── .gitignore            # Arquivos ignorados pelo versionamento
````

## Padrão Interno dos Módulos por Marketplace
Cada pasta de marketplace contém tipicamente os seguintes componentes:

main_*.py ou main.py: Orquestrador de linha de comando (CLI) que recebe parâmetros de execução e aciona o fluxo.

crawler_playwright_*.py: Controla a instância do navegador via Playwright e gerencia a paginação e o carregamento do DOM.

extracao_*.py ou extracao.py: Contém os seletores CSS/XPath para extração de título, preço, marca, modelo e número Anatel.

classificacao_*.py: Executa as regras de negócio de triagem (como teto de preço, detecção de termos de disfarce e análise de catálogos suspeitos).

base_anatel.py: Script responsável por carregar o banco de dados oficial e realizar o cruzamento técnico do produto.

buscar_*.txt: Arquivo de texto contendo as consultas de busca executadas pelo robô (uma por linha).

utils_*.py: Funções auxiliares de normalização de strings, gerenciamento de diretórios e salvamento.

## Tecnologias Utilizadas
Python 3.x: Linguagem base para toda a lógica de engenharia de dados e automação.

Playwright: Motor moderno de automação de navegadores (headless ou conectado via CDP), escolhido por sua alta performance e estabilidade na manipulação de conteúdos dinâmicos (Single Page Applications).

Pandas & PyArrow: Utilizados para manipulação de dados em memória e gravação colunar de alta performance em arquivos .parquet.

## Guia de Instalação e Execução
1. Pré-requisitos
Certifique-se de ter o Python instalado e o Google Chrome configurado em seu ambiente. Instale as dependências globais listadas na raiz:
```text
pip install -r requirements.txt
playwright install
```
2. Execução via Sessão Real do Chrome (CDP)
Para mitigar bloqueios e CAPTCHAs, recomenda-se iniciar o navegador localmente em uma porta de depuração (CDP 9225), permitindo que o Playwright aproveite os cookies e o perfil humano:
```text
& "C:\Program Files\Google\Chrome\Application\chrome.exe" --remote-debugging-port=9225 --user-data-dir="$PWD\chrome_profiles\sessao_real"
```
3. Rodando um Robô (Exemplo: Mercado Livre)
Navegue até o diretório do marketplace desejado ou execute a partir da raiz apontando para os parâmetros do script:
```text
python Mercado_livre/main.py --txt Mercado_livre/buscar_mercadolivre.txt --limit 50 --base "caminho/para/Produtos_Homologados_Anatel.csv"
```
## Regras de Negócio e Classificação
O sistema processa cada anúncio através de uma esteira rigorosa para evitar falsos positivos e garantir consistência estatística:

### Triagem de Escopo: 

Descarta automaticamente acessórios (capas, películas, fones) e itens fora do escopo de smartphones.

### Detecção de Disfarces e Produtos Irregulares: 

Valida títulos contra listas de termos suspeitos (ex.: disfarces de "mini celulares" como chaveiros ou MP3) e restrições de preço máximo (teto de R$ 300) antes da validação padrão.

### Cruzamento Anatel: 

Compara o código de homologação capturado com a base oficial, validando a correspondência exata de Marca, Modelo Técnico (Coluna M) e checando se o processo não está com a Homologação Suspensa.

### Persistência Incremental: 

Os resultados são gravados instantaneamente em products.parquet e comments.parquet, acompanhados de capturas de tela (prints) organizadas em pastas de evidências (/regulares e /irregulares).
Licença e Uso

```text
Projeto desenvolvido para fins de Supervisão de Mercado e Auditoria Técnica. Uso restrito aos operadores autorizados.
