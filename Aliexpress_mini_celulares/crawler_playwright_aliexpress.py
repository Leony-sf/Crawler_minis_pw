from __future__ import annotations

import asyncio
import json
import re
import sys
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import quote_plus

from playwright.async_api import TimeoutError as PlaywrightTimeoutError
from playwright.async_api import async_playwright

# Aponta para a pasta do Mercado Livre para reaproveitar as lógicas
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'ML_crawler')))

from base_anatel import BaseAnatel, analisar_situacao_anatel
from classificacao_aliexpress import analisar_dimensoes_produto, classificar_produto
from utils_aliexpress import (
    criar_pastas_saida,
    metadados_captura,
    gerar_id,
    hash_curto,
    rolar_pagina,
    salvar_parquet_incremental,
    slugify,
)

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/126.0.0.0 Safari/537.36"
)

def _valor_terminal(valor: Any, vazio: str = "NÃO LOCALIZADO") -> str:
    texto = str(valor or "").strip()
    return texto if texto else vazio

def _sim_nao_terminal(valor: Any) -> str:
    texto = str(valor or "").strip().upper()
    if texto == "SIM": return "SIM"
    if texto == "NAO_VERIFICADO": return "NÃO VERIFICADO"
    return "NÃO"

def _formatar_numero_cm(valor: Any) -> str:
    if valor in (None, ""): return ""
    try: numero = float(valor)
    except (TypeError, ValueError): return str(valor)
    return f"{numero:.2f}".rstrip("0").rstrip(".").replace(".", ",")

def _dimensoes_terminal(analise: dict) -> str:
    if analise.get("dimensoes_confiaveis") != "SIM": return "NÃO LOCALIZADAS"
    valores = [_formatar_numero_cm(analise.get("altura_cm")), _formatar_numero_cm(analise.get("largura_cm")), _formatar_numero_cm(analise.get("espessura_cm"))]
    valores = [v for v in valores if v]
    return " x ".join(valores) + " cm" if valores else "NÃO LOCALIZADAS"

def _log_auditoria_dimensoes(analise: dict) -> None:
    produto = _dimensoes_terminal(analise)
    resultado = str(analise.get("dentro_limite_dimensional") or "NAO_VERIFICADO").upper()
    situacao = "DENTRO DO LIMITE" if resultado == "SIM" else "ACIMA DO LIMITE" if resultado == "NAO" else "NÃO FOI POSSÍVEL VERIFICAR"
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] [INFO]  DIMENSÕES        Limite adotado : 12,0 x 5,5 cm")
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [INFO]  DIMENSÕES        Produto        : {produto}")
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [INFO]  DIMENSÕES        Origem         : {_valor_terminal(analise.get('origem_dimensoes'), 'não localizada')}")
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [INFO]  DIMENSÕES        Resultado      : {situacao}")

def _log_auditoria_anatel(dados: dict, anatel: dict) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [INFO]  ANATEL           Código         : anúncio={_valor_terminal(dados.get('codigo_anatel_principal'))} | base={_valor_terminal(anatel.get('codigo_base'))} | confere={_sim_nao_terminal(anatel.get('codigo_confere_base'))}")
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [INFO]  ANATEL           Situação Req.  : {_valor_terminal(anatel.get('situacao_requerimento_base'), 'NÃO LOCALIZADA')} | emitida={_sim_nao_terminal(anatel.get('requerimento_emitido'))}")
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [INFO]  ANATEL           Marca          : anúncio={_valor_terminal(dados.get('marca'))} | base={_valor_terminal(anatel.get('fabricante_base'))} | confere={_sim_nao_terminal(anatel.get('marca_confere_base'))}")
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [INFO]  ANATEL           Modelo         : anúncio={_valor_terminal(dados.get('modelo'))} | base={_valor_terminal(anatel.get('modelo_base'))} | confere={_sim_nao_terminal(anatel.get('modelo_confere_base'))}")
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [INFO]  ANATEL           Nome Com.      : anúncio={_valor_terminal(dados.get('nome_comercial'))} | base={_valor_terminal(anatel.get('nome_comercial_base'))} | confere={_sim_nao_terminal(anatel.get('nome_comercial_confere_base'))}")
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [INFO]  ANATEL           Resultado      : {_valor_terminal(anatel.get('situacao_anatel'), 'NÃO VERIFICADO')} — {_valor_terminal(anatel.get('motivo_anatel'), 'sem motivo')}")

