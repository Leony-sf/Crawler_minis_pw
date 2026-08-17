from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from typing import Any

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from .base_anatel import BaseAnatel, normalizar_homologacao_base
from .utils import apenas_alnum, bloco, gerar_id, log, normalizar_chave, normalizar_texto, remover_acentos


LABELS_MODELO_VALIDAR = [
    "Modelo",
    "Modelo detalhado",
    "Modelo alfanumérico",
    "Modelo alfanumerico",
    "Número do modelo",
    "Numero do modelo",
]
LABELS_MODELO_IGNORAR = [
    "Modelo do processador",
    "Modelo de processador",
]


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


def _click_suave(page: Page, locator_textos: list[str], timeout_ms: int = 1500) -> bool:
    for texto in locator_textos:
        seletores = [
            f"button:has-text('{texto}')",
            f"a:has-text('{texto}')",
            f"span:has-text('{texto}')",
        ]
        for sel in seletores:
            try:
                loc = page.locator(sel).first
                if loc.count() and loc.is_visible(timeout=400):
                    loc.scroll_into_view_if_needed(timeout=timeout_ms)
                    page.wait_for_timeout(250)
                    loc.click(timeout=timeout_ms)
                    page.wait_for_timeout(900)
                    return True
            except Exception:
                continue
    return False


def fechar_modais_leves(page: Page) -> None:
    textos = [
        "Aceitar cookies",
        "Entendi",
        "Mais tarde",
        "Agora não",
        "Depois",
        "Fechar",
    ]
    _click_suave(page, textos, timeout_ms=1000)


def expandir_ficha_tecnica(page: Page) -> bool:
    textos = [
        "Ver todas as características",
        "Ver todas as caracteristicas",
        "Ver características",
        "Ver caracteristicas",
        "Ver mais características",
        "Ver mais caracteristicas",
        "Ficha técnica",
        "Ficha tecnica",
    ]

    # Scroll gradual para ativar lazy-load.
    for y in [0, 700, 1400, 2200, 3200]:
        try:
            page.evaluate("window.scrollTo(0, arguments[0])", y)
            page.wait_for_timeout(350)
        except Exception:
            pass
        if _click_suave(page, textos, timeout_ms=1400):
            log("anatel ml", "Ficha técnica/características expandida.")
            return True
    return False


def _coletar_atributos(page: Page) -> dict[str, str]:
    """Coleta pares label/valor da ficha técnica do Mercado Livre."""
    script = r"""
    () => {
      const out = [];
      const seen = new Set();
      function clean(s) { return (s || '').replace(/\s+/g, ' ').trim(); }
      function push(label, value) {
        label = clean(label); value = clean(value);
        if (!label || !value || label === value) return;
        const key = `${label}=>${value}`;
        if (seen.has(key)) return;
        seen.add(key); out.push([label, value]);
      }

      // Tabelas reais.
      for (const tr of document.querySelectorAll('tr')) {
        const cells = Array.from(tr.children).map(c => clean(c.innerText || c.textContent));
        if (cells.length >= 2) push(cells[0], cells.slice(1).join(' '));
      }

      // Linhas visuais do ML em divs/sections.
      const candidates = Array.from(document.querySelectorAll('div, li, section'));
      for (const el of candidates) {
        const children = Array.from(el.children).filter(c => clean(c.innerText || c.textContent));
        if (children.length === 2) {
          const a = clean(children[0].innerText || children[0].textContent);
          const b = clean(children[1].innerText || children[1].textContent);
          if (a.length <= 80 && b.length <= 220) push(a, b);
        }
      }
      return out.slice(0, 300);
    }
    """
    pares = []
    try:
        pares = page.evaluate(script) or []
    except Exception:
        pares = []

    attrs: dict[str, str] = {}
    for label, value in pares:
        label_limpo = normalizar_texto(label)
        value_limpo = normalizar_texto(value)
        if not label_limpo or not value_limpo:
            continue
        chave = normalizar_chave(label_limpo)
        # Evita sobrescrever um valor bom por bloco gigante.
        if chave not in attrs or len(attrs[chave]) > len(value_limpo):
            attrs[chave] = value_limpo
    return attrs


