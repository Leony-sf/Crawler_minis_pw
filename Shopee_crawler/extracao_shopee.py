from __future__ import annotations

import re
from typing import Any

from bs4 import BeautifulSoup

from .base_anatel import buscar_codigo_na_base
from .utils import (
    juntar_textos,
    normalizar_codigo_anatel,
    normalizar_texto,
    parece_codigo_anatel,
    somente_digitos,
)


LABELS_MARCA = [
    "marca",
    "brand",
]

LABELS_MODELO = [
    "modelo",
    "modelo alfanumerico",
    "modelo alfanumérico",
    "modelo detalhado",
    "numero do modelo",
    "número do modelo",
    "model",
]

LABELS_VERSAO = [
    "versao",
    "versão",
    "versoes",
    "versões",
    "versao do modelo",
    "versão do modelo",
]

LABELS_FABRICANTE = [
    "fabricante",
    "nome do fabricante",
    "manufacturer",
]

LABELS_ANATEL = [
    "anatel",
    "codigo anatel",
    "código anatel",
    "homologacao",
    "homologação",
    "numero de homologacao",
    "número de homologação",
    "numero de homologacao da anatel",
    "número de homologação da anatel",
    "nr de homologacao",
    "nr de homologação",
    "nº de homologacao",
    "nº de homologação",
]


REGEX_ANATEL_PERTO_TERMO = re.compile(
    r"(?:anatel|homologa[cç][aã]o|c[oó]digo\s+anatel|nr\.?\s*de\s*homologa[cç][aã]o|n[ºo]\s*de\s*homologa[cç][aã]o)"
    r"[^\d]{0,140}([\d.\-/\s]{8,24})",
    flags=re.IGNORECASE,
)

REGEX_TERMO_DEPOIS_NUMERO = re.compile(
    r"([\d.\-/\s]{8,24})[^a-zA-Z0-9]{0,50}"
    r"(?:anatel|homologa[cç][aã]o)",
    flags=re.IGNORECASE,
)

REGEX_ANATEL_LINHAS = re.compile(
    r"n[uú]mero\s+de\s+homologa[cç][aã]o(?:\s+da\s+anatel)?\s*[:\-]?\s*([0-9][\d.\-/\s]{7,24})",
    flags=re.IGNORECASE,
)

STOPWORDS_FABRICANTE = {
    "da",
    "de",
    "do",
    "das",
    "dos",
    "e",
    "a",
    "o",
    "the",
    "inc",
    "ltda",
    "ltd",
    "sa",
    "s/a",
    "co",
    "corp",
    "corporation",
    "company",
    "industria",
    "industrial",
    "comercio",
    "comercial",
    "eletronica",
    "electronics",
    "technology",
    "technologies",
    "mobile",
    "comunicacao",
    "communications",
    "amazonas",
    "amazonia",
    "brasil",
    "brazil",
}

MARCAS_EQUIVALENTES = {
    "xiaomi": ["xiaomi", "mi", "redmi", "poco"],
    "mi": ["xiaomi", "mi", "redmi", "poco"],
    "redmi": ["xiaomi", "mi", "redmi", "poco"],
    "poco": ["xiaomi", "mi", "redmi", "poco"],
    "samsung": ["samsung", "galaxy"],
    "apple": ["apple", "iphone", "ipad"],
    "motorola": ["motorola", "moto", "lenovo"],
    "lenovo": ["lenovo", "motorola", "moto"],
    "lg": ["lg"],
    "realme": ["realme"],
    "asus": ["asus", "zenfone", "rog"],
    "positivo": ["positivo"],
    "multilaser": ["multilaser", "multi"],
}


def texto_limpo(soup: BeautifulSoup) -> str:
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    return soup.get_text("\n", strip=True)


def _linhas_validas(texto: str) -> list[str]:
    return [l.strip(" :") for l in str(texto or "").splitlines() if l.strip(" :")]


def _parece_label(texto: str, labels: list[str]) -> bool:
    texto_norm = normalizar_texto(texto)
    labels_norm = [normalizar_texto(lbl) for lbl in labels]

    return any(lbl == texto_norm or lbl in texto_norm for lbl in labels_norm)


def _valor_aceitavel(valor: str) -> bool:
    valor = str(valor or "").strip()
    valor_norm = normalizar_texto(valor)

    if not valor:
        return False

    if len(valor) > 180:
        return False

    valores_ruins = {
        "da anatel",
        "anatel",
        "detalhes do produto",
        "especificacoes do produto",
        "especificações do produto",
        "informacoes do produto",
        "informações do produto",
        "descricao do produto",
        "descrição do produto",
        "marca",
        "modelo",
        "fabricante",
    }

    if valor_norm in {normalizar_texto(v) for v in valores_ruins}:
        return False

    return True


