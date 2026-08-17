# -*- coding: utf-8 -*-
from __future__ import annotations
import re
from dataclasses import asdict, dataclass
from typing import Any
from utils_alibaba import normalizar_texto

LIMITE_ALTURA_CM = 12.0
LIMITE_LARGURA_CM = 5.5
ROTULOS_DIMENSAO = {"dimensoes", "dimensao", "tamanho do produto", "medidas do produto", "medida do produto", "altura", "largura", "comprimento", "profundidade", "espessura", "size", "dimensions"}
ROTULOS_EXCLUIR = {"embalagem", "pacote", "caixa", "display", "tela", "screen", "diagonal", "monitor", "volume", "frete", "produto embalado", "package"}
PADROES_FORA_ESCOPO_TITULO = [r"^\s*(case|cover|protector|glass|pel[ií]cula|capa|capinha)\b", r"^\s*(toy|brinquedo)\b", r"^\s*(carregador|cabo|fonte|adaptador)\b"]

@dataclass
class AnaliseDimensional:
    dimensoes_encontradas: str = "NAO"
    dimensoes_confiaveis: str = "NAO"
    dentro_limite_dimensional: str = "NAO_VERIFICADO"
    altura_cm: float | None = None
    largura_cm: float | None = None
    espessura_cm: float | None = None
    maior_dimensao_cm: float | None = None
    segunda_dimensao_cm: float | None = None
    evidencia_dimensoes: str = ""
    origem_dimensoes: str = ""
    motivo_dimensoes: str = "Dimensões corporais não localizadas."
    limite_altura_cm: float = LIMITE_ALTURA_CM
    limite_largura_cm: float = LIMITE_LARGURA_CM

    def para_dict(self) -> dict[str, Any]:
        return asdict(self)

def _numero(valor: str) -> float | None:
    texto = str(valor or "").strip().replace(" ", "")
    if not texto: return None
    if "," in texto and "." in texto:
        if texto.rfind(",") > texto.rfind("."): texto = texto.replace(".", "").replace(",", ".")
        else: texto = texto.replace(",", "")
    else: texto = texto.replace(",", ".")
    try: return float(texto)
    except ValueError: return None

def _para_cm(valor: str, unidade: str | None) -> float | None:
    numero = _numero(valor)
    if numero is None: return None
    unidade_norm = normalizar_texto(unidade or "")
    if unidade_norm in {"mm", "milimetro", "milimetros"}: return numero / 10.0
    if unidade_norm in {"m", "metro", "metros"}: return numero * 100.0
    if unidade_norm in {"pol", "polegada", "polegadas", "in", "inch", "inches"}: return numero * 2.54
    return numero

def _contexto_valido(contexto: str) -> bool:
    texto = normalizar_texto(contexto)
    return not any(termo in texto for termo in ROTULOS_EXCLUIR)

def _inferir_unidade_sem_rotulo(valores: list[float]) -> str:
    if valores and max(valores) > 30 and max(valores) <= 300: return "mm"
    return "cm"

def _corrigir_escala_dimensional_suspeita(valores_convertidos: list[float], valores_brutos: list[float], unidades: list[str | None]) -> tuple[list[float], bool]:
    if len(valores_convertidos) < 2 or len(valores_brutos) < 2: return valores_convertidos, False
    maior_convertida = max(valores_convertidos)
    brutos_ordenados = sorted(valores_brutos, reverse=True)
    unidades_norm = [normalizar_texto(unidade or "") for unidade in unidades if unidade]
    tem_mm = "mm" in unidades_norm
    escala_cm_plausivel = (4.0 <= brutos_ordenados[0] <= 30.0 and brutos_ordenados[1] <= 15.0)
    if tem_mm and maior_convertida < 4.0 and escala_cm_plausivel: return list(valores_brutos), True
    return valores_convertidos, False

