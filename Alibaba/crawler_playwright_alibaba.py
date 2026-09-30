# -*- coding: utf-8 -*-
"""Crawler Alibaba.com com Playwright e Inteligência ML."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import json
import re

import pandas as pd
from playwright.async_api import async_playwright, BrowserContext, Page, TimeoutError as PlaywrightTimeoutError

from classificacao_alibaba import classificar_produto, analisar_dimensoes_produto
from base_anatel_alibaba import analisar_situacao_anatel
from extracao_alibaba import coletar_links_resultados, esperar_carregamento, extrair_produto, fechar_popups_basicos
from utils_alibaba import (
    ler_termos_txt, montar_url_busca, criar_pastas_saida_alibaba, 
    gerar_id, metadados_captura, salvar_parquet_incremental, arquivo_seguro,
    secao, bloco, log
)

@dataclass
class ConfigAlibaba:
    txt: str = "buscar_alibaba.txt"
    saida: Path | str | None = None
    limit: int = 100
    max_paginas: int = 2
    headless: bool = False
    slow_mo: int = 0
    timeout_ms: int = 30000
    salvar_descartados: bool = False
    limpar_prints: bool = False
    pausar_inicio: bool = False
    base_anatel: Any = None

def _modelo_decisivo(dados: dict[str, Any]) -> tuple[str, str]:
    prioridades = [
        ("modelo_alfanumerico", "Modelo alfanumérico"),
        ("modelo_detalhado", "Modelo detalhado"),
        ("numero_modelo", "Número do modelo"),
        ("modelo", "Modelo"),
    ]
    for campo, rotulo in prioridades:
        valor = str(dados.get(campo) or "").strip()
        if valor: return rotulo, valor
    return "", ""

def _valor_terminal(valor: Any, vazio: str = "NÃO LOCALIZADO") -> str:
    texto = str(valor or "").strip()
    return texto if texto else vazio

def _sim_nao_terminal(valor: Any) -> str:
    texto = str(valor or "").strip().upper()
    return "SIM" if texto == "SIM" else "NÃO VERIFICADO" if texto == "NAO_VERIFICADO" else "NÃO"

def _formatar_numero_cm(valor: Any) -> str:
    if valor in (None, ""): return ""
    try: return f"{float(valor):.2f}".rstrip("0").rstrip(".").replace(".", ",")
    except (TypeError, ValueError): return str(valor)

def _dimensoes_terminal(analise: dict[str, Any]) -> str:
    if analise.get("dimensoes_confiaveis") != "SIM": return "NÃO LOCALIZADAS"
    valores = [_formatar_numero_cm(analise.get(c)) for c in ["altura_cm", "largura_cm", "espessura_cm"]]
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

def _log_auditoria_anatel(dados: dict[str, Any], anatel: dict[str, Any], modelo_label: str, modelo_anuncio: str) -> None:
    log("anatel", "Código         : anúncio=" + _valor_terminal(dados.get("codigo_anatel_principal")) + " | base=" + _valor_terminal(anatel.get("codigo_base")) + " | confere=" + _sim_nao_terminal(anatel.get("codigo_confere_base")))
    log("anatel", "Situação Req.  : " + _valor_terminal(anatel.get("situacao_requerimento_base"), "NÃO LOCALIZADA") + " | emitida=" + _sim_nao_terminal(anatel.get("requerimento_emitido")))
    log("anatel", "Marca          : anúncio=" + _valor_terminal(dados.get("marca")) + " | base=" + _valor_terminal(anatel.get("fabricante_base")) + " | confere=" + _sim_nao_terminal(anatel.get("marca_confere_base")))
    log("anatel", "Modelo Técnico : anúncio=" + _valor_terminal(modelo_anuncio) + f" ({modelo_label or 'campo não identificado'})" + " | base=" + _valor_terminal(anatel.get("modelo_base")) + " | confere=" + _sim_nao_terminal(anatel.get("modelo_confere_base")))
    log("anatel", "Nome Comercial : anúncio=" + _valor_terminal(dados.get("nome_comercial")) + " | base=" + _valor_terminal(anatel.get("nome_comercial_base")) + " | confere=" + _sim_nao_terminal(anatel.get("nome_comercial_confere_base")))
    log("anatel", "Resultado      : " + _valor_terminal(anatel.get("situacao_anatel"), "NÃO VERIFICADO") + " — " + _valor_terminal(anatel.get("motivo_anatel"), "sem motivo"))

def _log_auditoria_classificacao(classificacao: dict[str, Any]) -> None:
    log("classificação", "Destino        : " + _valor_terminal(classificacao.get("classificacao"), "NÃO DEFINIDO"))
    log("classificação", "Motivo         : " + _valor_terminal(classificacao.get("motivo_classificacao"), "sem motivo registrado"))

def _formatar_dimensoes_encontradas(classificacao: dict[str, Any]) -> str:
    if classificacao.get("dimensoes_confiaveis") != "SIM": return "NAO ENCONTRADAS"
    valores = []
    for campo in ["altura_cm", "largura_cm", "espessura_cm"]:
        valor = classificacao.get(campo)
        if valor in (None, ""): continue
        try: valores.append(f"{float(valor):.2f}".rstrip("0").rstrip(".").replace(".", ","))
        except (TypeError, ValueError): continue
    return " x ".join(valores) + " cm" if len(valores) >= 2 else "ENCONTRADAS, MAS INCOMPLETAS"

async def executar_crawler_alibaba(config: ConfigAlibaba) -> dict[str, Any]:
    termos = ler_termos_txt(config.txt)
    pasta_saida = criar_pastas_saida_alibaba(config.saida)
    
    log("arquivos", f"Pasta desta execução: {pasta_saida}")

    produtos: List[Dict[str, Any]] = []
    visitados: set[str] = set()
    total_visitados = 0
    total_descartados = 0

    salvar_parquet_incremental(pasta_saida, produtos, [])

    secao("Alibaba.com — crawler com regras ML")

    async with async_playwright() as p:
        contexto = await _criar_contexto(p, config)
        page = await _obter_pagina_principal(contexto)
        page.set_default_timeout(config.timeout_ms)
        page.set_default_navigation_timeout(config.timeout_ms + 15000)

        try:
            url_inicial = montar_url_busca(termos[0], 1)
            await page.goto(url_inicial, wait_until="domcontentloaded", timeout=config.timeout_ms)
            await esperar_carregamento(page, timeout_ms=config.timeout_ms)
            await fechar_popups_basicos(page)

            if config.pausar_inicio:
                secao("Pausa manual")
                print("Resolva login ou captcha no Chrome e deixe a listagem aberta.")
                input("Pressione ENTER para iniciar a coleta... ")

            for idx_termo, termo in enumerate(termos, start=1):
                if len(produtos) >= config.limit: break
                
                secao(f"Busca {idx_termo}/{len(termos)} — {termo}")
                if idx_termo > 1:
                    url_busca = montar_url_busca(termo, 1)
                    await page.goto(url_busca, wait_until="domcontentloaded", timeout=config.timeout_ms)
                    await esperar_carregamento(page, timeout_ms=config.timeout_ms)
                    await fechar_popups_basicos(page)

                for pagina in range(1, config.max_paginas + 1):
                    if len(produtos) >= config.limit: break
                    
                    if pagina > 1:
                        url_busca = montar_url_busca(termo, pagina)
                        await page.goto(url_busca, wait_until="domcontentloaded", timeout=config.timeout_ms)
                        await esperar_carregamento(page, timeout_ms=config.timeout_ms)
                        await fechar_popups_basicos(page)
                    
                    bloco(f"Página {pagina}")
                    
                    links_candidatos = await coletar_links_resultados(page)
                    log("listagem", f"Links candidatos: {len(links_candidatos)}")

                    if not links_candidatos:
                        await _salvar_print_debug(page, pasta_saida, termo, pagina)
                        continue

                    for indice, url_produto in enumerate(links_candidatos, start=1):
                        if len(produtos) >= config.limit: break
                        if not url_produto or url_produto in visitados: continue
                        
                        visitados.add(url_produto)
                        total_visitados += 1

                        bloco(f"Produto {indice}/{len(links_candidatos)}")
                        log("produto", url_produto)

                        registro = await _processar_produto(
                            contexto, url_produto, config, termo, pasta_saida
                        )
                        
                        if not registro:
                            continue

                        if registro.get("classificacao") == "DESCARTADO":
                            total_descartados += 1
                            if not config.salvar_descartados: continue

                        produtos.append(registro)
                        salvar_parquet_incremental(pasta_saida, produtos, [])
                        
        finally:
            salvar_parquet_incremental(pasta_saida, produtos, [])
            log("chrome", "Execução finalizada; contexto encerrado.")
            await contexto.close()

    resumo = {
        "pasta_saida": str(pasta_saida),
        "total_visitados": total_visitados,
        "total_irregulares": sum(1 for item in produtos if item.get("classificacao") == "IRREGULAR"),
        "total_suspeitos": sum(1 for item in produtos if item.get("classificacao") == "SUSPEITO"),
        "total_nao_classificados": sum(1 for item in produtos if item.get("classificacao") == "NÃO CLASSIFICADO"),
        "total_descartados": total_descartados,
        "total_produtos_no_parquet": len(produtos),
        "total_comentarios": 0,
        "criterio_dimensional": "120 x 55 mm",
        "data_hora_finalizacao": datetime.now().astimezone().strftime("%d/%m/%Y %H:%M:%S"),
    }
    
    secao("Resumo")
    for chave, valor in resumo.items():
        log("resumo", f"{chave}: {valor}")

    return resumo

async def _criar_contexto(p: Any, config: ConfigAlibaba) -> BrowserContext:
    perfil = Path("perfil_alibaba").resolve()
    perfil.mkdir(parents=True, exist_ok=True)
    return await p.chromium.launch_persistent_context(
        user_data_dir=str(perfil), headless=config.headless, slow_mo=config.slow_mo,
        viewport={"width": 1366, "height": 900}, locale="en-US",
        args=["--disable-blink-features=AutomationControlled", "--start-maximized"],
    )

async def _obter_pagina_principal(contexto: BrowserContext) -> Page:
    if contexto.pages:
        page = contexto.pages[0]
        for extra in contexto.pages[1:]:
            try:
                if extra.url == "about:blank": await extra.close()
            except Exception: pass
        return page
    return await contexto.new_page()

async def _processar_produto(
    contexto: BrowserContext, url_produto: str, config: ConfigAlibaba, 
    termo: str, pasta_saida: Path
) -> Optional[Dict[str, Any]]:
    page: Optional[Page] = None
    try:
        page = await contexto.new_page()
        page.set_default_timeout(config.timeout_ms)
        await page.goto(url_produto, wait_until="domcontentloaded", timeout=config.timeout_ms)
        
        produto = await extrair_produto(page, url_produto)
        momento = datetime.now().astimezone()

        analise_dim = analisar_dimensoes_produto(produto)
        _log_auditoria_dimensoes(analise_dim)

        modelo_label, modelo_anatel = _modelo_decisivo(produto)
        analise_anatel = analisar_situacao_anatel(
            codigo=produto.get("codigo_anatel_principal", ""),
            marca=produto.get("marca", ""),
            modelo=modelo_anatel,
            nome_comercial=produto.get("nome_comercial", ""), # Inclusão do Nome Comercial
            base=config.base_anatel
        )
        _log_auditoria_anatel(produto, analise_anatel, modelo_label, modelo_anatel)

        classificacao = classificar_produto(produto, analise_dim, analise_anatel)
        classificacao_final = str(classificacao.get("classificacao") or "").upper()
        motivo_final = str(classificacao.get("motivo_classificacao") or "")

        _log_auditoria_classificacao(classificacao)

        pid = gerar_id(produto.get("titulo"), produto.get("marca"), analise_anatel.get("codigo_anatel_normalizado"), url_produto)

        # Ajuste do status para incluir as três categorias
        status = "Irregular" if classificacao_final == "IRREGULAR" else "Suspeito" if classificacao_final == "SUSPEITO" else "Não Classificado" if classificacao_final == "NÃO CLASSIFICADO" else "Descartado"

        registro: Dict[str, Any] = {
            "pid": pid,
            "marketplace_id": "Alibaba",
            "titulo": produto.get("titulo", ""),
            "link": url_produto,
            "codigo_anatel": analise_anatel.get("codigo_anatel_normalizado") or produto.get("codigo_anatel_principal") or "",
            "marca": produto.get("marca", ""),
            "preco": produto.get("preco", ""),
            "status": status,
            "motivo_validacao": motivo_final,
            "motivo_irregularidade": motivo_final if classificacao_final == "IRREGULAR" else "",
            "warning": motivo_final if classificacao_final in ("SUSPEITO", "NÃO CLASSIFICADO") else analise_anatel.get("motivo_anatel", ""),
            "modelo": produto.get("modelo", ""),
            "nome_comercial": produto.get("nome_comercial", ""),
            "modelo_alfanumerico": produto.get("modelo_alfanumerico", ""),
            "modelo_decisivo": modelo_anatel,
            "classificacao": classificacao_final,
            "evidencia_mini": classificacao.get("evidencia_mini", ""),
            "dimensoes_encontradas": _formatar_dimensoes_encontradas(analise_dim),
            "codigo_confere_base": analise_anatel.get("codigo_confere_base", ""),
            "marca_confere_base": analise_anatel.get("marca_confere_base", ""),
            "modelo_confere_base": analise_anatel.get("modelo_confere_base", ""),
            "nome_comercial_confere_base": analise_anatel.get("nome_comercial_confere_base", ""),
            "motivo_anatel": analise_anatel.get("motivo_anatel", ""),
            "data_hora_captura": momento.strftime("%d/%m/%Y %H:%M:%S")
        }
        
        registro.update(analise_dim)
        registro.update(analise_anatel)
        registro.update(classificacao)
        registro.update(metadados_captura(pasta_saida, momento))

        if classificacao_final != "DESCARTADO":
            await _tirar_print_produto(page, pasta_saida, registro, classificacao_final)

        return registro

    except Exception as exc:
        if isinstance(exc, PlaywrightTimeoutError):
            log("erro produto", "Falha ao processar anúncio: Timeout", nivel="ERRO")
            return None
        log("erro produto", f"Falha ao processar anúncio: {exc}", nivel="ERRO")
        return None
    finally:
        if page:
            try: await page.close()
            except Exception: pass

async def _tirar_print_produto(page: Page, saida: Path, registro: Dict[str, Any], status: str) -> str:
    # Lógica ajustada para as novas pastas
    nome_pasta = "irregulares" if status == "IRREGULAR" else "suspeitos" if status == "SUSPEITO" else "nao_classificados"
    pasta = saida / "prints" / nome_pasta
    pasta.mkdir(parents=True, exist_ok=True)
    titulo = arquivo_seguro(registro.get("titulo") or "produto")
    identificador = registro.get("pid", "0000000")
    caminho = pasta / f"{identificador}_{titulo}.png"
    try:
        await page.screenshot(path=str(caminho), full_page=True)
        return str(caminho.resolve())
    except Exception: return ""

async def _salvar_print_debug(page: Page, saida: Path, termo: str, pagina: int) -> None:
    pasta = saida / "prints" / "debug_busca_sem_links"
    pasta.mkdir(parents=True, exist_ok=True)
    try:
        await page.screenshot(path=str(pasta / f"{arquivo_seguro(termo)}_pagina_{pagina}.png"), full_page=True)
    except Exception: pass

def _texto_curto(texto: Any, limite: int = 100) -> str:
    texto = " ".join(str(texto or "").split())
    return texto if len(texto) <= limite else texto[: limite - 3].rstrip() + "..."