def _log_auditoria_classificacao(linha: dict) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [INFO]  CLASSIFICAÇÃO    Destino        : {_valor_terminal(linha.get('classificacao'), 'NÃO DEFINIDO')}")
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [INFO]  CLASSIFICAÇÃO    Motivo         : {_valor_terminal(linha.get('motivo_classificacao'), 'sem motivo registrado')}")
    print("-" * 72)

def _extrair_codigo_anatel(atributos: dict, texto_pagina: str) -> str:
    padroes = [
        r"(?:anatel|homologa(?:cao|ção)|certifica(?:cao|ção)|certificado)[^0-9]{0,160}((?:\d[\s./-]*){8,14})",
        r"((?:\d[\s./-]*){8,14})[^a-z0-9]{0,100}(?:anatel|homologa(?:cao|ção)|certifica(?:cao|ção))",
    ]
    fontes = [f"{k}: {v}" for k, v in atributos.items() if any(t in k.lower() for t in ["anatel", "homolog", "certific"])]
    fontes.append(texto_pagina)
    for fonte in fontes:
        for p in padroes:
            for m in re.finditer(p, fonte, flags=re.IGNORECASE):
                digitos = re.sub(r"\D", "", m.group(1))
                if len(digitos) == 12:
                    return digitos
    return ""

def montar_url_busca(termo: str, pagina: int = 1) -> str:
    termo_url = quote_plus(termo)
    return f"https://pt.aliexpress.com/wholesale?SearchText={termo_url}&page={pagina}"

async def _fechar_popups_basicos(page) -> None:
    textos = ["Accept", "Aceitar", "Concordo", "I agree", "Got it", "Entendi", "Não, obrigado", "No thanks", "Continuar", "Continue"]
    for texto in textos:
        try:
            loc = page.get_by_text(texto, exact=False).first
            if await loc.count() > 0 and await loc.is_visible(timeout=500):
                await loc.click(timeout=500)
        except Exception:
            pass

    seletores = ["button[aria-label='Close']", "button[aria-label='close']", ".pop-close-btn", ".close-btn", "[class*='close']"]
    for seletor in seletores:
        try:
            loc = page.locator(seletor).first
            if await loc.count() > 0 and await loc.is_visible(timeout=500):
                await loc.click(timeout=500)
        except Exception:
            pass

async def _coletar_links_resultados(page, limite_restante: int) -> List[Dict[str, str]]:
    await rolar_pagina(page, passos=4, pausa=0.4)
    itens = await page.evaluate(
        """
        () => {
            const anchors = Array.from(document.querySelectorAll('a[href*="/item/"]'));
            const out = [];
            const vistos = new Set();
            for (const a of anchors) {
                let href = a.href || a.getAttribute('href') || '';
                if (!href.includes('/item/')) continue;
                href = href.split('?')[0];
                if (!href.startsWith('http')) href = new URL(href, location.href).href;
                if (vistos.has(href)) continue;
                vistos.add(href);

                const card = a.closest('[class*="search"], [class*="product"], [data-item-id], div') || a;
                const img = card.querySelector('img') || a.querySelector('img');
                const textoCard = (card.innerText || a.innerText || '').trim();
                const alt = img ? (img.alt || img.getAttribute('aria-label') || '') : '';
                const titleAttr = a.getAttribute('title') || '';
                const titulo = (titleAttr || alt || textoCard || '').trim();
                const imagem = img ? (img.src || img.getAttribute('src') || img.getAttribute('data-src') || '') : '';
                out.push({url: href, titulo_card: titulo, texto_card: textoCard, imagem_card: imagem});
            }
            return out;
        }
        """
    )
    return [item for i, item in enumerate(itens) if item.get("url") and item["url"] not in [x["url"] for x in itens[:i]]][:limite_restante]