def _proximo_valor(linhas: list[str], indice: int) -> str:
    for j in range(indice + 1, min(indice + 6, len(linhas))):
        candidato = linhas[j]
        candidato_norm = normalizar_texto(candidato)

        if candidato_norm in {"da anatel", "anatel", "produto"}:
            continue

        if _valor_aceitavel(candidato):
            return candidato.strip()

    return ""


def extrair_label_values_texto(texto: str) -> dict[str, str]:
    pares: dict[str, str] = {}
    linhas = _linhas_validas(texto)

    labels_todos = (
        LABELS_MARCA
        + LABELS_MODELO
        + LABELS_VERSAO
        + LABELS_FABRICANTE
        + LABELS_ANATEL
    )

    # Formato: "Marca: Samsung" ou "Código ANATEL - 123456789"
    for linha in linhas:
        m = re.match(r"^(.{2,90}?)[\s]*[:：-][\s]*(.{1,180})$", linha)

        if not m:
            continue

        chave = m.group(1).strip(" :")
        valor = m.group(2).strip(" :")

        if _parece_label(chave, labels_todos) and _valor_aceitavel(valor):
            pares.setdefault(chave, valor)

    # Formato em linhas:
    # Marca
    # Samsung
    labels_norm = [normalizar_texto(x) for x in labels_todos]

    for i, linha in enumerate(linhas):
        linha_norm = normalizar_texto(linha)

        if linha_norm == "da anatel":
            continue

        if any(lbl == linha_norm or lbl in linha_norm for lbl in labels_norm):
            valor = _proximo_valor(linhas, i)

            if valor:
                chave = linha

                if "numero de homologacao" in linha_norm and i + 1 < len(linhas):
                    if normalizar_texto(linhas[i + 1]) == "da anatel":
                        chave = f"{linha} da Anatel"

                pares.setdefault(chave, valor)

    texto_uma_linha = " ".join(linhas)

    for match in REGEX_ANATEL_LINHAS.findall(texto_uma_linha):
        if parece_codigo_anatel(match):
            pares.setdefault("Número de homologação da Anatel", normalizar_codigo_anatel(match))

    return pares


def extrair_label_values(html: str, texto_extra: str = "") -> dict[str, str]:
    soup = BeautifulSoup(html or "", "lxml")
    pares: dict[str, str] = {}

    # Tabelas comuns
    for tr in soup.select("tr"):
        celulas = [c.get_text(" ", strip=True) for c in tr.select("th, td")]

        if len(celulas) >= 2:
            chave = celulas[0].strip(" :")
            valor = celulas[1].strip()

            if chave and valor:
                pares.setdefault(chave, valor)

    # Blocos genéricos de especificação da Shopee.
    possiveis_blocos = soup.select(
        "[class*='product-detail'] [class*='item'], "
        "[class*='product-detail'] [class*='row'], "
        "[class*='product-spec'] [class*='item'], "
        "[class*='product-spec'] [class*='row'], "
        "[class*='attribute'] [class*='item'], "
        "[class*='attribute'] [class*='row'], "
        "[class*='detail'] [class*='item'], "
        "[class*='detail'] [class*='row']"
    )

    for bloco in possiveis_blocos:
        textos = [
            t.get_text(" ", strip=True)
            for t in bloco.find_all(["span", "p", "div", "th", "td"])
        ]

        textos = [t.strip(" :") for t in textos if t and len(t.strip()) <= 200]

        if len(textos) >= 2:
            chave = textos[0]
            valor = textos[-1]

            if chave and valor and chave != valor:
                pares.setdefault(chave, valor)

    texto_html = texto_limpo(soup)
    pares_texto_html = extrair_label_values_texto(texto_html)

    for chave, valor in pares_texto_html.items():
        pares.setdefault(chave, valor)

    if texto_extra:
        pares_texto_visivel = extrair_label_values_texto(texto_extra)

        for chave, valor in pares_texto_visivel.items():
            pares.setdefault(chave, valor)

    return pares


def _buscar_por_labels(pares: dict[str, str], labels: list[str]) -> str:
    labels_norm = [normalizar_texto(l) for l in labels]

    for chave, valor in pares.items():
        chave_norm = normalizar_texto(chave)

        if any(lbl == chave_norm for lbl in labels_norm):
            return str(valor).strip()

    for chave, valor in pares.items():
        chave_norm = normalizar_texto(chave)

        if any(lbl in chave_norm for lbl in labels_norm):
            return str(valor).strip()

    return ""