def _valor_por_labels(attrs: dict[str, str], labels: list[str], excluir: list[str] | None = None) -> str:
    excluir_norm = [normalizar_chave(x) for x in (excluir or [])]
    labels_norm = [normalizar_chave(x) for x in labels]
    for chave, valor in attrs.items():
        if any(ex in chave for ex in excluir_norm):
            continue
        for label in labels_norm:
            # igualdade ou label contido de forma segura
            if chave == label or chave.endswith(label) or label in chave:
                return valor
    return ""


def extrair_codigo_de_texto(texto: str) -> str:
    texto = normalizar_texto(texto)
    if not texto:
        return ""
    texto_norm = remover_acentos(texto)
    padroes = [
        r"(?i)(?:anatel|homologacao|homologado|certificacao|certificado|numero\s+de\s+homologacao|codigo\s+anatel)[^0-9]{0,180}((?:\d[\s.\-/]*){8,14})(?![\s.\-/]*\d)",
        r"(?i)((?:\d[\s.\-/]*){8,14})(?![\s.\-/]*\d)[^a-z0-9]{0,180}(?:anatel|homologacao|homologado|certificacao|certificado)",
    ]
    candidatos: list[str] = []
    for padrao in padroes:
        for m in re.finditer(padrao, texto_norm):
            dig = re.sub(r"\D", "", m.group(1) or "")
            if 8 <= len(dig) <= 14:
                candidatos.append(dig)
    for c in candidatos:
        if len(c) == 12:
            return c
    return candidatos[0] if candidatos else ""


def extrair_codigo_anatel(page: Page, attrs: dict[str, str]) -> str:
    # 1. Busca nos atributos da ficha técnica.
    for chave, valor in attrs.items():
        if any(p in chave for p in ["anatel", "homolog", "certific"]):
            codigo = extrair_codigo_de_texto(f"{chave} {valor}")
            if codigo:
                return codigo

    # 2. Busca em janelas do texto visível.
    try:
        texto = page.locator("body").inner_text(timeout=3000)
    except Exception:
        texto = ""
    texto = normalizar_texto(texto)
    for termo in ["anatel", "homolog", "certific"]:
        for m in re.finditer(termo, texto, flags=re.IGNORECASE):
            ini = max(0, m.start() - 240)
            fim = min(len(texto), m.end() + 320)
            codigo = extrair_codigo_de_texto(texto[ini:fim])
            if codigo:
                return codigo
    return ""


def capturar_comentarios(page: Page, limite: int = 10) -> list[str]:
    bloco("comentários")
    log("comentários", f"Tentando capturar até {limite} comentários.")
    comentarios: list[str] = []

    textos_botao = [
        "Ver todas as opiniões",
        "Ver opiniões",
        "Opiniões",
        "Ver avaliações",
        "Avaliações",
    ]
    _click_suave(page, textos_botao, timeout_ms=1200)
    try:
        page.wait_for_timeout(1000)
    except Exception:
        pass

    seletores = [
        ".ui-review-capability-comments__comment__content",
        ".ui-review-capability-comments__comment__content p",
        ".ui-review-capability__comment",
        ".ui-review-capability-comments__comment",
        "[data-testid*='comment']",
    ]

    for _ in range(10):
        for sel in seletores:
            try:
                for txt in page.locator(sel).all_inner_texts():
                    txt = normalizar_texto(txt)
                    if len(txt) >= 3 and txt not in comentarios:
                        comentarios.append(txt)
                    if len(comentarios) >= limite:
                        break
            except Exception:
                pass
            if len(comentarios) >= limite:
                break
        if len(comentarios) >= limite:
            break
        try:
            page.mouse.wheel(0, 900)
            page.wait_for_timeout(450)
        except Exception:
            break

    log("comentários", f"Comentários capturados: {len(comentarios[:limite])}")
    return comentarios[:limite]


