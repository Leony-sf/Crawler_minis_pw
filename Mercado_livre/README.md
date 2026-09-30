# ML_crawler — saída Parquet limpa

## Por que o VS Code mostra `.parquet.as.json`

O arquivo real continua sendo `products.parquet` ou `comments.parquet`.
A extensão do VS Code converte temporariamente o conteúdo binário do Parquet
em JSON para permitir a leitura no editor.

## products.parquet

O arquivo possui somente estas colunas:

```text
pid
marketplace_id
titulo
link
codigo_anatel
marca
preco
status
motivo_validacao
motivo_irregularidade
warning
modelo
modelo_alfanumerico
modelo_decisivo
classificacao
evidencia_mini
dimensoes_encontradas
codigo_confere_base
marca_confere_base
modelo_confere_base
motivo_anatel
data_hora_captura
```

A coluna `dimensoes_encontradas` apresenta as medidas em formato legível,
por exemplo:

```text
6,8 x 2,8 x 1,2 cm
```

Quando não houver medidas confiáveis:

```text
NAO ENCONTRADAS
```

Linhas sem `pid` são descartadas antes da gravação.

## comments.parquet

A estrutura que já estava funcionando foi preservada, inclusive a data e hora
associadas ao produto.

## Saída

```text
Saidas_mercadolivre_DD-MM_HH-MM/
├── products.parquet
├── comments.parquet
└── prints/
    ├── irregulares/
    └── suspeitos/
```

Não é criado `resumo.txt`.


## Auditoria no terminal

Cada anúncio imprime três blocos lógicos:

```text
DIMENSÕES
  Limite adotado : 12,0 x 5,5 cm
  Produto        : medidas encontradas no anúncio
  Origem         : atributo usado para a medida
  Resultado      : dentro/acima/não verificável

ANATEL
  Código         : anúncio x base x confere
  Marca          : anúncio x base x confere
  Modelo         : anúncio x base x confere
  Resultado      : situação e motivo

CLASSIFICAÇÃO
  Destino        : DESCARTADO / IRREGULAR / SUSPEITO
  Motivo         : justificativa final
```

Para a comparação de modelo com a base, a prioridade é:
`modelo_alfanumerico -> modelo_detalhado -> numero_modelo -> modelo`.


## Situação do Requerimento — base Anatel

A coluna `Situação do Requerimento` é obrigatória.

Ordem da conferência:

```text
Código exato
    ↓
Situação do Requerimento
    ↓
Marca/Fabricante
    ↓
Modelo
```

Regras:

- `Homologação Emitida`: segue para comparação de marca e modelo.
- `Homologação Suspensa`: Anatel irregular.
- `Homologação Cancelada`: Anatel irregular.
- situação ausente ou diferente das anteriores: revisão, sem aprovação automática.

Para mini celulares com dimensões dentro de 12 × 5,5 cm, homologação suspensa
ou cancelada resulta em classificação `IRREGULAR`.

No terminal:

```text
ANATEL
Código         : anúncio=... | base=... | confere=SIM
Situação Req.  : base=Homologação Suspensa | emitida=NÃO
Marca          : anúncio=... | base=... | confere=NÃO VERIFICADO
Modelo         : anúncio=... | base=... | confere=NÃO VERIFICADO
Resultado      : IRREGULAR — ...
```


## Navegador — sessão temporária

O crawler agora abre um Google Chrome novo para cada execução.

Não utiliza:

```text
chrome_profiles
perfil persistente
user-data-dir
remote-debugging-port
CDP
sessão anterior
cookies de execuções anteriores
```

Fluxo:

```text
python main.py ...
        ↓
Google Chrome novo
        ↓
contexto temporário
        ↓
Mercado Livre
        ↓
busca e produtos
        ↓
fecha o contexto ao final
```

A pasta `chrome_profiles`, caso exista no projeto, não é utilizada por esta
versão do crawler Mercado Livre.

A mudança do navegador não altera as regras de:

- dimensões 120 × 55 mm;
- conferência Anatel;
- Situação do Requerimento;
- prioridade do modelo alfanumérico;
- classificação DESCARTADO / SUSPEITO / IRREGULAR;
- products.parquet;
- comments.parquet;
- prints.
