from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .base_anatel import BaseAnatel, normalizar_codigo_anatel
from .utils import normalizar_texto

@dataclass
class DadosProduto:
    url: str = ""
    titulo: str = ""
    preco: str = ""
    codigo_anatel_principal: str = ""
    codigo_anatel_normalizado: str = ""
    marca: str = ""
    fabricante: str = ""
    modelo: str = ""
    modelo_detalhado: str = ""
    modelo_alfanumerico: str = ""
    numero_modelo: str = ""
    atributos_json: str = ""
    comentarios: list[str] | None = None

def _texto_compativel(anuncio: str, base: str) -> bool:
    anuncio_norm = normalizar_texto(anuncio)
    base_norm = normalizar_texto(base)
    if not anuncio_norm or not base_norm:
        return False
    return anuncio_norm == base_norm or anuncio_norm in base_norm or base_norm in anuncio_norm

def _equivalencia_marcas(anuncio: str, base: str) -> bool:
    anuncio_norm = normalizar_texto(anuncio)
    base_norm = normalizar_texto(base)
    if not anuncio_norm or not base_norm: 
        return False
    
    aliases = {
        "xiaomi": ["poco", "redmi", "mi", "xiaomi"],
        "apple": ["apple", "iphone"],
        "samsung": ["samsung", "galaxy"],
        "motorola": ["motorola", "moto", "lenovo"]
    }
    for marca, lista in aliases.items():
        if marca in base_norm or marca in anuncio_norm:
            if any(t in anuncio_norm for t in lista) and any(t in base_norm for t in lista):
                return True
    return _texto_compativel(anuncio, base)

def _equivalencia_nome_comercial(anuncio: str, base: str) -> bool:
    anuncio_norm = normalizar_texto(anuncio)
    base_norm = normalizar_texto(base)
    if not anuncio_norm or not base_norm: 
        return False
    
    subs = {"pro plus": "pro+", "pro+": "pro+", "5g": "5g"}
    for k, v in subs.items():
        anuncio_norm = anuncio_norm.replace(k, v)
        base_norm = base_norm.replace(k, v)
        
    return anuncio_norm == base_norm or anuncio_norm in base_norm or base_norm in anuncio_norm

def _normalizar_situacao_requerimento(valor: Any) -> str:
    texto = normalizar_texto(valor)
    if "cancelad" in texto:
        return "CANCELADA"
    if "suspens" in texto:
        return "SUSPENSA"
    if "emitid" in texto:
        return "EMITIDA"
    if not texto:
        return "NAO_INFORMADA"
    return "OUTRA"

def _modelo_decisivo_capturado(dados: DadosProduto) -> tuple[str, str]:
    prioridade = [
        ("Modelo alfanumérico", dados.modelo_alfanumerico),
        ("Modelo detalhado", dados.modelo_detalhado),
        ("Número do modelo", dados.numero_modelo),
        ("Modelo", dados.modelo),
    ]
    for label, valor in prioridade:
        if str(valor).strip():
            return label, str(valor).strip()
    return "", ""

