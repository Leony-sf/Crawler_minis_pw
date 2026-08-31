# -*- coding: utf-8 -*-
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd
from playwright.async_api import async_playwright, BrowserContext, Page, TimeoutError as PlaywrightTimeoutError

from classificacao_americanas import classificar_produto
from extracao_americanas import coletar_links_resultados, esperar_carregamento, extrair_produto, fechar_popups_basicos
from utils_americanas import agora_iso, carregar_termos_busca, montar_url_busca, slugify, escrever_resumo_txt, log, secao, bloco

try:
    from base_anatel import analisar_situacao_anatel
except ImportError:
    analisar_situacao_anatel = lambda *args: {}

@dataclass
class ConfigAmericanas:
    txt: str = "buscar_americanas.txt"
    saida: Path = Path("saidas_americanas")
    limit: int = 100
    max_paginas: int = 2
    headless: bool = False
    slow_mo: int = 0
    timeout_ms: int = 30000
    salvar_descartados: bool = False
    pausar_inicio: bool = False
    base_anatel: Any = None

def _valor_terminal(valor: Any, vazio: str = "NÃO LOCALIZADO") -> str:
    texto = str(valor or "").strip()
    return texto if texto else vazio

def _sim_nao_terminal(valor: Any) -> str:
    texto = str(valor or "").strip().upper()
    if texto == "SIM": return "SIM"
    if texto == "NAO_VERIFICADO": return "NÃO VERIFICADO"
    return "NÃO"

def _log_auditoria_dimensoes(produto: dict, classificacao: Any) -> None:
    altura = produto.get("altura_mm")
    largura = produto.get("largura_mm")
    maior_dim = produto.get("maior_dimensao_mm")

    if altura and largura:
        medidas_str = f"{altura/10:.1f} x {largura/10:.1f} cm"
    elif maior_dim:
        medidas_str = f"Maior dimensão {maior_dim/10:.1f} cm"
    else:
        medidas_str = "NÃO LOCALIZADAS"

    resultado = "DENTRO DO LIMITE" if classificacao.status != "DESCARTADO" else "ACIMA DO LIMITE"
    if not maior_dim: resultado = "NÃO FOI POSSÍVEL VERIFICAR"

    log("DIMENSÕES", "Limite adotado : 12,0 x 5,5 cm")
    log("DIMENSÕES", f"Produto        : {medidas_str}")
    log("DIMENSÕES", "Origem         : tabela de atributos / texto")
    log("DIMENSÕES", f"Resultado      : {resultado}")

def _log_auditoria_anatel(produto: dict, anatel: dict) -> None:
    log("ANATEL", "Código         : anúncio=" + _valor_terminal(produto.get("codigo_anatel")) + " | base=" + _valor_terminal(anatel.get("codigo_base")) + " | confere=" + _sim_nao_terminal(anatel.get("codigo_confere_base")))
    log("ANATEL", "Situação Req.  : " + _valor_terminal(anatel.get("situacao_requerimento_base"), "NÃO LOCALIZADA") + " | emitida=" + _sim_nao_terminal(anatel.get("requerimento_emitido")))
    log("ANATEL", "Marca          : anúncio=" + _valor_terminal(produto.get("marca")) + " | base=" + _valor_terminal(anatel.get("fabricante_base")) + " | confere=" + _sim_nao_terminal(anatel.get("marca_confere_base")))
    log("ANATEL", "Modelo         : anúncio=" + _valor_terminal(produto.get("modelo")) + " | base=" + _valor_terminal(anatel.get("modelo_base")) + " | confere=" + _sim_nao_terminal(anatel.get("modelo_confere_base")))
    log("ANATEL", "Resultado      : " + _valor_terminal(anatel.get("situacao_anatel"), "NAO_INFORMADO") + " — " + _valor_terminal(anatel.get("motivo_anatel"), "sem motivo"))


async def executar_crawler_americanas(config: ConfigAmericanas) -> List[Dict[str, Any]]:
    termos = carregar_termos_busca(config.txt)
    resultados: List[Dict[str, Any]] = []
    comentarios_lista: List[Dict[str, Any]] = []
    visitados: set[str] = set()
    total_cards = total_descartados = total_erros = total_analisados = 0

    async with async_playwright() as p:
        contexto = await _criar_contexto(p, config)
        page = await _obter_pagina_principal(contexto)
        page.set_default_timeout(config.timeout_ms)

        if config.pausar_inicio:
            await page.goto("https://www.americanas.com.br", timeout=config.timeout_ms)
            input("Resolva CEP/captcha no navegador e pressione ENTER para iniciar...")

        for pagina in range(1, config.max_paginas + 1):
            if total_analisados >= config.limit: break
            for idx_termo, termo in enumerate(termos, start=1):
                if total_analisados >= config.limit: break
                
                secao(f"BUSCA: {termo.upper()}")

                cards = await _abrir_busca_e_coletar(page, config, termo, pagina)
                total_cards += len(cards)

                for indice, card in enumerate(cards, start=1):
                    if total_analisados >= config.limit: break
                    url_produto = card.get("url", "")
                    if not url_produto or url_produto in visitados: continue
                    visitados.add(url_produto)

                    total_analisados += 1
                    
                    bloco(f"PRODUTO {indice}/{len(cards)}")
                    log("PRODUTO", url_produto)
                    
                    registro, comentarios = await _processar_produto(
                        contexto, url_produto, card, config
                    )
                    
                    if not registro:
                        total_erros += 1
                        continue

                    if registro.get("status") == "DESCARTADO":
                        total_descartados += 1
                        if not config.salvar_descartados: continue

                    resultados.append(registro)
                    if comentarios:
                        for c in comentarios:
                            comentarios_lista.append({
                                "url": url_produto, "titulo": registro.get("titulo"), "comentario": c, "status": registro.get("status")
                            })
                    _salvar_parquets_incrementais(resultados, comentarios_lista, config.saida)
        await contexto.close()

    _salvar_parquets_incrementais(resultados, comentarios_lista, config.saida)
    return resultados