def _extrair_multiplicacoes(texto: str, origem: str, prioridade: int) -> list[dict[str, Any]]:
    padrao = re.compile(r"(?P<a>\d{1,3}(?:[.,]\d+)?)\s*(?P<ua>mm|cm|m|pol|polegadas?|in|inch(?:es)?)?\s*(?:x|X|\*|×|por)\s*(?P<b>\d{1,3}(?:[.,]\d+)?)\s*(?P<ub>mm|cm|m|pol|polegadas?|in|inch(?:es)?)?(?:\s*(?:x|X|\*|×|por)\s*(?P<c>\d{1,3}(?:[.,]\d+)?)\s*(?P<uc>mm|cm|m|pol|polegadas?|in|inch(?:es)?)?)?", flags=re.IGNORECASE)
    candidatos = []
    for match in padrao.finditer(texto):
        contexto = texto[max(0, match.start() - 100): min(len(texto), match.end() + 100)]
        contexto_norm = normalizar_texto(contexto)
        if not _contexto_valido(contexto): continue
        brutos = [match.group("a"), match.group("b"), match.group("c")]
        unidades = [match.group("ua"), match.group("ub"), match.group("uc")]
        numeros_brutos = [_numero(item) for item in brutos if item is not None]
        unidade_padrao = match.group("uc") or match.group("ub") or match.group("ua") or _inferir_unidade_sem_rotulo(numeros_brutos)
        valores = []
        for bruto, unidade in zip(brutos, unidades):
            if bruto is None: continue
            convertido = _para_cm(bruto, unidade or unidade_padrao)
            if convertido is not None: valores.append(convertido)
        if len(valores) < 2: continue
        valores, escala_corrigida = _corrigir_escala_dimensional_suspeita(valores, numeros_brutos, unidades)
        if any(valor <= 0 or valor > 80 for valor in valores): continue
        tem_rotulo = any(rotulo in contexto_norm for rotulo in ROTULOS_DIMENSAO)
        if origem == "descricao" and not tem_rotulo: continue
        candidatos.append({"valores": sorted(valores, reverse=True), "evidencia": " ".join(contexto.split()), "origem": origem + " [escala reavaliada]" if escala_corrigida else origem, "prioridade": prioridade - (1 if tem_rotulo else 0)})
    return candidatos

def _extrair_atributos_separados(atributos: dict[str, str]) -> list[dict[str, Any]]:
    brutos = {}
    for chave, valor in atributos.items():
        chave_norm = normalizar_texto(chave)
        if not _contexto_valido(chave_norm): continue
        tipo = ""
        if "altura" in chave_norm or "comprimento" in chave_norm or "height" in chave_norm or "length" in chave_norm: tipo = "altura"
        elif "largura" in chave_norm or "width" in chave_norm: tipo = "largura"
        elif "espessura" in chave_norm or "profundidade" in chave_norm or "depth" in chave_norm: tipo = "espessura"
        if not tipo: continue
        match = re.search(r"(\d{1,3}(?:[.,]\d+)?)\s*(mm|cm|m|pol|polegadas?|in|inch(?:es)?)?", str(valor), flags=re.IGNORECASE)
        if not match: continue
        numero = _numero(match.group(1))
        if numero is None: continue
        brutos[tipo] = {"numero_texto": match.group(1), "numero": numero, "unidade": match.group(2), "evidencia": f"{chave}: {valor}"}

    if "altura" not in brutos or "largura" not in brutos: return []
    numeros_sem_unidade = [item["numero"] for item in brutos.values() if not item["unidade"]]
    unidade_inferida = _inferir_unidade_sem_rotulo(numeros_sem_unidade) if numeros_sem_unidade else ""
    encontrados = {}
    for tipo, item in brutos.items():
        convertido = _para_cm(item["numero_texto"], item["unidade"] or unidade_inferida or "cm")
        if convertido is None or convertido <= 0 or convertido > 80: continue
        encontrados[tipo] = (convertido, item["evidencia"])

    if "altura" not in encontrados or "largura" not in encontrados: return []
    valores = [encontrados["altura"][0], encontrados["largura"][0]]
    evidencias = [encontrados["altura"][1], encontrados["largura"][1]]
    if "espessura" in encontrados:
        valores.append(encontrados["espessura"][0])
        evidencias.append(encontrados["espessura"][1])
    return [{"valores": sorted(valores, reverse=True), "evidencia": " | ".join(evidencias), "origem": "atributos_separados", "prioridade": -2}]

