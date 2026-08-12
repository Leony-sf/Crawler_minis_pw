from __future__ import annotations

import re
from typing import Any

from playwright.sync_api import Page

from base_anatel import normalizar_codigo_anatel
from utils import normalizar_chave, normalizar_texto


def _clicar_primeiro_visivel(
    page: Page,
    textos: list[str],
    timeout_ms: int = 1500,
) -> bool:
    for texto in textos:
        seletores = [
            f"button:has-text('{texto}')",
            f"a:has-text('{texto}')",
            f"span:has-text('{texto}')",
        ]
        for seletor in seletores:
            try:
                item = page.locator(seletor).first
                if item.count() and item.is_visible(timeout=500):
                    item.scroll_into_view_if_needed(timeout=timeout_ms)
                    item.click(timeout=timeout_ms)
                    page.wait_for_timeout(700)
                    return True
            except Exception:
                continue
    return False


def fechar_modais_leves(page: Page) -> None:
    _clicar_primeiro_visivel(
        page,
        [
            "Aceitar cookies",
            "Aceitar todos",
            "Entendi",
            "Mais tarde",
            "Agora não",
            "Depois",
            "Fechar",
        ],
        timeout_ms=1000,
    )


def expandir_ficha_tecnica(page: Page) -> None:
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

    for posicao in [400, 1000, 1800, 2800, 3800]:
        try:
            page.evaluate("(y) => window.scrollTo(0, y)", posicao)
            page.wait_for_timeout(350)
        except Exception:
            pass

        if _clicar_primeiro_visivel(page, textos, timeout_ms=1400):
            return


def coletar_atributos(page: Page) -> dict[str, str]:
    script = r"""
    () => {
      const saida = [];
      const vistos = new Set();

      const limpar = (valor) =>
        (valor || '').replace(/\s+/g, ' ').trim();

      const adicionar = (rotulo, valor) => {
        rotulo = limpar(rotulo);
        valor = limpar(valor);
        if (!rotulo || !valor || rotulo === valor) return;
        const chave = `${rotulo}=>${valor}`;
        if (vistos.has(chave)) return;
        vistos.add(chave);
        saida.push([rotulo, valor]);
      };

      for (const linha of document.querySelectorAll('tr')) {
        const celulas = Array.from(linha.children)
          .map((item) => limpar(item.innerText || item.textContent));
        if (celulas.length >= 2) {
          adicionar(celulas[0], celulas.slice(1).join(' '));
        }
      }

      const seletores = [
        '.ui-pdp-specs__table tr',
        '.andes-table__row',
        '[class*="spec"] li',
        '[class*="attribute"] li',
        '[class*="technical"] li'
      ];

      for (const seletor of seletores) {
        for (const elemento of document.querySelectorAll(seletor)) {
          const filhos = Array.from(elemento.children)
            .map((item) => limpar(item.innerText || item.textContent))
            .filter(Boolean);
          if (filhos.length >= 2) {
            adicionar(filhos[0], filhos.slice(1).join(' '));
          }
        }
      }

      for (const elemento of document.querySelectorAll('div, li')) {
        const filhos = Array.from(elemento.children)
          .map((item) => limpar(item.innerText || item.textContent))
          .filter(Boolean);

        if (
          filhos.length === 2 &&
          filhos[0].length <= 90 &&
          filhos[1].length <= 260
        ) {
          adicionar(filhos[0], filhos[1]);
        }
      }

      return saida.slice(0, 400);
    }
    """

    try:
        pares = page.evaluate(script) or []
    except Exception:
        pares = []

    atributos: dict[str, str] = {}
    for rotulo, valor in pares:
        chave = str(rotulo or "").strip()
        conteudo = str(valor or "").strip()
        if not chave or not conteudo:
            continue
        chave_norm = normalizar_chave(chave)
        if chave_norm not in atributos or len(conteudo) < len(atributos[chave_norm]):
            atributos[chave_norm] = conteudo

    return atributos


def _valor_por_rotulos(
    atributos: dict[str, str],
    rotulos: list[str],
    excluir: list[str] | None = None,
) -> str:
    rotulos_norm = [normalizar_chave(item) for item in rotulos]
    excluir_norm = [normalizar_chave(item) for item in (excluir or [])]

    for chave, valor in atributos.items():
        if any(item in chave for item in excluir_norm):
            continue
        if any(
            chave == rotulo or chave.endswith(rotulo) or rotulo in chave
            for rotulo in rotulos_norm
        ):
            return str(valor or "").strip()
    return ""


def _texto_visivel(page: Page) -> str:
    try:
        return page.locator("body").inner_text(timeout=6000)
    except Exception:
        return ""


def _titulo(page: Page) -> str:
    seletores = [
        "h1.ui-pdp-title",
        "h1",
        "meta[property='og:title']",
    ]

    for seletor in seletores:
        try:
            item = page.locator(seletor).first
            if not item.count():
                continue
            if seletor.startswith("meta"):
                valor = item.get_attribute("content")
            else:
                valor = item.inner_text(timeout=2500)
            if valor and valor.strip():
                return valor.strip()
        except Exception:
            continue
    return ""