def extrair_produto(page: Page, capturar_reviews: bool = True) -> DadosProduto:
    fechar_modais_leves(page)
    expandir_ficha_tecnica(page)

    try:
        titulo = page.locator("h1, .ui-pdp-title").first.inner_text(timeout=6000)
    except Exception:
        titulo = ""

    try:
        preco = page.locator(".andes-money-amount__fraction, .price-tag-fraction").first.inner_text(timeout=1500)
    except Exception:
        preco = ""

    attrs = _coletar_atributos(page)

    marca = _valor_por_labels(attrs, ["Marca"])
    fabricante = _valor_por_labels(attrs, ["Fabricante"])
    modelo = _valor_por_labels(attrs, ["Modelo"], excluir=LABELS_MODELO_IGNORAR + ["Modelo detalhado", "Modelo alfanumérico", "Modelo alfanumerico"])
    modelo_detalhado = _valor_por_labels(attrs, ["Modelo detalhado"])
    modelo_alfanumerico = _valor_por_labels(attrs, ["Modelo alfanumérico", "Modelo alfanumerico"])
    numero_modelo = _valor_por_labels(attrs, ["Número do modelo", "Numero do modelo"])

    codigo = extrair_codigo_anatel(page, attrs)
    codigo_norm = normalizar_homologacao_base(codigo) if codigo else ""

    comentarios = capturar_comentarios(page, limite=10) if capturar_reviews else []

    return DadosProduto(
        url=page.url,
        titulo=normalizar_texto(titulo),
        preco=normalizar_texto(preco),
        codigo_anatel_principal=codigo,
        codigo_anatel_normalizado=codigo_norm,
        marca=normalizar_texto(marca),
        fabricante=normalizar_texto(fabricante),
        modelo=normalizar_texto(modelo),
        modelo_detalhado=normalizar_texto(modelo_detalhado),
        modelo_alfanumerico=normalizar_texto(modelo_alfanumerico),
        numero_modelo=normalizar_texto(numero_modelo),
        atributos_json=json.dumps(attrs, ensure_ascii=False),
        comentarios=comentarios,
    )


def _alias_marca(marca: str) -> set[str]:
    m = remover_acentos(marca)
    tokens = set(re.findall(r"[a-z0-9]+", m))
    aliases = set(tokens)
    joined = " ".join(tokens)
    regras = {
        "xiaomi": ["xiaomi", "redmi", "poco", "mi"],
        "apple": ["apple", "iphone", "ipad", "airpods", "macbook"],
        "samsung": ["samsung", "galaxy"],
        "motorola": ["motorola", "moto"],
        "oppo": ["oppo"],
        "realme": ["realme"],
        "asus": ["asus", "rog", "zenfone"],
        "doogee": ["doogee"],
        "umidigi": ["umidigi"],
        "infinix": ["infinix"],
        "honor": ["honor"],
        "huawei": ["huawei"],
        "nokia": ["nokia"],
        "positivo": ["positivo"],
        "multilaser": ["multilaser", "multi"],
        "tcl": ["tcl"],
    }
    for canon, vals in regras.items():
        if any(v in tokens or v in joined for v in vals):
            aliases.add(canon)
            aliases.update(vals)
    return {a for a in aliases if len(a) >= 2}


def marca_compativel(marca_capturada: str, fabricante_base: str) -> bool:
    marca_capturada = normalizar_texto(marca_capturada)
    fabricante_base = normalizar_texto(fabricante_base)
    if not marca_capturada or not fabricante_base:
        return False
    aliases = _alias_marca(marca_capturada)
    fab_norm = remover_acentos(fabricante_base)
    fab_tokens = set(re.findall(r"[a-z0-9]+", fab_norm))
    for alias in aliases:
        if alias in fab_tokens or alias in fab_norm:
            return True
    return False


def _normalizar_modelo_comparacao(valor: str) -> str:
    """Normaliza modelo para comparação estrita.

    Remove espaços, hífens, barras e demais pontuações, mas NÃO aceita
    compatibilidade por prefixo/contém. Essa regra corrige casos como:

    Base: SM-A075M/DS
    Anúncio: SM-A075MZGRZTO

    Antes isso podia passar por prefixo. Agora é divergente.
    """
    return apenas_alnum(valor)


