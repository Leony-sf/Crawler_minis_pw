from __future__ import annotations

from pathlib import Path
from typing import Any
import os
import re
from urllib.parse import urlsplit, parse_qsl, urlencode, urlunsplit
from datetime import datetime
import json
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

from base_anatel import analisar_situacao_anatel
from extracao_shopee import analisar_dimensoes_produto, extrair_dados_html, classificar_produto
from utils import (
    construir_url_busca, criar_pastas_saida, encurtar_texto, linha, limpar_url,
    log, log_aviso, log_debug, log_erro, log_ok, normalizar_texto,
    pasta_print_por_status, salvar_parquet_incremental, secao, bloco, metadados_captura, gerar_id
)

RAIZ_PROJETO = Path(__file__).resolve().parent.parent
PERFIL_CHROME_SHOPEE = RAIZ_PROJETO / "perfil_chrome_shopee"
LOGIN_SHOPEE_URL = "https://shopee.com.br/buyer/login?next=https%3A%2F%2Fshopee.com.br"
SALVAR_SESSAO_DEBUG_ENV = "SHOPEE_SALVAR_SESSAO_DEBUG"

LINK_PRODUTO_SELECTORS = [
    "a[href*='-i.']",
    "a[href*='/product/']",
    "a[data-sqe='link'][href]",
    "a[href*='shopee.com.br'][href]",
]

# ==============================================================================
# FUNÇÕES DE AUDITORIA VISUAL DO TERMINAL (Padrão Mercado Livre)
# ==============================================================================

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

def _dimensoes_terminal(analise: dict[str, Any]) -> str:
    if analise.get("dimensoes_confiaveis") != "SIM": return "NÃO LOCALIZADAS"
    valores = [
        _formatar_numero_cm(analise.get("altura_cm")),
        _formatar_numero_cm(analise.get("largura_cm")),
        _formatar_numero_cm(analise.get("espessura_cm")),
    ]
    valores = [v for v in valores if v]
    return " x ".join(valores) + " cm" if valores else "NÃO LOCALIZADAS"

def _log_auditoria_dimensoes(analise: dict[str, Any]) -> None:
    produto = _dimensoes_terminal(analise)
    resultado = str(analise.get("dentro_limite_dimensional") or "NAO_VERIFICADO").upper()
    
    if resultado == "SIM": situacao = "DENTRO DO LIMITE"
    elif resultado == "NAO": situacao = "ACIMA DO LIMITE"
    else: situacao = "NÃO FOI POSSÍVEL VERIFICAR"

    log("dimensões", "Limite adotado : 12,0 x 5,5 cm")
    log("dimensões", f"Produto        : {produto}")
    log("dimensões", "Origem         : " + _valor_terminal(analise.get("origem_dimensoes"), "não localizada"))
    log("dimensões", f"Resultado      : {situacao}")

def _log_auditoria_anatel(dados: dict[str, Any], anatel: dict[str, Any]) -> None:
    log("anatel", "Código         : anúncio=" + _valor_terminal(dados.get("codigo_anatel_principal")) + " | base=" + _valor_terminal(anatel.get("codigo_base")) + " | confere=" + _sim_nao_terminal(anatel.get("codigo_confere_base")))
    log("anatel", "Situação Req.  : " + _valor_terminal(anatel.get("situacao_requerimento_base"), "NÃO LOCALIZADA") + " | emitida=" + _sim_nao_terminal(anatel.get("requerimento_emitido")))
    log("anatel", "Marca          : anúncio=" + _valor_terminal(dados.get("marca")) + " | base=" + _valor_terminal(anatel.get("fabricante_base")) + " | confere=" + _sim_nao_terminal(anatel.get("marca_confere_base")))
    log("anatel", "Modelo         : anúncio=" + _valor_terminal(dados.get("modelo")) + " | base=" + _valor_terminal(anatel.get("modelo_base")) + " | confere=" + _sim_nao_terminal(anatel.get("modelo_confere_base")))
    log("anatel", "Resultado      : " + _valor_terminal(anatel.get("situacao_anatel"), "NAO_INFORMADO") + " — " + _valor_terminal(anatel.get("motivo_anatel"), "sem motivo"))