def analisar_dimensoes_produto(dados: dict[str, Any]) -> dict[str, Any]:
    atributos = dados.get("atributos") or {}
    candidatos = []
    candidatos.extend(_extrair_atributos_separados(atributos))
    for chave, valor in atributos.items():
        contexto = f"{chave}: {valor}"
        if _contexto_valido(contexto): candidatos.extend(_extrair_multiplicacoes(contexto, origem=f"atributo:{chave}", prioridade=0))
    descricao = str(dados.get("descricao") or dados.get("texto_pagina") or "")
    candidatos.extend(_extrair_multiplicacoes(descricao, origem="descricao", prioridade=3))

    if not candidatos: return AnaliseDimensional().para_dict()
    candidatos.sort(key=lambda item: (item["prioridade"], item["valores"][0], item["valores"][1]))
    escolhido = candidatos[0]
    valores = escolhido["valores"]
    maior, segunda = valores[0], valores[1]
    espessura = valores[2] if len(valores) >= 3 else None
    dentro = (maior <= LIMITE_ALTURA_CM and segunda <= LIMITE_LARGURA_CM)

    return AnaliseDimensional(
        dimensoes_encontradas="SIM", dimensoes_confiaveis="SIM", dentro_limite_dimensional="SIM" if dentro else "NAO",
        altura_cm=maior, largura_cm=segunda, espessura_cm=espessura, maior_dimensao_cm=maior, segunda_dimensao_cm=segunda,
        evidencia_dimensoes=escolhido["evidencia"], origem_dimensoes=escolhido["origem"],
        motivo_dimensoes="Dimensões corporais dentro do limite." if dentro else "Dimensões corporais acima do limite."
    ).para_dict()

def classificar_produto(dados: dict[str, Any], analise_dimensional: dict[str, Any], analise_anatel: dict[str, Any]) -> dict[str, Any]:
    titulo = normalizar_texto(dados.get("titulo") or "")
    fora_escopo = ""
    for padrao in PADROES_FORA_ESCOPO_TITULO:
        match = re.search(padrao, titulo, flags=re.IGNORECASE)
        if match:
            fora_escopo = match.group(0).strip()
            break

    dimensoes_confiaveis = analise_dimensional.get("dimensoes_confiaveis") == "SIM"
    dentro_limite = analise_dimensional.get("dentro_limite_dimensional") == "SIM"
    anatel_em_ordem = analise_anatel.get("anatel_em_ordem") == "SIM"
    codigo_anatel = str(analise_anatel.get("codigo_anatel_normalizado") or "").strip()

    resultado = {"classificacao": "DESCARTADO", "motivo_classificacao": "", "fora_escopo_titulo": "SIM" if fora_escopo else "NAO", "motivo_fora_escopo": fora_escopo}

    if fora_escopo:
        resultado["motivo_classificacao"] = f"Produto fora do escopo identificado pelo título: {fora_escopo}."
        return resultado
    if not dimensoes_confiaveis:
        resultado["classificacao"] = "SUSPEITO"
        resultado["motivo_classificacao"] = "Aparelho localizado, mas dimensões confiáveis não foram encontradas."
        return resultado
    if not dentro_limite:
        resultado["classificacao"] = "DESCARTADO"
        resultado["motivo_classificacao"] = "Dimensões corporais maiores que o limite de 12 × 5,5 cm."
        return resultado

    status_req = analise_anatel.get("situacao_requerimento_normalizada")
    if status_req in {"CANCELADA", "SUSPENSA"}:
        resultado["classificacao"] = "IRREGULAR"
        resultado["motivo_classificacao"] = f"Homologação {status_req.lower()} torna o produto irregular."
        return resultado
    if anatel_em_ordem:
        resultado["classificacao"] = "DESCARTADO"
        resultado["motivo_classificacao"] = "Dimensões no limite, porém Anatel, marca e modelo conferem com a base."
        return resultado

    resultado["classificacao"] = "IRREGULAR"
    if not codigo_anatel: resultado["motivo_classificacao"] = "Dimensões dentro do limite e código Anatel não localizado no anúncio."
    else: resultado["motivo_classificacao"] = "Dimensões dentro do limite, mas código Anatel, marca ou modelo divergem da base."
    return resultado