def _partes_modelo_no_campo(valor: str) -> list[str]:
    """Detecta quando o próprio campo decisivo traz mais de um modelo.

    Regra do documento: se o anúncio possuir dois modelos no campo usado
    para decisão, deve ser IRREGULAR, mesmo que um deles bata com a base.

    Não separamos por barra (/), pois modelos reais da base podem conter
    variações como SM-A075M/DS.
    """
    txt = normalizar_texto(valor)
    if not txt:
        return []

    partes = re.split(
        r"\s*(?:,|;|\||\s+\+\s+|\s+e\s+|\s+ou\s+)\s*",
        txt,
        flags=re.IGNORECASE,
    )

    saida: list[str] = []
    vistos: set[str] = set()

    for parte in partes:
        parte = normalizar_texto(parte)
        chave = _normalizar_modelo_comparacao(parte)

        # Evita contar textos muito genéricos ou lixo de quebra de layout.
        if len(chave) < 3:
            continue

        if chave not in vistos:
            vistos.add(chave)
            saida.append(parte)

    return saida


def modelo_compativel(modelo_capturado: str, modelo_base: str) -> bool:
    """Compara modelo capturado contra coluna Modelo da base ANATEL.

    A comparação agora é estrita após normalização alfanumérica:
    - aceita diferenças de pontuação/espaço/hífen/barra;
    - NÃO aceita prefixo;
    - NÃO aceita substring;
    - se houver vários modelos na base para o mesmo código/prefixo,
      a validação deve chamar esta função contra cada candidato.
    """
    a = _normalizar_modelo_comparacao(modelo_capturado)
    b = _normalizar_modelo_comparacao(modelo_base)

    if not a or not b:
        return False

    return a == b


def _modelos_capturados(dados: DadosProduto) -> dict[str, str]:
    modelos = {
        "Modelo": dados.modelo,
        "Modelo detalhado": dados.modelo_detalhado,
        "Modelo alfanumérico": dados.modelo_alfanumerico,
        "Número do modelo": dados.numero_modelo,
    }
    return {k: normalizar_texto(v) for k, v in modelos.items() if normalizar_texto(v)}


def _modelo_decisivo_capturado(dados: DadosProduto) -> tuple[str, str]:
    """Escolhe apenas um modelo para decidir a regularidade.

    Prioridade definida para o Mercado Livre:
    1) Modelo alfanumérico, quando existir;
    2) Modelo detalhado, quando não existir modelo alfanumérico;
    3) Modelo, quando não existir modelo detalhado.

    O campo "Número do modelo" deixa de ser usado na decisão.
    Ele pode continuar sendo salvo como informação, mas não define Regular/Irregular.
    """
    prioridade = [
        ("Modelo alfanumérico", dados.modelo_alfanumerico),
        ("Modelo detalhado", dados.modelo_detalhado),
        ("Modelo", dados.modelo),
    ]

    for label, valor in prioridade:
        valor_norm = normalizar_texto(valor)
        if valor_norm:
            return label, valor_norm

    return "", ""


def _amazon_detalhes_produto_encontrados(dados: DadosProduto) -> bool | None:
    """Lê a evidência salva pelo extrator Amazon.

    Retorna:
    - True: detalhes encontrados;
    - False: detalhes explicitamente não encontrados;
    - None: evidência não existe/arquivo antigo/outro marketplace.
    """
    try:
        pacote = json.loads(dados.atributos_json or "{}")
        if isinstance(pacote, dict) and "detalhes_produto_encontrados" in pacote:
            return bool(pacote.get("detalhes_produto_encontrados"))
    except Exception:
        pass
    return None