def extrair_codigos_anatel(
    html: str,
    pares: dict[str, str] | None = None,
    texto_extra: str = "",
) -> list[str]:
    soup = BeautifulSoup(html or "", "lxml")
    texto = juntar_textos([texto_limpo(soup), texto_extra], "\n")

    codigos: list[str] = []
    pares = pares or {}

    for chave, valor in pares.items():
        chave_norm = normalizar_texto(chave)

        if any(normalizar_texto(lbl) in chave_norm for lbl in LABELS_ANATEL):
            for candidato in re.findall(r"[\d.\-/\s]{8,24}", str(valor)):
                if parece_codigo_anatel(candidato):
                    codigos.append(normalizar_codigo_anatel(candidato))

    texto_uma_linha = " ".join(_linhas_validas(texto))

    for match in REGEX_ANATEL_LINHAS.findall(texto_uma_linha):
        if parece_codigo_anatel(match):
            codigos.append(normalizar_codigo_anatel(match))

    for match in REGEX_ANATEL_PERTO_TERMO.findall(texto):
        if parece_codigo_anatel(match):
            codigos.append(normalizar_codigo_anatel(match))

    for match in REGEX_TERMO_DEPOIS_NUMERO.findall(texto):
        if parece_codigo_anatel(match):
            codigos.append(normalizar_codigo_anatel(match))

    unicos = []

    for codigo in codigos:
        digitos = somente_digitos(codigo)

        if len(set(digitos)) <= 2:
            continue

        if codigo and codigo not in unicos:
            unicos.append(codigo)

    return unicos


def extrair_dados_html(html: str, url: str = "", texto_extra: str = "") -> dict[str, Any]:
    soup = BeautifulSoup(html or "", "lxml")
    pares = extrair_label_values(html, texto_extra=texto_extra)

    titulo = ""

    for seletor in [
        "meta[property='og:title']",
        "h1",
        "[data-sqe='name']",
        "[class*='product-briefing'] [class*='name']",
        "[class*='product-title']",
    ]:
        el = soup.select_one(seletor)

        if el:
            titulo = el.get("content") if el.name == "meta" else el.get_text(" ", strip=True)

            if titulo:
                break

    preco = ""

    for seletor in [
        "meta[property='product:price:amount']",
        "meta[itemprop='price']",
    ]:
        el = soup.select_one(seletor)

        if el and el.get("content"):
            preco = el.get("content", "")
            break

    if not preco:
        candidatos_preco = soup.select(
            "[class*='price'], "
            "[class*='Price'], "
            "[data-sqe='price']"
        )

        for candidato in candidatos_preco:
            txt = candidato.get_text(" ", strip=True)

            if txt and "R$" in txt:
                preco = txt
                break

    marca = _buscar_por_labels(pares, LABELS_MARCA)
    modelo = _buscar_por_labels(pares, LABELS_MODELO)
    versao = _buscar_por_labels(pares, LABELS_VERSAO)
    fabricante = _buscar_por_labels(pares, LABELS_FABRICANTE)

    codigos = extrair_codigos_anatel(html, pares, texto_extra=texto_extra)

    texto_relevante_mini = juntar_textos(
        [
            titulo,
            marca,
            modelo,
            versao,
            fabricante,
            pares,
            texto_extra,
        ],
        " | ",
    )

    return {
        "url": url,
        "titulo": titulo,
        "preco": preco,
        "marca": marca,
        "modelo": modelo,
        "versao": versao,
        "fabricante": fabricante,
        "codigos_anatel": codigos,
        "codigo_anatel_principal": codigos[0] if codigos else "",
        "ficha_tecnica": pares,
        "texto_relevante_mini": texto_relevante_mini,
    }



# ============================================================
# MINI CELULARES / DIMENSÕES / SUSPEITOS MANUAIS
# ============================================================

# Margem operacional para não perder produtos que passam pouco do recorte.
# Regra: se QUALQUER medida exceder o limite por até 1 cm, vira SUSPEITO_MANUAL.
# Ex.: limite 8,5 x 5,5 cm -> maior eixo próximo: >8,5 e <=9,5; largura próxima: >5,5 e <=6,5.
# Medidas abaixo do limite não contam como "próximas"; elas já são tratadas como dentro do recorte.
TOLERANCIA_PROXIMA_MAIOR_CM = 1.0
TOLERANCIA_PROXIMA_LARGURA_CM = 1.0

TERMOS_MINI_CELULAR = [
    "mini celular",
    "micro celular",
    "nano celular",
    "celular mini",
    "mini telefone",
    "micro telefone",
    "mini phone",
    "micro phone",
    "tiny phone",
    "small phone",
    "card phone",
    "key phone",
    "keyring phone",
    "bluetooth dialer",
    "dialer gsm",
    "celular chaveiro",
    "telefone chaveiro",
    "celular cartao",
    "celular cartão",
    "telefone cartao",
    "telefone cartão",
    "celular batom",
    "telefone batom",
    "celular caneta",
    "pen phone",
]

TERMOS_CELULAR_FUNCIONAL = [
    "celular",
    "telefone",
    "smartphone",
    "phone",
    "chip",
    "sim",
    "sim card",
    "gsm",
    "imei",
    "dual sim",
    "2 chips",
    "dois chips",
    "sms",
    "chamada",
    "ligacao",
    "ligação",
    "android",
    "lte",
    "4g",
    "3g",
    "2g",
    "samsung",
    "galaxy",
    "apple",
    "iphone",
    "xiaomi",
    "redmi",
    "poco",
    "motorola",
    "moto g",
    "nokia",
    "positivo",
    "multilaser",
]