def _log_auditoria_classificacao(cls: dict[str, Any]) -> None:
    log("classificação", "Destino        : " + _valor_terminal(cls.get("classificacao"), "NÃO DEFINIDO"))
    log("classificação", "Motivo         : " + _valor_terminal(cls.get("motivo_classificacao"), "sem motivo registrado"))

# ==============================================================================
# NAVEGAÇÃO E EXTRAÇÃO
# ==============================================================================

def _pausa(page, segundos: float, motivo: str = "") -> None:
    if motivo: log_debug("pausa", f"{segundos:.1f}s - {motivo}")
    page.wait_for_timeout(int(segundos * 1000))

def _abrir_contexto_chrome_persistente(p, headless: bool = False):
    headless_efetivo = False
    try:
        return p.chromium.launch_persistent_context(
            user_data_dir=str(PERFIL_CHROME_SHOPEE), channel="chrome", headless=headless_efetivo,
            no_viewport=True, locale="pt-BR", args=["--start-maximized", "--disable-blink-features=AutomationControlled"]
        )
    except Exception:
        return p.chromium.launch_persistent_context(
            user_data_dir=str(PERFIL_CHROME_SHOPEE), headless=headless_efetivo,
            no_viewport=True, locale="pt-BR", args=["--start-maximized", "--disable-blink-features=AutomationControlled"]
        )

def _fechar_popups_se_existir(page) -> None:
    try:
        texto_norm = normalizar_texto(page.locator("body").inner_text(timeout=3000))
    except Exception: texto_norm = ""
    if "cookies" in texto_norm or "usamos cookies" in texto_norm:
        for t in ["Aceitar todos os cookies", "Aceitar todos", "Aceitar"]:
            try:
                b = page.get_by_text(t, exact=False).first
                if b.count() > 0 and b.is_visible(timeout=1500):
                    b.click(timeout=2500, force=True); page.wait_for_timeout(700); return
            except Exception: pass
    for sel in ["button[aria-label='Close']", "button[aria-label='Fechar']", ".shopee-popup__close-btn", ".shopee-modal__close"]:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0 and loc.is_visible(timeout=1500):
                loc.click(timeout=2500, force=True); page.wait_for_timeout(700); return
        except Exception: pass

def _selecionar_idioma_portugues_se_aparecer(page) -> None:
    try:
        if "selecione seu idioma" not in normalizar_texto(page.locator("body").inner_text(timeout=3000)): return
    except Exception: return
    for t in ["Português (BR)", "Portugues (BR)", "Português", "Portugues"]:
        try:
            loc = page.get_by_text(t, exact=True).first
            if loc.count() > 0 and loc.is_visible(timeout=2000):
                loc.click(timeout=4000, force=True); page.wait_for_timeout(1500); return
        except Exception: pass

def _esta_logado_shopee(page) -> bool:
    try:
        txt = normalizar_texto(page.locator("body").inner_text(timeout=5000))
        return any(s in txt for s in ["minha conta", "meus pedidos", "notificacoes", "notificações", "sair", "minhas compras"])
    except Exception: return False

def _precisa_intervencao_manual(page) -> bool:
    try:
        url_atual = (page.url or "").lower()
        txt = normalizar_texto(page.locator("body").inner_text(timeout=4000))
        sinais = ["captcha", "verificacao", "verificação", "nao sou um robo", "não sou um robô", "atividade suspeita", "sms", "selecione seu idioma"]
        return "captcha" in url_atual or "verify" in url_atual or "buyer/login" in url_atual or any(s in txt for s in sinais)
    except Exception: return False