def validar_produto(dados: DadosProduto, base: BaseAnatel | None) -> dict[str, Any]:
    """Valida código, marca e modelo decisivo contra a base ANATEL.

    Regras atuais:
    - sem código ANATEL => IRREGULAR;
    - código fora da base e sem prefixo válido => IRREGULAR;
    - marca capturada divergente da base => IRREGULAR;
    - modelo decisivo divergente da coluna Modelo da base => IRREGULAR.

    Modelo decisivo segue a prioridade:
    Modelo alfanumérico > Modelo detalhado > Modelo.
    O campo Número do modelo não é usado para decidir Regular/Irregular.
    """
    motivos_irreg: list[str] = []
    avisos: list[str] = []

    detalhes_amazon = _amazon_detalhes_produto_encontrados(dados)
    if detalhes_amazon is False:
        motivos_irreg.append("Abas/seção de detalhes do produto não encontradas na Amazon")

    if not normalizar_texto(dados.marca):
        motivos_irreg.append("Marca não capturada no anúncio")

    label_decisivo_pre, modelo_decisivo_pre = _modelo_decisivo_capturado(dados)
    if not modelo_decisivo_pre:
        motivos_irreg.append("Modelo não capturado no anúncio")

    codigo = dados.codigo_anatel_normalizado or normalizar_homologacao_base(dados.codigo_anatel_principal)

    bloco("anatel")
    if not codigo:
        motivos_irreg.append("Código ANATEL não encontrado")
        log("anatel", "Código capturado: não encontrado")
    else:
        log("anatel", f"Código capturado: {dados.codigo_anatel_principal}")
        log("anatel", f"Código normalizado: {codigo}")

    if not codigo:
        status = "IRREGULAR"
        return _resultado_validacao(status, motivos_irreg, avisos, modo_base="sem_codigo")

    if base is None:
        avisos.append("Código ANATEL capturado, mas nenhuma base foi informada")
        return _resultado_validacao("SEM_BASE", motivos_irreg, avisos, modo_base="sem_base")

    modo, candidatos = base.candidatos_para_codigo(codigo)
    pref = codigo[: base.prefix_len]

    bloco("base")
    log("base", f"Código exato no CSV: {'SIM' if modo == 'exato' else 'NÃO'}")
    log("base", f"Prefixo {pref} no CSV: {'SIM' if modo in ['exato', 'prefixo'] else 'NÃO'}")

    if modo == "nenhum" or candidatos.empty:
        motivos_irreg.append(f"Código ANATEL {codigo} não existe na base nem por prefixo {base.prefix_len}")
        return _resultado_validacao("IRREGULAR", motivos_irreg, avisos, modo_base="nenhum")

    if modo == "prefixo":
        avisos.append(f"Código sem match exato, mas prefixo {pref} existe na base")

    # Marca capturada x fabricante/marca da base.
    bloco("marca x base")
    if dados.marca:
        fabricantes = [normalizar_texto(v) for v in candidatos.get("fabricante_base", []).tolist() if normalizar_texto(v)]
        if fabricantes:
            ok_marca = any(marca_compativel(dados.marca, fab) for fab in fabricantes)
            log("marca x base", f"Marca capturada: {dados.marca}")
            log("marca x base", f"Fabricantes candidatos: {', '.join(fabricantes[:5])}")
            if not ok_marca:
                motivos_irreg.append(
                    f"Marca '{dados.marca}' diverge da base para o código/prefixo. Base encontrada: {', '.join(fabricantes[:5])}"
                )
        else:
            avisos.append("Base não possui fabricante para validar marca")
    else:
        log("marca x base", "Marca capturada: não encontrada")

    # Modelo decisivo capturado x coluna Modelo da base.
    # Prioridade: Modelo alfanumérico > Modelo detalhado > Modelo.
    # Número do modelo fica apenas como informação, não como decisão.
    bloco("modelo x base")
    modelos_base = [normalizar_texto(v) for v in candidatos.get("modelo_base", []).tolist() if normalizar_texto(v)]
    modelos_cap = _modelos_capturados(dados)
    label_decisivo, modelo_decisivo = _modelo_decisivo_capturado(dados)

    if modelos_base:
        log("modelo x base", f"Modelos base candidatos: {', '.join(modelos_base[:8])}")

        if modelos_cap:
            log("modelo x base", "Modelos capturados no anúncio:")
            for label, valor in modelos_cap.items():
                marcador = " usado na decisão" if label == label_decisivo else " apenas informativo"
                log("modelo x base", f"- {label}: {valor} ({marcador})")

        if modelo_decisivo:
            partes_decisivo = _partes_modelo_no_campo(modelo_decisivo)

            if len(partes_decisivo) > 1:
                log(
                    "modelo x base",
                    f"Modelo decisivo: {label_decisivo} = {modelo_decisivo} => DIVERGENTE",
                )
                log(
                    "modelo x base",
                    f"Mais de um modelo detectado no campo decisivo: {', '.join(partes_decisivo)}",
                )
                motivos_irreg.append(
                    f"{label_decisivo} possui mais de um modelo no anúncio: "
                    f"{', '.join(partes_decisivo)}. O anúncio não pode possuir dois modelos."
                )
            else:
                ok_modelo = any(modelo_compativel(modelo_decisivo, mb) for mb in modelos_base)
                log(
                    "modelo x base",
                    f"Modelo decisivo: {label_decisivo} = {modelo_decisivo} => "
                    f"{'compatível' if ok_modelo else 'DIVERGENTE'}",
                )
                if not ok_modelo:
                    motivos_irreg.append(
                        f"{label_decisivo} '{modelo_decisivo}' diverge da coluna Modelo da base. "
                        f"Base encontrada: {', '.join(modelos_base[:8])}"
                    )
        else:
            log("modelo x base", "Nenhum campo de modelo foi capturado no anúncio")
    else:
        avisos.append("Base não possui coluna/valor de Modelo para validar modelos")

    status = "IRREGULAR" if motivos_irreg else "REGULAR"
    return _resultado_validacao(status, motivos_irreg, avisos, modo_base=modo)