MARCAS_MODELOS_SUSPEITOS_MINI = [
    "bm10",
    "bm20",
    "bm30",
    "bm50",
    "bm70",
    "bm90",
    "bm100",
    "bm200",
    "bm310",
    "bt11",
    "bt22",
    "b25",
    "b30",
    "j8",
    "j9",
    "j10",
    "long-cz",
    "long cz",
    "k10",
    "k33",
    "k66",
    "l8star",
    "l8 star",
    "gtstar",
    "gt star",
    "zanco",
    "zanco tiny",
    "servo",
    "servo phone",
    "anica",
    "aizku",
    "kechaoda",
    "soyes",
    "soyes xs",
    "soyes s10",
    "soyes 7s",
    "melrose",
    "melrose s9",
    "melrose s10",
]

TERMOS_FORMATO_DISFARCADO_MINI = [
    "batom",
    "batonzinho",
    "caneta",
    "pen phone",
    "isqueiro",
    "lighter phone",
    "chaveiro",
    "chave de carro",
    "bmw",
    "porsche",
    "keyring",
    "cartao",
    "cartão",
    "card phone",
    "tamanho de cartao",
    "tamanho de cartão",
]

TERMOS_TECNICOS_SUSPEITOS_MINI = [
    "aceita chip",
    "com chip",
    "para chip",
    "chip sim",
    "sim card",
    "dual sim",
    "2 chips",
    "dois chips",
    "gsm",
    "imei",
    "sms",
    "ligacao",
    "ligação",
    "chamada",
    "bluetooth dialer",
    "dialer gsm",
    "phone companion",
    "fone com chip",
]

TERMOS_DESCARTAR_MINI_TITULO = [
    "capinha",
    "capa para",
    "capa compativel",
    "capinha",
    "capa para",
    "capa compativel",
    "capa compatível",
    "case para",
    "pelicula",
    "película",
    "carregador",
    "cabo usb",
    "cabo tipo c",
    "fonte",
    "fone de ouvido",
    "suporte",
    "tripé",
    "tripe",
    "bateria para",
    "display para",
    "tela para",
    "frontal para",
    "placa para",
    "conector para",
    "flex para",
    "slot para",
    "gaveta chip",
    "smartwatch",
    "relogio",
    "relógio",
    "tablet",
    "adesivo",
    "miniatura decorativa",
]


def _numero_ptbr_para_float(valor: object) -> float | None:
    txt = str(valor or "").strip().replace(" ", "")
    if not txt:
        return None

    if "," in txt:
        txt = txt.replace(".", "").replace(",", ".")

    try:
        return float(txt)
    except Exception:
        return None


def _converter_para_cm(valor: object, unidade: str | None) -> float | None:
    numero = _numero_ptbr_para_float(valor)

    if numero is None:
        return None

    unidade_norm = normalizar_texto(unidade or "cm")

    if unidade_norm == "mm":
        return numero / 10.0

    return numero


def _fmt_cm(valor: float | None) -> str:
    if valor is None:
        return ""

    txt = f"{float(valor):.2f}".rstrip("0").rstrip(".")
    return txt.replace(".", ",")


def _janela_texto(texto: str, inicio: int, fim: int, margem: int = 80) -> str:
    ini = max(0, inicio - margem)
    fim = min(len(texto), fim + margem)
    return " ".join(str(texto[ini:fim] or "").split())


def _score_evidencia_dimensao(evidencia: object, maior_cm: float, largura_cm: float) -> tuple[int, float, float]:
    ev = normalizar_texto(evidencia)

    prioridade = 4

    if any(t in ev for t in ["detalhes do produto", "especificacoes do produto", "especificações do produto", "ficha tecnica", "ficha técnica"]):
        prioridade = 0
    elif any(t in ev for t in ["dimens", "altura", "largura", "comprimento", "diametro", "diâmetro", "tamanho"]):
        prioridade = 1
    elif " cm" in ev or "mm" in ev:
        prioridade = 2

    # Penaliza trechos comerciais ou de produtos relacionados.
    if any(t in ev for t in ["frete", "r$", "parcela", "produtos relacionados", "compre junto"]):
        prioridade += 3

    return (prioridade, float(maior_cm), float(largura_cm))