def _salvar_estado_sessao_debug(page) -> None:
    if os.getenv(SALVAR_SESSAO_DEBUG_ENV, "").strip().lower() not in {"1", "true", "sim", "yes"}: return
    try: page.context.storage_state(path=str(RAIZ_PROJETO / "shopee_state_debug.json"))
    except Exception: pass

def _pausar_intervencao_manual(page, etapa: str = "") -> None:
    print("\n" + "=" * 70 + "\nINTERVENÇÃO MANUAL NECESSÁRIA\n" + "=" * 70)
    input("Resolva na janela aberta e pressione ENTER para continuar... ")
    _salvar_estado_sessao_debug(page)

def _garantir_sessao_shopee(page, url_busca: str, login_manual: bool = False) -> None:
    _selecionar_idioma_portugues_se_aparecer(page)
    _fechar_popups_se_existir(page)
    if login_manual and not _esta_logado_shopee(page):
        try:
            page.goto(LOGIN_SHOPEE_URL, wait_until="domcontentloaded", timeout=60000); page.wait_for_timeout(4000)
        except Exception: pass
        _pausar_intervencao_manual(page, etapa="no login manual")
    elif _precisa_intervencao_manual(page):
        _pausar_intervencao_manual(page, etapa="na página atual")
    try:
        page.goto(url_busca, wait_until="domcontentloaded", timeout=60000); page.wait_for_timeout(4000)
        _selecionar_idioma_portugues_se_aparecer(page); _fechar_popups_se_existir(page)
    except Exception: pass

def _rolar_para_carregar(page, vezes: int = 3, pausa_ms: int = 1200) -> None:
    for _ in range(vezes):
        page.mouse.wheel(0, 1200); page.wait_for_timeout(pausa_ms)

def _clicar_ver_mais_se_existir(page) -> None:
    for t in ["Ver mais", "Mostrar mais", "Ler mais", "Ver tudo", "Ver Tudo"]:
        try:
            b = page.get_by_text(t, exact=True).first
            if b.count() > 0 and b.is_visible(timeout=1500):
                b.click(timeout=2000, force=True); page.wait_for_timeout(800); return
        except Exception: pass

def _rolar_para_detalhes_produto(page) -> str:
    for t in ["Detalhes do produto", "Especificações do produto", "Informações do produto", "Descrição do produto", "Marca", "Modelo", "ANATEL"]:
        try:
            loc = page.get_by_text(t, exact=False).first
            if loc.count() > 0 and loc.is_visible(timeout=2000):
                loc.scroll_into_view_if_needed(timeout=3500); page.wait_for_timeout(1200)
                _clicar_ver_mais_se_existir(page); break
        except Exception: pass
    ultimo_texto = ""
    for _ in range(1, 12):
        try:
            ultimo_texto = page.locator("body").inner_text(timeout=6000)
            txt = normalizar_texto(ultimo_texto)
            if any(x in txt for x in ["detalhes do produto", "especificacoes do produto", "descricao do produto", "anatel", "homologacao"]):
                _clicar_ver_mais_se_existir(page); return ultimo_texto
        except Exception: pass
        page.mouse.wheel(0, 900); page.wait_for_timeout(900); _clicar_ver_mais_se_existir(page)
    return ultimo_texto

def _texto_card_do_link(link_locator) -> str:
    try:
        return link_locator.evaluate("el => { const c = el.closest(\"[data-sqe='item']\") || el.closest(\"li\"); return c ? c.innerText : el.innerText; }") or ""
    except Exception: return ""

def _coletar_links_produtos(page, limite: int) -> list[str]:
    links = []
    for sel in LINK_PRODUTO_SELECTORS:
        try:
            loc = page.locator(sel)
            for i in range(loc.count()):
                h = limpar_url(loc.nth(i).get_attribute("href") or "")
                if "-i." in h or "/product/" in h:
                    if h not in links: links.append(h)
                if len(links) >= limite: return links
        except Exception: pass
    return links[:limite]