def analisar_situacao_anatel(codigo: str, marca: str, modelo: str, nome_comercial_anuncio: str, base: BaseAnatel | None) -> dict[str, str]:
    codigo_norm = normalizar_codigo_anatel(codigo)
    resultado = {
        "codigo_anatel": str(codigo or ""),
        "codigo_anatel_normalizado": codigo_norm,
        "codigo_base": "",
        "codigo_confere_base": "NAO",
        "marca_confere_base": "NAO",
        "modelo_confere_base": "NAO",
        "nome_comercial_confere_base": "NAO",
        "nome_comercial_base": "",
        "situacao_requerimento_base": "",
        "situacao_requerimento_normalizada": "NAO_INFORMADA",
        "requerimento_emitido": "NAO",
        "anatel_em_ordem": "NAO",
        "situacao_anatel": "NAO_INFORMADO",
        "motivo_anatel": "Código Anatel não localizado no anúncio.",
    }

    if not codigo_norm:
        return resultado

    if base is None:
        resultado.update({
            "situacao_anatel": "NAO_VERIFICADO",
            "motivo_anatel": "Código encontrado no anúncio, mas nenhuma base Anatel foi fornecida para a conferência."
        })
        return resultado

    encontrados = base.buscar_codigo_exato(codigo_norm)
    if encontrados.empty:
        resultado.update({
            "situacao_anatel": "IRREGULAR",
            "motivo_anatel": "Código do anúncio não possui correspondência exata na base Anatel."
        })
        return resultado

    linha = encontrados.iloc[0]
    fabricante_base = str(linha.get(base.coluna_fabricante) or "") if base.coluna_fabricante else ""
    modelo_base = str(linha.get(base.coluna_modelo) or "") if base.coluna_modelo else ""
    nome_comercial_base = str(linha.get(base.coluna_nome_comercial) or "") if base.coluna_nome_comercial else ""
    sit_req_base = str(linha.get(base.coluna_situacao_requerimento) or "")
    sit_req_norm = _normalizar_situacao_requerimento(sit_req_base)

    resultado.update({
        "codigo_base": str(linha.get("codigo_anatel_normalizado") or ""),
        "codigo_confere_base": "SIM",
        "situacao_requerimento_base": sit_req_base,
        "situacao_requerimento_normalizada": sit_req_norm,
        "requerimento_emitido": "SIM" if sit_req_norm == "EMITIDA" else "NAO",
        "nome_comercial_base": nome_comercial_base,
    })

    marca_confere = _equivalencia_marcas(marca, fabricante_base)
    modelo_confere = _texto_compativel(modelo, modelo_base) if modelo_base else False
    nome_com_confere = _equivalencia_nome_comercial(nome_comercial_anuncio, nome_comercial_base) if nome_comercial_base else True

    resultado.update({
        "marca_confere_base": "SIM" if marca_confere else "NAO",
        "modelo_confere_base": "SIM" if modelo_confere else "NAO",
        "nome_comercial_confere_base": "SIM" if nome_com_confere else "NAO",
    })

    divergencias = []
    if not marca: divergencias.append("marca não capturada no anúncio")
    elif not fabricante_base: divergencias.append("marca/fabricante ausente na base")
    elif not marca_confere: divergencias.append("marca do anúncio diferente da base")

    if not modelo: divergencias.append("modelo técnico não capturado no anúncio")
    elif not modelo_base: divergencias.append("modelo técnico ausente na base")
    elif not modelo_confere: divergencias.append("modelo técnico do anúncio diferente da base")
    
    if nome_comercial_base and not nome_com_confere:
        divergencias.append("nome comercial do anúncio diferente da base")

    if sit_req_norm in {"CANCELADA", "SUSPENSA"}:
        resultado.update({
            "situacao_anatel": "IRREGULAR",
            "motivo_anatel": f"Situação do Requerimento: '{sit_req_base}'. Homologação suspensa ou cancelada não é válida."
        })
        return resultado

    if sit_req_norm != "EMITIDA":
        resultado.update({
            "situacao_anatel": "NAO_CLASSIFICADO",
            "motivo_anatel": f"A coluna 'Situação do Requerimento' contém um valor não reconhecido: '{sit_req_base or 'não informado'}'."
        })
        return resultado

    if divergencias:
        resultado.update({
            "situacao_anatel": "NAO_CLASSIFICADO",
            "motivo_anatel": "Homologação Emitida e código exato, porém " + "; ".join(divergencias) + "."
        })
        return resultado

    resultado.update({
        "anatel_em_ordem": "SIM",
        "situacao_anatel": "REGULAR",
        "motivo_anatel": "Homologação Emitida; código, marca/fabricante, modelo e nome comercial do anúncio conferem com a base."
    })
    return resultado

def classificar_produto(dados: DadosProduto, analise_dimensional: dict[str, Any], anatel: dict[str, Any]) -> dict[str, Any]:
    dimensoes_confiaveis = analise_dimensional.get("dimensoes_confiaveis") == "SIM"
    dentro_limite = analise_dimensional.get("dentro_limite_dimensional") == "SIM"
    anatel_em_ordem = anatel.get("anatel_em_ordem") == "SIM"
    codigo_anatel = str(anatel.get("codigo_anatel_normalizado") or "").strip()

    if not dimensoes_confiaveis:
        status_req = anatel.get("situacao_requerimento_normalizada")
        complemento_anatel = f" Homologação {status_req.lower()} na base Anatel." if status_req in {"CANCELADA", "SUSPENSA"} else ""
        return {
            "classificacao": "SUSPEITO",
            "motivo_classificacao": "Não foram localizadas dimensões corporais confiáveis." + complemento_anatel
        }

    if not dentro_limite:
        return {
            "classificacao": "DESCARTADO",
            "motivo_classificacao": "Dimensões corporais maiores que o limite de 12 × 5,5 cm."
        }

    status_req = anatel.get("situacao_requerimento_normalizada")
    if status_req in {"CANCELADA", "SUSPENSA"}:
        return {
            "classificacao": "IRREGULAR",
            "motivo_classificacao": f"Dimensões dentro do limite e homologação {status_req.lower()} na base Anatel."
        }

    if anatel_em_ordem:
        return {
            "classificacao": "DESCARTADO",
            "motivo_classificacao": "Dimensões dentro do limite, porém o código Anatel, a marca e o modelo estão em conformidade com a base."
        }
        
    if anatel.get("situacao_anatel") == "NAO_CLASSIFICADO":
        return {
            "classificacao": "NÃO CLASSIFICADO",
            "motivo_classificacao": "Informações não permitem concluir regularidade com segurança. " + anatel.get("motivo_anatel", "")
        }

    return {
        "classificacao": "IRREGULAR",
        "motivo_classificacao": "Dimensões dentro do limite de 12 × 5,5 cm e código Anatel não localizado no anúncio." if not codigo_anatel else "Dimensões dentro do limite, mas o código Anatel, a marca ou o modelo não ficaram em conformidade."
    }