def _extrair_dimensao_por_multiplicacao(texto: str) -> dict[str, Any] | None:
    padrao = re.compile(
        r"(?P<a>\d+(?:[\.,]\d+)?)\s*(?P<ua>cm|mm)?\s*(?:x|×|por)\s*"
        r"(?P<b>\d+(?:[\.,]\d+)?)\s*(?P<ub>cm|mm)?"
        r"(?:\s*(?:x|×|por)\s*(?P<c>\d+(?:[\.,]\d+)?)\s*(?P<uc>cm|mm)?)?",
        flags=re.IGNORECASE,
    )

    candidatos: list[dict[str, Any]] = []

    for m in padrao.finditer(texto):
        unidades = [m.group("ua"), m.group("ub"), m.group("uc")]
        unidade_padrao = next((u for u in reversed(unidades) if u), "cm")
        valores: list[float] = []

        for nome_num, nome_un in [("a", "ua"), ("b", "ub"), ("c", "uc")]:
            bruto = m.group(nome_num)

            if not bruto:
                continue

            cm = _converter_para_cm(bruto, m.group(nome_un) or unidade_padrao)

            if cm is not None:
                valores.append(cm)

        if len(valores) < 2:
            continue

        # Evita capturas absurdas de preço/layout.
        if any(v <= 0 or v > 60 for v in valores):
            continue

        ordenados = sorted(valores, reverse=True)

        candidatos.append(
            {
                "maior_cm": ordenados[0],
                "largura_cm": ordenados[1],
                "espessura_cm": ordenados[2] if len(ordenados) >= 3 else None,
                "evidencia": _janela_texto(texto, m.start(), m.end(), margem=80),
                "origem": "multiplicacao",
            }
        )

    if not candidatos:
        return None

    candidatos.sort(key=lambda d: _score_evidencia_dimensao(d.get("evidencia"), d["maior_cm"], d["largura_cm"]))
    return candidatos[0]


def _normalizar_rotulo_dimensao(rotulo: str) -> str:
    r = normalizar_texto(rotulo)

    if any(t in r for t in ["altura", "comprimento", "diametro", "diâmetro"]):
        return "maior"

    if "largura" in r:
        return "largura"

    return ""


def _extrair_dimensao_por_rotulos(texto: str) -> dict[str, Any] | None:
    rotulos = "altura|comprimento|diametro|diâmetro|largura"
    numero = r"\d+(?:[\.,]\d+)?"

    achados: list[dict[str, Any]] = []

    padroes = [
        re.compile(rf"(?P<label>{rotulos})\b(?P<gap>[^0-9]{{0,35}})(?P<num>{numero})\s*(?P<unit>cm|mm)?", flags=re.IGNORECASE),
        re.compile(rf"(?P<num>{numero})\s*(?P<unit>cm|mm)?\s*(?:de\s*)?(?P<label>{rotulos})\b", flags=re.IGNORECASE),
    ]

    for padrao in padroes:
        for m in padrao.finditer(texto):
            tipo = _normalizar_rotulo_dimensao(m.group("label"))

            if not tipo:
                continue

            unidade = m.group("unit")
            cm = _converter_para_cm(m.group("num"), unidade or "cm")

            if cm is None or cm <= 0 or cm > 60:
                continue

            achados.append(
                {
                    "tipo": tipo,
                    "cm": cm,
                    "start": m.start(),
                    "end": m.end(),
                }
            )

    if not achados:
        return None

    maior_vals = [a["cm"] for a in achados if a["tipo"] == "maior"]
    largura_vals = [a["cm"] for a in achados if a["tipo"] == "largura"]

    if not maior_vals or not largura_vals:
        return None

    maior = min(maior_vals)
    largura = min(largura_vals)

    if largura > maior:
        maior, largura = largura, maior

    ini = min(a["start"] for a in achados)
    fim = max(a["end"] for a in achados)

    return {
        "maior_cm": maior,
        "largura_cm": largura,
        "espessura_cm": None,
        "evidencia": _janela_texto(texto, ini, fim, margem=100),
        "origem": "rotulos",
    }


def extrair_dimensoes_mini_celular(texto: str) -> dict[str, Any] | None:
    texto = " ".join(str(texto or "").split())

    if not texto:
        return None

    candidatos = [
        _extrair_dimensao_por_multiplicacao(texto),
        _extrair_dimensao_por_rotulos(texto),
    ]
    candidatos = [c for c in candidatos if c]

    if not candidatos:
        return None

    candidatos.sort(key=lambda d: _score_evidencia_dimensao(d.get("evidencia"), d["maior_cm"], d["largura_cm"]))
    return candidatos[0]


def _texto_base_mini(dados: dict[str, Any]) -> tuple[str, str, str]:
    titulo = str(dados.get("titulo") or "")

    ficha = dados.get("ficha_tecnica") or ""
    if isinstance(ficha, dict):
        ficha_txt = " | ".join(f"{k}: {v}" for k, v in ficha.items())
    else:
        ficha_txt = str(ficha or "")

    identificacao = juntar_textos(
        [
            dados.get("titulo"),
            dados.get("marca"),
            dados.get("modelo"),
            dados.get("versao"),
            dados.get("fabricante"),
            ficha_txt,
            dados.get("texto_relevante_mini"),
        ],
        " | ",
    )

    dimensoes = juntar_textos(
        [
            dados.get("titulo"),
            ficha_txt,
            dados.get("texto_relevante_mini"),
        ],
        " | ",
    )

    return titulo, identificacao, dimensoes


