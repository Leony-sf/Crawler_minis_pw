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