async def _texto_primeiro(page, seletores: List[str], timeout: int = 1500) -> str:
    for seletor in seletores:
        try:
            loc = page.locator(seletor).first
            if await loc.count() > 0:
                texto = await loc.inner_text(timeout=timeout)
                if texto and texto.strip(): return texto.strip()
        except Exception:
            pass
    return ""

async def _atributo_primeiro(page, seletores: List[str], atributo: str = "src", timeout: int = 1000) -> str:
    for seletor in seletores:
        try:
            loc = page.locator(seletor).first
            if await loc.count() > 0:
                val = await loc.get_attribute(atributo, timeout=timeout)
                if val: return val
        except Exception:
            pass
    return ""

async def _capturar_comentarios(page) -> List[str]:
    comentarios = []
    
    try:
        await page.evaluate("window.scrollTo(0, 0)")
        await page.wait_for_timeout(1000)
    except Exception:
        pass

    await page.evaluate("""
        () => {
            const elementos = document.querySelectorAll('div, span, a, button, li');
            for(let el of elementos) {
                if(el.innerText && el.innerText.trim().match(/^(Avaliações|Reviews|Customer Reviews)/i)) {
                    el.click();
                }
            }
        }
    """)
    await page.wait_for_timeout(3000) 

    try:
        await page.evaluate("window.scrollBy(0, 800)")
        await page.wait_for_timeout(1000)
        await page.evaluate("window.scrollBy(0, 800)")
        await page.wait_for_timeout(1000)
    except Exception:
        pass

    comentarios_js = await page.evaluate('''
        () => {
            const out = [];
            const els = document.querySelectorAll(
                '[class*="feedback-item"], [class*="review-content"], [class*="buyer-review"], [class*="review-text"], .buyer-feedback, [data-pl="product-reviews"] span'
            );
            
            for(let el of els) {
                const txt = (el.innerText || '').replace(/\\s+/g, ' ').trim();
                if(txt.length > 15 && !txt.includes('AliExpress') && !out.includes(txt)) {
                    out.push(txt);
                }
            }
            return out.slice(0, 10);
        }
    ''')

    if comentarios_js:
        comentarios.extend(comentarios_js)

    if not comentarios:
        seletores = [
            "[class*='feedback-item']", 
            "[class*='review-content']", 
            ".buyer-feedback", 
            "[data-pl='product-reviews'] div",
            "[class*='review-item']"
        ]

        for seletor in seletores:
            try:
                locs = page.locator(seletor)
                count = await locs.count()
                for i in range(count):
                    txt = await locs.nth(i).inner_text(timeout=1000)
                    txt_clean = " ".join(txt.split())
                    
                    if len(txt_clean) > 15 and txt_clean not in comentarios:
                        comentarios.append(txt_clean)
                    
                    if len(comentarios) >= 10: 
                        break
            except Exception:
                continue

    print(f"[{datetime.now().strftime('%H:%M:%S')}] [INFO]  COMENTÁRIOS      Capturados: {len(comentarios)}")
    return comentarios[:10]