# Não há mais exceção para "marcas famosas".
# Qualquer marca/modelo pode ir para suspeitos se cair nas regras de dimensão,
# ausência de medida ou indício textual de mini celular/disfarce.


def analisar_suspeito_mini_celular(dados: dict[str, Any]) -> tuple[bool, str]:
    """Retorna suspeição textual para a fila manual.

    Não existe mais exceção por marca famosa.
    Se o anúncio tiver indícios de mini celular, formato disfarçado, chip/SIM/GSM
    ou modelo/marca suspeita, ele pode entrar na fila manual.
    """
    titulo, identificacao, _ = _texto_base_mini(dados)
    texto = normalizar_texto(identificacao)

    motivos: list[str] = []


    for termo in MARCAS_MODELOS_SUSPEITOS_MINI:
        if normalizar_texto(termo) in texto:
            motivos.append(f"marca/modelo suspeito: {termo}")
            break

    for termo in TERMOS_FORMATO_DISFARCADO_MINI:
        if normalizar_texto(termo) in texto:
            motivos.append(f"formato disfarçado: {termo}")
            break

    tem_indicio_rede = any(
        normalizar_texto(t) in texto
        for t in ["chip", "sim", "gsm", "imei", "sms", "ligacao", "ligação", "chamada", "dual sim", "2 chips"]
    )
    tem_mini_ou_formato = any(normalizar_texto(t) in texto for t in TERMOS_MINI_CELULAR + TERMOS_FORMATO_DISFARCADO_MINI)

    if tem_indicio_rede and tem_mini_ou_formato and not motivos:
        motivos.append("mini/formato disfarçado com indício de chip/SIM/GSM")

    marca_capturada = normalizar_texto(dados.get("marca") or "")
    if not marca_capturada and tem_indicio_rede and tem_mini_ou_formato:
        motivos.append("marca não capturada + indício de mini celular com chip/SIM/GSM")

    return bool(motivos), "; ".join(motivos)


