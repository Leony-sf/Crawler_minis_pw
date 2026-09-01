from __future__ import annotations
import re
from typing import Any

TERMOS_TELEFONIA = [
    "dual sim", "single sim", "dois chips", "2 chips", "chip", "sim card",
    "nano sim", "micro sim", "gsm", "2g", "3g", "4g", "5g", "lte", "volte",
    "celular", "telefone celular", "telefone móvel", "telefone movel", "smartphone",
    "feature phone", "mobile phone", "cell phone", "cellphone", "flip phone",
    "telefone simples", "celular simples", "celular antigo", "tijolinho",
    "chamada", "ligações", "ligacoes", "realiza chamada", "discagem",
]
TERMOS_INDICIO_FORTE_MINI = [
    "mini celular", "mini telefone", "mini mobile", "mini phone", "mini cellphone",
    "menor celular", "menor telefone", "smallest phone", "tiny phone", "micro celular",
    "card phone", "bluetooth dialer", "discador bluetooth", "ponto eletrônico",
    "telefone espião", "telefone espiao", "fone discador", "headset dialer",
    "l8star", "gtstar", "bm70", "bm30", "bm10", "bm50", "k8 mini",
    "soyes xs", "soyes xs11", "melrose s9x",
]
TERMOS_ACESSORIO = [
    "capa", "capinha", "case", "cover", "película", "pelicula", "vidro temperado",
    "carregador", "cabo usb", "fonte", "bateria", "tela para", "display para",
    "peça", "peca", "conector", "flex", "placa", "suporte",
    "fone de ouvido", "headphone", "headset", "adaptador",
]
TERMOS_PRODUTO_FORA_DO_ESCOPO = [
    "chocolate", "amendoim", "amêndoa", "amendoas", "biscoito", "bolacha",
    "leite", "lacta", "garoto", "nestlé", "nestle", "café", "cafe",
    "arroz", "feijão", "macarrão", "molho", "tempero", "salgadinho", "suco", 
    "refrigerante", "vinho", "cerveja", "ração", "racao", "shampoo", "condicionador", 
    "sabonete", "fralda", "detergente", "desinfetante", "limpador", "desodorante",
    "perfume", "creme dental", "escova dental", "brinquedo", "infantil educativo"
]

def classificar_produto(dados: Any, analise_dimensional: dict[str, Any], analise_anatel: dict[str, Any]) -> dict[str, Any]:
    titulo = dados.get("titulo", "").lower()
    try:
        import json
        pacote = json.loads(dados.get("atributos_json", "{}"))
        detalhes = pacote.get("detalhes_brutos", "").lower()
    except: detalhes = ""
    texto_focado = f"{titulo} {detalhes}"
    
    termos_fora = any(t in texto_focado for t in TERMOS_PRODUTO_FORA_DO_ESCOPO)
    eh_acessorio = any(t in titulo for t in TERMOS_ACESSORIO) and not any(t in titulo for t in ["chip", "gsm", "celular", "telefone"])
    indicio_mini = any(t in texto_focado for t in TERMOS_INDICIO_FORTE_MINI)
    
    if termos_fora or eh_acessorio: return {"classificacao": "DESCARTADO", "motivo_classificacao": "Produto fora do escopo ou acessório."}
    
    dimensoes_confiaveis = analise_dimensional.get("dimensoes_confiaveis") == "SIM"
    dentro_limite = analise_dimensional.get("dentro_limite_dimensional") == "SIM"
    status_requerimento = analise_anatel.get("situacao_requerimento_normalizada")
    situacao_anatel = analise_anatel.get("situacao_anatel")

    if not dimensoes_confiaveis:
        if indicio_mini: return {"classificacao": "SUSPEITO", "motivo_classificacao": "Indício forte de mini celular, mas dimensões não localizadas."}
        return {"classificacao": "NAO_CLASSIFICADO", "motivo_classificacao": "Informações insuficientes para concluir análise (dimensões e base faltantes/duvidosos)."}

    if not dentro_limite: return {"classificacao": "DESCARTADO", "motivo_classificacao": "Dimensões corporais maiores que o limite."}
    if status_requerimento in {"CANCELADA", "SUSPENSA"}: return {"classificacao": "IRREGULAR", "motivo_classificacao": f"Dimensões no limite e Homologação {status_requerimento.lower()}."}

    if situacao_anatel == "NAO_CLASSIFICADO": return {"classificacao": "NAO_CLASSIFICADO", "motivo_classificacao": analise_anatel.get("motivo_anatel")}
    if situacao_anatel == "REGULAR": return {"classificacao": "DESCARTADO", "motivo_classificacao": "Dimensões no limite, porém Anatel em conformidade."}

    return {"classificacao": "IRREGULAR", "motivo_classificacao": "Dimensões no limite e Anatel sem registro na base."}