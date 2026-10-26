# Crawler de Marketplaces & Validador ANATEL 📱🛒

Sistema automatizado para extração, classificação e validação de anúncios de telefonia em múltiplos marketplaces, com verificação de homologação junto à base oficial da ANATEL e exportação compatível com dashboards do Qlik.

---

## 📌 Visão Geral do Sistema

O projeto coleta dados de anúncios em **10 marketplaces** distintos e realiza um pipeline completo de tratamento de dados:
1. **Extração:** Coleta de títulos, preços, vendedores, URLs e códigos de homologação via Playwright/Scrapers.
2. **Filtragem Semântica:** Identificação e separação automática de produtos irrelevantes (acessórios, capas, brinquedos, cabos, etc.).
3. **Validação ANATEL:** Verificação cruzada do código de homologação extraído contra a base pública oficial de produtos homologados.
4. **Exportação Unificada:** Geração de relatórios em formatos **CSV** (delimitado por `;`) e **Parquet**, mantendo padronização rígida de esquemas para ingestão direta no Qlik.

---

## 📂 Estrutura do Repositório

```text
├── core/                           # Módulo Central Compartilhado
│   ├── base_anatel.py              # Regras de validação ANATEL, limpeza e filtros semânticos
│   └── exporter.py                 # Exportador padronizado em CSV e Parquet para o Qlik
│
├── Mercado_livre/                  # Módulos específicos por Marketplace
├── Amazon/
├── Shopee/
├── Magalu/
├── Casas_Bahia/
├── Carrefour/
├── Americanas/
├── Aliexpress/
├── Alibaba/
├── Temu/
│
├── Produtos_Homologados_Anatel.csv # Base oficial de homologados da ANATEL (gerada/atualizada)
├── atualizar_base_anatel.py        # Script para download/atualização automática da base ANATEL
├── run.py                          # Orquestrador Central CLI (interface única)
├── demo.py                         # Script para demonstração rápida/ao vivo
├── requirements.txt                # Dependências do projeto
└── README.md                       # Documentação do projeto
```

---

## 🛠️ Pré-requisitos e Instalação

### 1. Requisitos de Ambiente
* **Python 3.9** ou superior
* Gerenciador de pacotes `pip`

### 2. Instalação das Dependências

Clone o repositório e instale os pacotes necessários:

```bash
# Clonar o repositório
git clone https://github.com/seu-usuario/crawler_minis_pw.git
cd crawler_minis_pw

# Instalar bibliotecas Python
pip install -r requirements.txt

# Instalar os navegadores do Playwright
playwright install
```

---

## 🚀 Como Executar

### 1. Atualizar a Base Oficial da ANATEL
Antes de iniciar as coletas, execute o script para baixar ou atualizar o arquivo com os dados abertos oficiais da ANATEL:

```bash
python atualizar_base_anatel.py
```

### 2. Executar o Orquestrador Central (`run.py`)
O script `run.py` permite disparar a coleta em um ou múltiplos marketplaces simultaneamente com um único comando na raiz do projeto.

**Parâmetros disponíveis:**
* `--marketplaces` ou `-m`: Siglas dos marketplaces separados por vírgula (`ml`, `amazon`, `shopee`, `magalu`, `casas_bahia`, `carrefour`, `americanas`, `aliexpress`, `alibaba`, `temu`).
* `--query` ou `-q`: Termo de busca/pesquisa.
* `--limit` ou `-l`: Limite máximo de itens por marketplace *(opcional, padrão: 50)*.

**Exemplos de uso:**

```bash
# Coletar Mercado Livre e Amazon buscando por "mini celular"
python run.py -m ml,amazon -q "mini celular"

# Coletar em múltiplos marketplaces com limite de 100 itens
python run.py --marketplaces ml,amazon,shopee,magalu --query "mini celular" --limit 100
```

---

### 3. Executar a Demonstração Rápida (`demo.py`)
Para apresentações, reuniões ou testes rápidos de homologação sem risco de bloqueios ou demoras de rede, utilize o modo demonstração:

```bash
python demo.py
```
O script roda uma triagem rápida (3 a 5 anúncios) com saída formatada em tempo real no terminal e gera os arquivos na pasta `output/`.

---

## 📊 Formato dos Dados e Integração com Qlik

Todos os dados exportados seguem uma estrutura fixa de colunas garantindo a compatibilidade total com a carga de dados no **Qlik Dashboard**:

| Nome da Coluna | Tipo | Descrição |
| :--- | :--- | :--- |
| `marketplace` | String | Nome do marketplace de origem (ex: `Mercado_Livre`, `Amazon`) |
| `query` | String | Termo utilizado na busca (ex: `mini celular`) |
| `title` | String | Título completo do anúncio |
| `price` | Float | Preço normalizado em formato numérico (`00.00`) |
| `seller` | String | Nome ou identificador do vendedor |
| `url` | String | Link direto para o anúncio |
| `anatel_code` | String | Código de homologação extraído do anúncio |
| `is_valid_anatel` | Boolean | `True` se o código consta na base oficial da ANATEL |
| `is_accessory` | Boolean | `True` se for classificado como capa, brinquedo ou acessório |
| `scraped_at` | Datetime | Data e hora em que a extração foi realizada (`YYYY-MM-DD HH:MM:SS`) |

---

## 🔧 Módulo Central (`core/`)

* **`base_anatel.py`:** 
  * `AnatelValidator`: Classe responsável pelo carregamento em memória da base oficial e pela validação dos códigos.
  * `is_accessory_or_toy()`: Aplica Regex e filtros semânticos para identificar itens que não são aparelhos celulares.
  * `normalize_item()`: Padroniza dados de entrada, tratando moedas e strings.
* **`exporter.py`:**
  * Garante que os arquivos `.csv` e `.parquet` sejam gerados na pasta `output/` mantendo sempre a ordenação rígida de colunas exigida pelo Qlik.

---

## 🛡️ Solução de Problemas (Troubleshooting)

* **Erro ao inicializar o Playwright:**
  Certifique-se de ter executado `playwright install` após instalar os `requirements.txt`.
* **Base da ANATEL desatualizada ou não encontrada:**
  Execute `python atualizar_base_anatel.py` para garantir que o arquivo `Produtos_Homologados_Anatel.csv` esteja presente na raiz.
* **Codificação de caracteres no CSV:**
  Os arquivos CSV são salvos no padrão `UTF-8-SIG` com separador `;`, garantindo que acentos e caracteres especiais abram corretamente no Excel e no Qlik.