async def _capturar_detalhes_produto(page) -> Dict[str, Any]:
    await _fechar_popups_basicos(page)
    try:
        await page.wait_for_selector("h1, [data-pl='product-title'], .product-title", timeout=6000)
    except Exception:
        pass
    
    # 1. Rolar suavemente várias vezes para garantir o carregamento da seção (Lazy Load)
    for _ in range(3):
        await page.mouse.wheel(0, 800)
        await page.wait_for_timeout(1000)

    # 2. Clicar na aba "Detalhes" forçadamente via JS
    await page.evaluate("""
        () => {
            const abas = document.querySelectorAll('div, span, a, button, li');
            for (const aba of abas) {
                const txt = (aba.innerText || '').trim().toLowerCase();
                if (txt === 'detalhes' || txt === 'specifications' || txt === 'especificações') {
                    aba.click();
                }
            }
        }
    """)
    await page.wait_for_timeout(2000)

    # Rolar mais um pouco para centralizar a tabela
    await page.mouse.wheel(0, 800)
    await page.wait_for_timeout(1000)

    # 3. FORÇA BRUTA: Clicar no botão "Ver mais"
    # Etapa A: Usar o Playwright com force=True
    textos_alvo = ["Ver mais", "View More", "Show more", "Mais", "Mostrar mais"]
    for texto in textos_alvo:
        try:
            botoes = page.get_by_text(texto, exact=True)
            count = await botoes.count()
            for i in range(count):
                btn = botoes.nth(i)
                if await btn.is_visible():
                    await btn.scroll_into_view_if_needed()
                    await page.wait_for_timeout(500)
                    await btn.click(force=True, timeout=2000) 
                    await page.wait_for_timeout(1000)
        except Exception:
            pass

    # Etapa B: Varredura JS para interceptar qualquer texto "Ver mais" desgarrado no HTML
    await page.evaluate("""
        () => {
            const keywords = ['ver mais', 'view more', 'show more'];
            const tags = ['button', 'a', 'span', 'div'];
            
            for (const tag of tags) {
                const elementos = document.querySelectorAll(tag);
                for (const el of elementos) {
                    const txt = Array.from(el.childNodes)
                        .filter(node => node.nodeType === 3)
                        .map(node => node.textContent.trim().toLowerCase())
                        .join('');
                        
                    if (keywords.includes(txt)) {
                        el.click();
                        if (el.parentElement) el.parentElement.click();
                    }
                }
            }
            // Força clique em classes típicas desse botão no Ali
            const btnClasses = document.querySelectorAll('[class*="spec-more"], [class*="show-more"]');
            for(let b of btnClasses) b.click();
        }
    """)
    await page.wait_for_timeout(2500) # Pausa estendida para a tabela carregar visualmente

    # Uma última rolada para garantir que toda a tabela expandida subiu no DOM
    await page.mouse.wheel(0, 600)
    await page.wait_for_timeout(1500)

    titulo = await _texto_primeiro(page, ["h1", "[data-pl='product-title'], .product-title"])
    if not titulo:
        try: titulo = (await page.title()).replace("| AliExpress", "").strip()
        except Exception: titulo = ""

    preco = await _texto_primeiro(page, ["[data-pl='product-price']", ".product-price-value"])
    loja = await _texto_primeiro(page, ["[data-pl='store-name']", "a[href*='/store/']"])
    imagem = await _atributo_primeiro(page, ["img[class*='magnifier']", "[data-pl='product-image'] img", "img[src*='alicdn']"])

    texto_pagina = ""
    try:
        texto_pagina = await page.locator("body").inner_text(timeout=2500)
    except Exception:
        pass

    # 4. EXTRAÇÃO CORRIGIDA: Lendo tabelas com 4 ou mais colunas (O pulo do gato das imagens)
    atributos = await page.evaluate(
        """
        () => {
            const out = {};
            const els = document.querySelectorAll('li, tr, div.specification, div[class*="spec-item"], div[class*="prop-item"], .product-specs li, .product-prop, div[class*="base-attr"]');
            for (const el of els) {
                
                // Lê tabelas de 2 em 2 colunas para resolver o problema de múltiplas colunas na mesma linha
                if (el.tagName === 'TR' || el.tagName === 'DIV') {
                    const tds = el.querySelectorAll('td, th, .prop-name, .prop-value, .title, .desc');
                    if (tds.length >= 2) {
                        for (let i = 0; i < tds.length - 1; i += 2) {
                            const key = tds[i].innerText.trim();
                            const val = tds[i+1].innerText.trim();
                            if (key && val && key.length < 80) out[key] = val;
                        }
                        continue;
                    }
                }
                // Fallback para spans 
                const spans = el.querySelectorAll('span');
                if (spans.length >= 2) {
                    for (let i = 0; i < spans.length - 1; i += 2) {
                        const key = spans[i].innerText.trim();
                        const val = spans[i+1].innerText.trim();
                        if (key && val && key.length < 80 && val.length < 150) out[key] = val;
                    }
                    continue;
                }
                
                // Fallback para texto solto (ex: "Marca: Nokia")
                const txt = el.innerText || '';
                const parts = txt.split(/[:：]/);
                if (parts.length >= 2) {
                    const key = parts[0].trim();
                    const val = parts.slice(1).join(':').trim();
                    if (key && val && key.length < 80 && val.length < 150) out[key] = val;
                }
            }
            return out;
        }
        """
    )

    marca = ""
    modelo = ""
    nome_comercial = ""
    
    for k, v in atributos.items():
        kl = str(k).lower()
        if "brand" in kl or "marca" in kl: 
            marca = v
        elif "model" in kl or "modelo" in kl: 
            modelo = v
        elif "name" in kl or "nome" in kl or "comercial" in kl: 
            if not nome_comercial: nome_comercial = v

    codigo_anatel = _extrair_codigo_anatel(atributos, texto_pagina)
    comentarios = await _capturar_comentarios(page)

    return {
        "titulo": titulo,
        "preco": preco,
        "marca": marca,
        "modelo": modelo,
        "nome_comercial": nome_comercial,
        "codigo_anatel_principal": codigo_anatel,
        "imagem": imagem,
        "atributos": atributos,
        "descricao": texto_pagina[:8000],
        "texto_pagina": texto_pagina[:15000],
        "comentarios": comentarios,
    }