def _preco(page: Page) -> str:
    seletores = [
        "meta[itemprop='price']",
        ".ui-pdp-price__second-line .andes-money-amount",
        ".andes-money-amount",
    ]

    for seletor in seletores:
        try:
            item = page.locator(seletor).first
            if not item.count():
                continue
            if seletor.startswith("meta"):
                valor = item.get_attribute("content")
            else:
                valor = item.inner_text(timeout=2000)
            if valor and valor.strip():
                return " ".join(valor.split())
        except Exception:
            continue
    return ""


def extrair_codigo_anatel(
    atributos: dict[str, str],
    texto_pagina: str,
) -> str:
    padroes = [
        r"(?:anatel|homologa(?:cao|ção)|certifica(?:cao|ção)|certificado)"
        r"[^0-9]{0,160}((?:\d[\s./-]*){8,14})",
        r"((?:\d[\s./-]*){8,14})[^a-z0-9]{0,100}"
        r"(?:anatel|homologa(?:cao|ção)|certifica(?:cao|ção))",
    ]

    fontes: list[str] = []
    for chave, valor in atributos.items():
        if any(termo in chave for termo in ["anatel", "homolog", "certific"]):
            fontes.append(f"{chave}: {valor}")
    fontes.append(texto_pagina)

    for fonte in fontes:
        fonte_norm = normalizar_texto(fonte)
        for padrao in padroes:
            for match in re.finditer(padrao, fonte_norm, flags=re.IGNORECASE):
                codigo = normalizar_codigo_anatel(match.group(1))
                if len(codigo) == 12:
                    return codigo
    return ""


def capturar_comentarios(page: Page, limite: int = 10) -> list[str]:
    if limite <= 0:
        return []

    try:
        for _ in range(3):
            page.mouse.wheel(0, 1400)
            page.wait_for_timeout(650)
    except Exception:
        pass

    seletores = [
        ".ui-review-capability-comments__comment__content",
        ".ui-review-capability-comments__comment",
        ".ui-pdp-review__comment",
        "[data-testid*='review']",
        "[class*='review'] [class*='comment']",
    ]

    comentarios: list[str] = []
    for seletor in seletores:
        try:
            itens = page.locator(seletor)
            for indice in range(itens.count()):
                texto = " ".join(
                    itens.nth(indice).inner_text(timeout=1200).split()
                )
                if len(texto) < 15 or texto in comentarios:
                    continue
                comentarios.append(texto)
                if len(comentarios) >= limite:
                    return comentarios
        except Exception:
            continue

    return comentarios


def extrair_produto(
    page: Page,
    capturar_reviews: bool = True,
) -> dict[str, Any]:
    fechar_modais_leves(page)
    expandir_ficha_tecnica(page)
    atributos = coletar_atributos(page)
    texto_pagina = _texto_visivel(page)

    marca = _valor_por_rotulos(
        atributos,
        ["marca", "fabricante"],
    )
    modelo = _valor_por_rotulos(
        atributos,
        ["modelo"],
        excluir=[
            "processador",
            "modelo detalhado",
            "modelo alfanumerico",
            "numero do modelo",
        ],
    )
    modelo_detalhado = _valor_por_rotulos(
        atributos,
        ["modelo detalhado"],
        excluir=["processador"],
    )
    modelo_alfanumerico = _valor_por_rotulos(
        atributos,
        ["modelo alfanumerico", "modelo alfanumérico"],
        excluir=["processador"],
    )
    numero_modelo = _valor_por_rotulos(
        atributos,
        ["numero do modelo", "número do modelo"],
        excluir=["processador"],
    )

    if not modelo:
        modelo = (
            modelo_detalhado
            or modelo_alfanumerico
            or numero_modelo
        )

    titulo = _titulo(page)
    codigo_anatel = extrair_codigo_anatel(atributos, texto_pagina)

    descricao = ""
    for seletor in [
        ".ui-pdp-description__content",
        ".ui-pdp-description",
        "[class*='description']",
    ]:
        try:
            item = page.locator(seletor).first
            if item.count():
                descricao = item.inner_text(timeout=2500).strip()
                if descricao:
                    break
        except Exception:
            continue

    comentarios = (
        capturar_comentarios(page, limite=10)
        if capturar_reviews else []
    )

    return {
        "url": page.url,
        "titulo": titulo,
        "preco": _preco(page),
        "marca": marca,
        "fabricante": marca,
        "modelo": modelo,
        "modelo_detalhado": modelo_detalhado,
        "modelo_alfanumerico": modelo_alfanumerico,
        "numero_modelo": numero_modelo,
        "codigo_anatel_principal": codigo_anatel,
        "descricao": descricao,
        "texto_pagina": texto_pagina,
        "atributos": atributos,
        "comentarios": comentarios,
    }