def _salvar_print(page, pasta_saida: Path, idx: int, status: str) -> str:
    if status == "DESCARTADO": return ""
    pasta = pasta_print_por_status(pasta_saida, status)
    p = pasta / f"produto_{idx:03d}.png"
    try: page.screenshot(path=str(p), full_page=True); return str(p)
    except Exception: return ""

def _extrair_total_comentarios_do_texto(texto: str) -> int:
    for p in [r"com\s+comentários\s*\((\d[\d\.]*)\)", r"(\d[\d\.]*)\s+avaliações"]:
        m = re.search(p, normalizar_texto(texto))
        if m:
            try: return int(m.group(1).replace(".", ""))
            except Exception: pass
    return 0

def _rolar_para_avaliacoes_produto(page) -> None:
    for _ in range(7): page.mouse.wheel(0, 1200); page.wait_for_timeout(700)

def _extrair_comentarios_por_js(page) -> list[str]:
    try:
        t = page.evaluate("() => { const r = Array.from(document.querySelectorAll('.shopee-product-rating')).map(c => c.innerText.trim()); return r; }")
        if isinstance(t, list): return [str(x) for x in t if str(x).strip()]
    except Exception: pass
    return []

def _capturar_comentarios_produto(page, idx: int, link: str, titulo: str, limite: int = 10) -> list[dict[str, Any]]:
    comentarios = []
    try:
        _rolar_para_avaliacoes_produto(page)
        for _ in range(3):
            for c in _extrair_comentarios_por_js(page):
                if c and c not in comentarios: comentarios.append(c)
            if len(comentarios) >= limite: break
            page.mouse.wheel(0, 1600); page.wait_for_timeout(1500)
            
        txt_body = page.locator("body").inner_text(timeout=6000)
        tot = _extrair_total_comentarios_do_texto(txt_body)
        
        l = []
        for pos, c in enumerate(comentarios[:limite], start=1):
            l.append({
                "pid": gerar_id(link), "marketplace_id": "Shopee", "url": link, "link": link, "titulo": titulo,
                "comentario_ordem": pos, "comentario": c, "comment": c, "comentarios_total_detectado": tot
            })
        return l
    except Exception: return []

def _clicar_proxima_pagina_busca(page) -> bool:
    for sel in [".shopee-icon-button--right"]:
        try:
            b = page.locator(sel).last
            if b.is_visible(timeout=1000) and not b.get_attribute("disabled"):
                b.click(timeout=5000, force=True); page.wait_for_timeout(4000); return True
        except Exception: pass
    return False