async def _abrir_busca_e_coletar(page: Page, config: ConfigAmericanas, termo: str, pagina: int) -> List[Dict[str, Any]]:
    for modo in ["s", "busca"]:
        try:
            url_busca = montar_url_busca(termo, pagina, modo=modo)
            await page.goto(url_busca, wait_until="domcontentloaded", timeout=config.timeout_ms)
            await esperar_carregamento(page, timeout_ms=config.timeout_ms)
            await fechar_popups_basicos(page)
            cards = await coletar_links_resultados(page)
            if cards: return cards
        except Exception:
            pass
    return []

async def _obter_pagina_principal(contexto: BrowserContext) -> Page:
    return contexto.pages[0] if contexto.pages else await contexto.new_page()

async def _criar_contexto(p: Any, config: ConfigAmericanas) -> BrowserContext:
    perfil = Path("perfil_americanas").resolve()
    return await p.chromium.launch_persistent_context(
        user_data_dir=str(perfil), headless=config.headless, slow_mo=config.slow_mo,
        viewport={"width": 1366, "height": 900}, locale="pt-BR"
    )

async def _processar_produto(contexto: BrowserContext, url_produto: str, card: Dict[str, Any], config: ConfigAmericanas) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    page: Optional[Page] = None
    try:
        page = await contexto.new_page()
        page.set_default_timeout(config.timeout_ms)
        await page.goto(url_produto, wait_until="domcontentloaded", timeout=config.timeout_ms)
        produto = await extrair_produto(page, url_produto, card)
        
        comentarios_ext = produto.get("comentarios", [])
        log("COMENTÁRIOS", f"Capturados: {len(comentarios_ext)}")

        anatel = analisar_situacao_anatel(
            produto.get("codigo_anatel", ""),
            produto.get("marca", ""),
            produto.get("modelo", ""),
            config.base_anatel
        )
        classificacao = classificar_produto(produto, anatel)

        _log_auditoria_dimensoes(produto, classificacao)
        _log_auditoria_anatel(produto, anatel)

        registro: Dict[str, Any] = {
            "data_coleta": agora_iso(), "marketplace": "Americanas", "url": url_produto,
            "status": classificacao.status, "titulo": produto.get("titulo", ""),
            "preco": produto.get("preco", ""), "fornecedor": produto.get("fabricante", ""),
            **classificacao.as_dict(), "codigo_anatel_principal": produto.get("codigo_anatel", ""),
            "detalhes": produto.get("detalhes", "")[:6000], "print_comprovante": "",
        }
        
        log("CLASSIFICAÇÃO", f"Destino        : {classificacao.status}")
        motivos_str = "; ".join(classificacao.motivos) if classificacao.motivos else "sem motivo"
        log("CLASSIFICAÇÃO", f"Motivo         : {motivos_str}")

        if classificacao.status in ["IRREGULAR", "SUSPEITO"]:
            cat = "irregulares" if classificacao.status == "IRREGULAR" else "suspeitos"
            registro["print_comprovante"] = await _tirar_print_produto(page, config.saida, registro, cat)

        return registro, comentarios_ext
    except Exception as exc:
        log("ERRO", f"Falha ao processar anúncio: {str(exc)[:110]}", nivel="ERRO")
        return None, []
    finally:
        if page:
            try: await page.close()
            except Exception: pass

async def _tirar_print_produto(page: Page, saida: Path, registro: Dict[str, Any], categoria: str) -> str:
    pasta = saida / "prints" / categoria
    titulo = slugify(registro.get("titulo") or "produto", max_len=70)
    caminho = pasta / f"{hash(registro.get('url', '')) % 100000}_{titulo}.png"
    try:
        await page.screenshot(path=str(caminho), full_page=True)
        return str(caminho)
    except Exception:
        return ""

def _salvar_parquets_incrementais(resultados: List[Dict[str, Any]], comentarios: List[Dict[str, Any]], saida: Path) -> None:
    if resultados: pd.DataFrame(resultados).to_parquet(saida / "products.parquet", index=False)
    if comentarios: pd.DataFrame(comentarios).to_parquet(saida / "comentarios.parquet", index=False)