async def _print_produto(page, base_saida: Path, categoria_print: str, titulo: str, url: str) -> str:
    nome = f"{slugify(titulo, 70)}_{hash_curto(url)}.png"
    pasta = base_saida / "prints" / categoria_print
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / nome
    try:
        if page.is_closed():
            return ""
        await page.screenshot(path=str(caminho), full_page=False, timeout=8000)
        return str(caminho)
    except Exception as exc:
        print(f"[{datetime.now().strftime('%H:%M:%S')}] [AVISO]  PRINT            Falha ao capturar print: {exc}")
        return ""

async def rodar_crawler_aliexpress(
    queries: List[str],
    saida: str | None = None,
    limit: int = 50,
    max_paginas: int = 1,
    headless: bool = False,
    pausa_login: bool = True,
    user_data_dir: str = "perfil_aliexpress",
    base_anatel: BaseAnatel | None = None,
) -> List[Dict[str, Any]]:
    
    base_saida = criar_pastas_saida(saida)
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] [INFO]  ARQUIVOS         Pasta desta execução: {base_saida}")

    produtos: List[Dict[str, Any]] = []
    comentarios_lista: List[Dict[str, Any]] = []
    urls_visitadas = set()

    salvar_parquet_incremental(base_saida, produtos, comentarios_lista)

    async with async_playwright() as p:
        browser_context = await p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=headless,
            viewport={"width": 1366, "height": 900},
            locale="pt-BR",
            user_agent=DEFAULT_USER_AGENT,
            args=["--disable-blink-features=AutomationControlled", "--start-maximized"],
        )
        page = browser_context.pages[0] if browser_context.pages else await browser_context.new_page()
        page.set_default_timeout(12000)

        if pausa_login:
            print("\n========================================================================")
            print("PAUSA MANUAL")
            print("========================================================================")
            print("O navegador será aberto. Resolva login/captcha/cookies se aparecer.")
            await page.goto("https://pt.aliexpress.com/", wait_until="domcontentloaded", timeout=60000)
            await _fechar_popups_basicos(page)
            input("Pressione ENTER aqui no terminal para iniciar a coleta... ")

        for query in queries:
            if len(produtos) >= limit: break
            print(f"\n========================================================================")
            print(f"BUSCA: {query.upper()}")
            print("========================================================================")

            for pagina_num in range(1, max_paginas + 1):
                if len(produtos) >= limit: break
                url_busca = montar_url_busca(query, pagina_num)
                
                try:
                    await page.goto(url_busca, wait_until="commit", timeout=60000)
                    await page.wait_for_load_state("domcontentloaded", timeout=15000)
                    await page.wait_for_timeout(2500)
                    await _fechar_popups_basicos(page)
                except Exception as exc:
                    if "interrupted" in str(exc) or "net::ERR_ABORTED" in str(exc):
                        try:
                            await page.wait_for_load_state("domcontentloaded", timeout=15000)
                            await page.wait_for_timeout(2500)
                            await _fechar_popups_basicos(page)
                        except Exception:
                            continue
                    else:
                        continue

                links = await _coletar_links_resultados(page, max(0, limit - len(produtos)) * 2)

                for indice_produto, item in enumerate(links, start=1):
                    if len(produtos) >= limit: break
                    url_produto = item.get("url", "")
                    if not url_produto or url_produto in urls_visitadas: continue
                    urls_visitadas.add(url_produto)

                    url_com_hash = url_produto if "#" in url_produto else f"{url_produto}#nav-specification"

                    print(f"\n------------------------------------------------------------------------")
                    print(f"PRODUTO {indice_produto}/{len(links)}")
                    print(f"------------------------------------------------------------------------")
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] [INFO]  PRODUTO          {url_produto}")

                    produto_page = await browser_context.new_page()
                    produto_page.set_default_timeout(12000)
                    try:
                        await produto_page.goto(url_com_hash, wait_until="domcontentloaded", timeout=60000)
                        detalhes = await _capturar_detalhes_produto(produto_page)

                        titulo_final = detalhes.get("titulo") or item.get("titulo_card") or ""
                        
                        dados_para_ml: Dict[str, Any] = {
                            "titulo": titulo_final,
                            "descricao": detalhes.get("descricao", ""),
                            "atributos": detalhes.get("atributos", {}),
                            "marca": detalhes.get("marca", ""),
                            "modelo": detalhes.get("modelo", ""),
                            "nome_comercial": detalhes.get("nome_comercial", ""),
                            "codigo_anatel_principal": detalhes.get("codigo_anatel_principal", ""),
                            "url": url_produto,
                            "preco": detalhes.get("preco", ""),
                            "comentarios": detalhes.get("comentarios", [])
                        }

                        analise_dimensional = analisar_dimensoes_produto(dados_para_ml)
                        _log_auditoria_dimensoes(analise_dimensional)

                        anatel = analisar_situacao_anatel(
                            dados_para_ml["codigo_anatel_principal"],
                            dados_para_ml["marca"],
                            dados_para_ml["modelo"],
                            dados_para_ml["nome_comercial"],
                            base_anatel
                        )
                        _log_auditoria_anatel(dados_para_ml, anatel)

                        classificacao = classificar_produto(dados_para_ml, analise_dimensional, anatel)
                        classificacao.update(analise_dimensional)
                        
                        status_final = str(classificacao.get("classificacao") or "").upper()
                        motivo_final = str(classificacao.get("motivo_classificacao") or "")

                        _log_auditoria_classificacao(classificacao)

                        if status_final == "DESCARTADO":
                            continue

                        momento = datetime.now().astimezone()
                        pid = gerar_id(titulo_final, url_produto)

                        linha = {
                            "pid": pid,
                            "marketplace_id": "3",
                            "name": titulo_final,
                            "titulo": titulo_final,
                            "link": url_produto,
                            "url": url_produto,
                            "anatel_number": anatel.get("codigo_anatel_normalizado", ""),
                            "codigo_anatel_principal": dados_para_ml["codigo_anatel_principal"],
                            "brand": dados_para_ml["marca"],
                            "marca": dados_para_ml["marca"],
                            "price": dados_para_ml["preco"],
                            "preco": dados_para_ml["preco"],
                            "status": status_final.capitalize(),
                            "status_validacao": status_final,
                            "motivo_validacao": motivo_final,
                            "irregularity_reasons": motivo_final if status_final == "IRREGULAR" else "",
                            "motivo_irregularidade": motivo_final if status_final == "IRREGULAR" else "",
                            "warnings": motivo_final if status_final == "SUSPEITO" else anatel.get("motivo_anatel", ""),
                            "warning": motivo_final if status_final == "SUSPEITO" else "",
                            "created_at": momento.strftime("%Y-%m-%d"),
                            "modelo": dados_para_ml["modelo"],
                            "nome_comercial": dados_para_ml["nome_comercial"],
                            "nome_comercial_confere_base": anatel.get("nome_comercial_confere_base", ""),
                            "modelo_detalhado": "",
                            "modelo_alfanumerico": "",
                            "numero_modelo": dados_para_ml["modelo"],
                            "modelo_decisivo_label": "Modelo Extraído",
                            "modelo_decisivo": dados_para_ml["modelo"],
                            "fabricante": dados_para_ml["marca"],
                            "modo_match_base": anatel.get("situacao_anatel", ""),
                            "query_busca": query,
                            "descricao": dados_para_ml["descricao"],
                            "texto_pagina": detalhes.get("texto_pagina", ""),
                            "atributos_json": json.dumps(dados_para_ml["atributos"], ensure_ascii=False),
                            "total_comentarios": len(dados_para_ml["comentarios"]),
                            "codigo_anatel": anatel.get("codigo_anatel_normalizado") or dados_para_ml["codigo_anatel_principal"],
                            "dimensoes_encontradas": _dimensoes_terminal(analise_dimensional),
                        }
                        
                        linha.update(classificacao)
                        linha.update(anatel)
                        linha.update(metadados_captura(base_saida, momento))

                        if status_final == "IRREGULAR":
                            pasta_categoria = "irregulares"
                        elif status_final in ["NÃO CLASSIFICADO", "NAO CLASSIFICADO", "NAO_CLASSIFICADO"]:
                            pasta_categoria = "nao_classificados"
                        else:
                            pasta_categoria = "suspeitos"

                        linha["print_path"] = await _print_produto(produto_page, base_saida, pasta_categoria, titulo_final, url_produto)
                        
                        produtos.append(linha)

                        for ordem, txt_comentario in enumerate(dados_para_ml["comentarios"], start=1):
                            comentarios_lista.append({
                                "pid": pid,
                                "marketplace_id": "3",
                                "url": url_produto,
                                "link": url_produto,
                                "titulo": titulo_final,
                                "name": titulo_final,
                                "comentario_ordem": ordem,
                                "comment": txt_comentario,
                                "comentario": txt_comentario,
                                "created_at": linha["created_at"],
                                "query_busca": query,
                                "classificacao": status_final,
                                "status": status_final.capitalize(),
                                "status_validacao": status_final,
                                "codigo_anatel_principal": dados_para_ml["codigo_anatel_principal"],
                                "anatel_number": anatel.get("codigo_anatel_normalizado", ""),
                                "marca": dados_para_ml["marca"],
                                "brand": dados_para_ml["marca"],
                                "modelo": dados_para_ml["modelo"],
                                "data_hora_captura": linha["data_hora_captura"],
                                "data_hora_captura_iso": linha["data_hora_captura_iso"],
                                "referencia_captura": linha["referencia_captura"],
                                "pasta_saida_execucao": linha["pasta_saida_execucao"],
                                "caminho_saida_execucao": linha["caminho_saida_execucao"],
                            })

                        salvar_parquet_incremental(base_saida, produtos, comentarios_lista)

                    except PlaywrightTimeoutError:
                        pass
                    except Exception:
                        pass
                    finally:
                        try: await produto_page.close()
                        except Exception: pass

        await browser_context.close()

    salvar_parquet_incremental(base_saida, produtos, comentarios_lista)
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] [INFO]  SAÍDA            Arquivos salvos em: {base_saida.resolve()}")
    return produtos

def executar_sync(**kwargs):
    return asyncio.run(rodar_crawler_aliexpress(**kwargs))