# ==============================================================================
# FUNÇÃO PRINCIPAL REESCRITA COM A LÓGICA E O LOG DE AUDITORIA DO ML
# ==============================================================================
def rodar_playwright_shopee(query: str, limite: int, base_anatel=None, headless: bool = False, max_paginas: int = 3, queries: list[str] = None) -> dict[str, Any]:
    pasta_saida = criar_pastas_saida()
    produtos_resultados = []
    comentarios_resultados = []

    queries_execucao = queries if queries else [query]
    urls_processadas = set()
    
    total_visitados = 0
    total_descartados = 0
    total_irregulares = 0
    total_suspeitos = 0

    secao("Busca Shopee")

    with sync_playwright() as p:
        context = _abrir_contexto_chrome_persistente(p, headless=headless)
        page = context.pages[0] if context.pages else context.new_page()

        try:
            for termo_busca in queries_execucao:
                if total_visitados >= limite: break
                url_busca = construir_url_busca(termo_busca)

                for pagina_atual in range(1, max_paginas + 1):
                    if total_visitados >= limite: break

                    if pagina_atual == 1:
                        page.goto(url_busca, timeout=60000); _pausa(page, 6)
                    else:
                        if not _clicar_proxima_pagina_busca(page): break
                    
                    _garantir_sessao_shopee(page, page.url)
                    _rolar_para_carregar(page, vezes=6, pausa_ms=1300)

                    restante = max(limite - total_visitados, 0)
                    links = _coletar_links_produtos(page, limite=restante)
                    links_novos = [l for l in links if l not in urls_processadas]

                    if not links_novos: break

                    for link in links_novos:
                        if total_visitados >= limite: break
                        urls_processadas.add(link)
                        total_visitados += 1
                        idx = total_visitados

                        bloco(f"Produto {idx}/{limite}")
                        log("produto", link)

                        produto_page = context.new_page()
                        try:
                            produto_page.goto(link, timeout=60000)
                            _pausa(produto_page, 4)
                            _fechar_popups_se_existir(produto_page)

                            texto_visivel = _rolar_para_detalhes_produto(produto_page)
                            html = produto_page.content()

                            dados = extrair_dados_html(html, url=link, texto_extra=texto_visivel)
                            momento = datetime.now()

                            # --- CADEIA DE AUDITORIA VISUAL DO ML ---
                            dim = analisar_dimensoes_produto(dados)
                            _log_auditoria_dimensoes(dim)

                            anatel = analisar_situacao_anatel(
                                dados.get("codigo_anatel_principal", ""), dados.get("marca", ""), dados.get("modelo", ""), base_anatel
                            )
                            _log_auditoria_anatel(dados, anatel)

                            cls = classificar_produto(dados, dim, anatel)
                            _log_auditoria_classificacao(cls)
                            
                            status_final = cls["classificacao"]
                            
                            # Se descartado, PULA o salvamento de prints e parquet, igual ao ML!
                            if status_final == "DESCARTADO":
                                total_descartados += 1
                                continue
                                
                            if status_final == "IRREGULAR": total_irregulares += 1
                            if status_final == "SUSPEITO": total_suspeitos += 1
                            
                            comentarios_extraidos = _capturar_comentarios_produto(produto_page, idx, link, dados.get("titulo", ""))
                            log("comentários", f"Capturados: {len(comentarios_extraidos)}")

                            # Prepara linha Parquet
                            linha_prod = {
                                "pid": gerar_id(link), "marketplace_id": "Shopee",
                                "titulo": dados.get("titulo", ""), "link": link, "url": link,
                                "codigo_anatel": anatel.get("codigo_anatel_normalizado", ""),
                                "codigo_anatel_principal": dados.get("codigo_anatel_principal", ""),
                                "marca": dados.get("marca", ""), "preco": dados.get("preco", ""),
                                "status": "Irregular" if status_final == "IRREGULAR" else "Suspeito",
                                "status_validacao": status_final,
                                "motivo_validacao": cls["motivo_classificacao"],
                                "classificacao": status_final,
                                "dimensoes_encontradas": _dimensoes_terminal(dim),
                                "codigo_confere_base": anatel.get("codigo_confere_base", ""),
                                "motivo_anatel": anatel.get("motivo_anatel", ""),
                            }
                            linha_prod.update(metadados_captura(pasta_saida, momento))
                            
                            # Tira print do que não foi descartado
                            linha_prod["print_path"] = _salvar_print(produto_page, pasta_saida, idx, status_final)
                            
                            produtos_resultados.append(linha_prod)
                            comentarios_resultados.extend(comentarios_extraidos)
                            
                            salvar_parquet_incremental(pasta_saida, produtos_resultados, comentarios_resultados)

                        except Exception as exc:
                            log("erro", f"Erro no produto {idx}: {exc}")
                        finally:
                            produto_page.close()

        finally:
            context.close()

    resumo = {
        "pasta_saida": str(pasta_saida),
        "total_visitados": total_visitados,
        "total_irregulares": total_irregulares,
        "total_suspeitos": total_suspeitos,
        "total_descartados": total_descartados,
        "total_produtos_no_parquet": len(produtos_resultados)
    }
    
    secao("Resumo Final")
    for k, v in resumo.items(): log("resumo", f"{k}: {v}")
    
    return resumo