def analisar_mini_celular(
    dados: dict[str, Any],
    maior_max_cm: float = 12.0,
    largura_max_cm: float = 5.5,
) -> dict[str, Any]:
    """Classifica produto no recorte de mini celulares da Shopee.

    Regra atual:
    - acessórios e não celulares continuam descartados;
    - produtos claramente maiores que o recorte continuam descartados;
    - produtos sem medida explícita viram SUSPEITO_MANUAL, para não serem perdidos;
    - produtos dentro do limite seguem para validação ANATEL e também podem entrar
      em suspeitos por texto/dimensão, independentemente da marca;
    - produtos próximos do limite, dentro da tolerância operacional, viram
      SUSPEITO_MANUAL em vez de serem descartados;
    - nenhuma marca é ignorada automaticamente.
    """
    titulo, identificacao, texto_dimensoes = _texto_base_mini(dados)

    titulo_norm = normalizar_texto(titulo)
    identificacao_norm = normalizar_texto(identificacao)
    termo_descartar = next((t for t in TERMOS_DESCARTAR_MINI_TITULO if normalizar_texto(t) in titulo_norm), "")

    if termo_descartar:
        return {
            "mini_status": "DESCARTAR_ACESSORIO",
            "mini_motivo": f"Produto parece acessório/peça no título: {termo_descartar}",
            "mini_maior_cm": None,
            "mini_largura_cm": None,
            "mini_espessura_cm": None,
            "mini_evidencia": "",
            "mini_limite_maior_cm": float(maior_max_cm),
            "mini_limite_largura_cm": float(largura_max_cm),
            "mini_suspeito_manual": False,
            "mini_motivos_suspeito": "",
        }

    parece_mini = any(normalizar_texto(t) in identificacao_norm for t in TERMOS_MINI_CELULAR)
    parece_celular = parece_mini or any(normalizar_texto(t) in identificacao_norm for t in TERMOS_CELULAR_FUNCIONAL)

    if not parece_celular:
        return {
            "mini_status": "DESCARTAR_NAO_CELULAR",
            "mini_motivo": "Anúncio não possui indício suficiente de telefone/celular funcional",
            "mini_maior_cm": None,
            "mini_largura_cm": None,
            "mini_espessura_cm": None,
            "mini_evidencia": "",
            "mini_limite_maior_cm": float(maior_max_cm),
            "mini_limite_largura_cm": float(largura_max_cm),
            "mini_suspeito_manual": False,
            "mini_motivos_suspeito": "",
        }

    dimensoes = extrair_dimensoes_mini_celular(texto_dimensoes)

    if not dimensoes:
        motivo = "Sem medida explícita em cm/mm; separado para análise manual em vez de descartar"
        if parece_mini:
            motivo = "Parece mini celular, mas não encontrei medida explícita em cm/mm; separado para análise manual"
        return {
            "mini_status": "SUSPEITO_MANUAL",
            "mini_motivo": motivo,
            "mini_maior_cm": None,
            "mini_largura_cm": None,
            "mini_espessura_cm": None,
            "mini_evidencia": "",
            "mini_limite_maior_cm": float(maior_max_cm),
            "mini_limite_largura_cm": float(largura_max_cm),
            "mini_suspeito_manual": True,
            "mini_motivos_suspeito": "sem medida explícita",
        }

    maior = float(dimensoes.get("maior_cm") or 0)
    largura = float(dimensoes.get("largura_cm") or 0)
    espessura = dimensoes.get("espessura_cm")
    evidencia = dimensoes.get("evidencia") or ""

    maior_max = float(maior_max_cm)
    largura_max = float(largura_max_cm)
    dentro_do_limite = maior <= maior_max and largura <= largura_max

    # Regra solicitada: se QUALQUER UMA das medidas passar do limite por até 1 cm,
    # já separamos para suspeitos manuais.
    # Importante: medida menor que o limite NÃO conta como "próxima" aqui; ela já
    # está dentro do recorte. Proximidade significa exceder pouco o limite.
    maior_excesso = maior - maior_max
    largura_excesso = largura - largura_max
    maior_proximo = 0 < maior_excesso <= TOLERANCIA_PROXIMA_MAIOR_CM
    largura_proxima = 0 < largura_excesso <= TOLERANCIA_PROXIMA_LARGURA_CM
    perto_do_limite = (
        not dentro_do_limite
        and (maior_proximo or largura_proxima)
    )

    if dentro_do_limite:
        status = "MANTER"
        motivo = f"Dentro do limite: maior eixo {_fmt_cm(maior)} cm <= {_fmt_cm(maior_max)} cm e largura {_fmt_cm(largura)} cm <= {_fmt_cm(largura_max)} cm"
        suspeito, motivos_suspeito = analisar_suspeito_mini_celular(dados)
        if not suspeito:
            suspeito = True
            motivos_suspeito = "dimensão dentro do limite; separado para revisão manual sem exceção por marca"
    elif perto_do_limite:
        status = "SUSPEITO_MANUAL"
        motivo = (
            f"Medida próxima do limite: maior eixo {_fmt_cm(maior)} cm / largura {_fmt_cm(largura)} cm; "
            f"limite {_fmt_cm(maior_max)} cm x {_fmt_cm(largura_max)} cm; "
            f"tolerância operacional +{_fmt_cm(TOLERANCIA_PROXIMA_MAIOR_CM)} cm / +{_fmt_cm(TOLERANCIA_PROXIMA_LARGURA_CM)} cm"
        )
        suspeito = True
        if maior_proximo and largura_proxima:
            motivos_suspeito = "maior eixo e largura excedem o limite por até 1 cm"
        elif maior_proximo:
            motivos_suspeito = "maior eixo excede o limite por até 1 cm"
        else:
            motivos_suspeito = "largura excede o limite por até 1 cm"
    else:
        status = "DESCARTAR_MEDIDA"
        motivo = f"Fora do limite: maior eixo {_fmt_cm(maior)} cm / largura {_fmt_cm(largura)} cm; limite {_fmt_cm(maior_max)} cm x {_fmt_cm(largura_max)} cm"
        suspeito = False
        motivos_suspeito = ""

    return {
        "mini_status": status,
        "mini_motivo": motivo,
        "mini_maior_cm": maior,
        "mini_largura_cm": largura,
        "mini_espessura_cm": float(espessura) if espessura is not None else None,
        "mini_evidencia": evidencia,
        "mini_limite_maior_cm": maior_max,
        "mini_limite_largura_cm": largura_max,
        "mini_suspeito_manual": bool(suspeito),
        "mini_motivos_suspeito": motivos_suspeito,
    }

def _texto_contem_aproximado(valor_base: str, texto_capturado: str) -> bool:
    base = normalizar_texto(valor_base)
    capturado = normalizar_texto(texto_capturado)

    if not base or not capturado:
        return False

    return base in capturado or capturado in base


def _tokens_significativos(texto: str) -> list[str]:
    texto_norm = normalizar_texto(texto)
    tokens = re.findall(r"[a-z0-9]+", texto_norm)
    saida: list[str] = []

    for token in tokens:
        if len(token) < 2:
            continue

        if token in STOPWORDS_FABRICANTE:
            continue

        if token not in saida:
            saida.append(token)

    return saida


def _aliases_marca(texto: str) -> list[str]:
    texto_norm = normalizar_texto(texto)

    saida = []

    for token in _tokens_significativos(texto_norm):
        if token not in saida:
            saida.append(token)

        if token in MARCAS_EQUIVALENTES:
            for alias in MARCAS_EQUIVALENTES[token]:
                if alias not in saida:
                    saida.append(alias)

    return saida