def _resultado_validacao(status: str, motivos_irreg: list[str], avisos: list[str], modo_base: str) -> dict[str, Any]:
    motivos = motivos_irreg + avisos
    bloco("resultado")
    log("resultado", f"Situação final: {status}")
    if motivos_irreg:
        log("resultado", "Irregularidades:")
        for m in motivos_irreg:
            print(f"- {m}")
    if avisos:
        log("resultado", "Avisos:")
        for a in avisos:
            print(f"- {a}")
    return {
        "status_validacao": status,
        "motivo_validacao": "; ".join(motivos),
        "irregularity_reasons": "; ".join(motivos_irreg),
        "warnings": "; ".join(avisos),
        "modo_match_base": modo_base,
    }


def dados_para_linha(dados: DadosProduto, validacao: dict[str, Any]) -> dict[str, Any]:
    status = validacao.get("status_validacao", "")
    pid = gerar_id(dados.titulo, dados.marca, dados.codigo_anatel_normalizado, dados.url)
    modelos = _modelos_capturados(dados)
    modelo_decisivo_label, modelo_decisivo_valor = _modelo_decisivo_capturado(dados)
    linha = {
        "pid": pid,
        "marketplace_id": "2",
        "name": dados.titulo,
        "titulo": dados.titulo,
        "link": dados.url,
        "url": dados.url,
        "anatel_number": dados.codigo_anatel_normalizado,
        "codigo_anatel_principal": dados.codigo_anatel_normalizado,
        "brand": dados.marca,
        "marca": dados.marca,
        "price": dados.preco,
        "preco": dados.preco,
        "reviewers": "",
        "status": "Irregular" if status == "IRREGULAR" else ("Regular" if status == "REGULAR" else status),
        "status_validacao": status,
        "irregularity_reasons": validacao.get("irregularity_reasons", ""),
        "motivo_validacao": validacao.get("motivo_validacao", ""),
        "warnings": validacao.get("warnings", ""),
        "created_at": "",
        "modelo": dados.modelo,
        "modelo_detalhado": dados.modelo_detalhado,
        "modelo_alfanumerico": dados.modelo_alfanumerico,
        "numero_modelo": dados.numero_modelo,
        "modelo_decisivo_label": modelo_decisivo_label,
        "modelo_decisivo": modelo_decisivo_valor,
        "modelo_decisivo_partes_json": json.dumps(_partes_modelo_no_campo(modelo_decisivo_valor), ensure_ascii=False),
        "modelos_capturados_json": json.dumps(modelos, ensure_ascii=False),
        "fabricante": dados.fabricante,
        "modo_match_base": validacao.get("modo_match_base", ""),
    }
    return linha