def _confirmar_marca(
    marca_base: str,
    texto_capturado: str,
    fabricante_base: str = "",
) -> bool:
    if not marca_base:
        return True

    if _texto_contem_aproximado(marca_base, texto_capturado):
        return True

    texto_norm = normalizar_texto(texto_capturado)

    for alias in _aliases_marca(marca_base):
        if alias and alias in texto_norm:
            return True

    for alias in _aliases_marca(fabricante_base):
        if alias and alias in texto_norm:
            return True

    return False


def _confirmar_fabricante_por_marca(
    fabricante_base: str,
    texto_capturado: str,
    marca_capturada: str = "",
    marca_base: str = "",
) -> bool:
    if not fabricante_base:
        return True

    if _texto_contem_aproximado(fabricante_base, texto_capturado):
        return True

    texto_norm = normalizar_texto(texto_capturado)
    fabricante_norm = normalizar_texto(fabricante_base)

    candidatos = []

    for valor in [marca_capturada, marca_base, fabricante_base]:
        for alias in _aliases_marca(valor):
            if alias not in candidatos:
                candidatos.append(alias)

    for token in _tokens_significativos(fabricante_base):
        if token not in candidatos:
            candidatos.append(token)

    for candidato in candidatos:
        if not candidato:
            continue

        if candidato in fabricante_norm and candidato in texto_norm:
            return True

        if candidato in texto_norm:
            return True

    return False


def validar_produto(dados: dict[str, Any], base) -> dict[str, Any]:
    codigo = dados.get("codigo_anatel_principal", "")

    titulo = dados.get("titulo", "")
    marca = dados.get("marca", "")
    fabricante = dados.get("fabricante", "")
    modelo = dados.get("modelo", "")
    versao = dados.get("versao", "")
    ficha = dados.get("ficha_tecnica", "")

    texto_capturado = juntar_textos(
        [
            titulo,
            marca,
            fabricante,
            modelo,
            versao,
            ficha,
        ],
        " ",
    )

    if not codigo:
        return {
            "status_validacao": "IRREGULAR",
            "motivo_validacao": "Código ANATEL não encontrado no anúncio/produto.",
            "fabricante_base": "",
            "marca_base": "",
            "modelo_base": "",
            "versao_base": "",
        }

    if base is None or getattr(base, "empty", True):
        return {
            "status_validacao": "IRREGULAR",
            "motivo_validacao": "Código ANATEL encontrado, mas nenhuma base foi informada/carregada.",
            "fabricante_base": "",
            "marca_base": "",
            "modelo_base": "",
            "versao_base": "",
        }

    registro = buscar_codigo_na_base(base, codigo)

    if not registro:
        return {
            "status_validacao": "IRREGULAR",
            "motivo_validacao": f"Código ANATEL {codigo} não encontrado na base.",
            "fabricante_base": "",
            "marca_base": "",
            "modelo_base": "",
            "versao_base": "",
        }

    fabricante_base = str(registro.get("fabricante_base", "") or "")
    marca_base = str(registro.get("marca_base", "") or "")
    modelo_base = str(registro.get("modelo_base", "") or "")
    versao_base = str(registro.get("versao_base", "") or "")

    irregularidades: list[str] = []
    avisos: list[str] = []

    if marca_base:
        if not _confirmar_marca(marca_base, texto_capturado, fabricante_base=fabricante_base):
            irregularidades.append("Marca do produto não foi confirmada na captura do anúncio.")

    if fabricante_base:
        if not _confirmar_fabricante_por_marca(
            fabricante_base,
            texto_capturado,
            marca_capturada=marca,
            marca_base=marca_base,
        ):
            irregularidades.append("Fabricante do produto não foi confirmado na captura do anúncio.")

    # Na Shopee, modelo geralmente vem como nome comercial.
    # Então modelo diferente vira aviso, não irregular automático.
    if modelo_base:
        if not _texto_contem_aproximado(modelo_base, texto_capturado):
            avisos.append("Modelo da base não foi confirmado literalmente no anúncio.")

    if versao_base:
        if not _texto_contem_aproximado(versao_base, texto_capturado):
            avisos.append("Versão da base não foi confirmada literalmente no anúncio.")

    if irregularidades:
        return {
            "status_validacao": "IRREGULAR",
            "motivo_validacao": " ".join(irregularidades + avisos),
            "fabricante_base": fabricante_base,
            "marca_base": marca_base,
            "modelo_base": modelo_base,
            "versao_base": versao_base,
        }

    motivo = "Código ANATEL encontrado na base e marca/fabricante sem divergência forte identificada."

    if avisos:
        motivo += " Atenção: " + " ".join(avisos)

    return {
        "status_validacao": "REGULAR",
        "motivo_validacao": motivo,
        "fabricante_base": fabricante_base,
        "marca_base": marca_base,
        "modelo_base": modelo_base,
        "versao_base": versao_base,
    }