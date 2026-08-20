from __future__ import annotations

import asyncio
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import quote
from typing import Any

from playwright.async_api import async_playwright, BrowserContext, Page

from base_anatel import BaseAnatel, analisar_situacao_anatel
from extracao_carrefour import extrair_produto_carrefour, fechar_popups_basicos, coletar_links_resultados, analisar_mini_celular_carrefour, DadosProduto
from classificacao_carrefour import classificar_produto
from utils_carrefour import bloco, criar_pastas_saida, gerar_id, log, secao, salvar_parquet_incremental, metadados_captura

def _valor_terminal(valor: Any, vazio: str = "NÃO LOCALIZADO") -> str:
    texto = str(valor or "").strip()
    return texto if texto else vazio

def _sim_nao_terminal(valor: Any) -> str:
    return "SIM" if str(valor or "").strip().upper() == "SIM" else ("NÃO VERIFICADO" if str(valor or "").strip().upper() == "NAO_VERIFICADO" else "NÃO")

def _formatar_numero_cm(valor: Any) -> str:
    if valor in (None, ""): return ""
    try: return f"{float(valor):.2f}".rstrip("0").rstrip(".").replace(".", ",")
    except Exception: return str(valor)

def _log_auditoria_dimensoes(analise: dict[str, Any]) -> None:
    vals = [_formatar_numero_cm(analise.get("altura_cm")), _formatar_numero_cm(analise.get("largura_cm")), _formatar_numero_cm(analise.get("espessura_cm"))]
    produto = " x ".join([v for v in vals if v]) + " cm" if analise.get("dimensoes_confiaveis") == "SIM" else "NÃO LOCALIZADAS"
    res = str(analise.get("dentro_limite_dimensional") or "NAO_VERIFICADO").upper()
    situacao = "DENTRO DO LIMITE" if res == "SIM" else ("ACIMA DO LIMITE" if res == "NAO" else "NÃO FOI POSSÍVEL VERIFICAR")

    print("")
    log("dimensões", "Limite adotado : 12,0 x 5,5 cm")
    log("dimensões", f"Produto        : {produto}")
    log("dimensões", "Origem         : " + _valor_terminal(analise.get("origem_dimensoes"), "não localizada"))
    log("dimensões", f"Resultado      : {situacao}")

def _log_auditoria_anatel(dados: DadosProduto, anatel: dict[str, Any], modelo_anuncio: str) -> None:
    log("anatel", "Código         : anúncio=" + _valor_terminal(dados.codigo_anatel_principal) + " | base=" + _valor_terminal(anatel.get("codigo_base")) + " | confere=" + _sim_nao_terminal(anatel.get("codigo_confere_base")))
    log("anatel", "Situação Req.  : " + _valor_terminal(anatel.get("situacao_requerimento_base"), "NÃO LOCALIZADA") + " | emitida=" + _sim_nao_terminal(anatel.get("requerimento_emitido")))
    log("anatel", "Marca          : anúncio=" + _valor_terminal(dados.marca) + " | base=" + _valor_terminal(anatel.get("fabricante_base")) + " | confere=" + _sim_nao_terminal(anatel.get("marca_confere_base")))
    log("anatel", "Modelo         : anúncio=" + _valor_terminal(modelo_anuncio) + " | base=" + _valor_terminal(anatel.get("modelo_base")) + " | confere=" + _sim_nao_terminal(anatel.get("modelo_confere_base")))
    log("anatel", "Resultado      : " + _valor_terminal(anatel.get("situacao_anatel"), "NAO_INFORMADO") + " — " + _valor_terminal(anatel.get("motivo_anatel"), "sem motivo"))

def _log_auditoria_classificacao(linha: dict[str, Any]) -> None:
    log("classificação", "Destino        : " + _valor_terminal(linha.get("classificacao"), "NÃO DEFINIDO"))
    log("classificação", "Motivo         : " + _valor_terminal(linha.get("motivo_validacao"), "sem motivo registrado"))

async def _salvar_print(page: Page, pasta_saida: Path, linha: dict[str, Any]) -> str:
    classificacao = str(linha.get("classificacao") or "").upper()
    if classificacao not in {"IRREGULAR", "SUSPEITO"}:
        return ""

    pasta = pasta_saida / "prints" / ("irregulares" if classificacao == "IRREGULAR" else "suspeitos")
    
    identificador = str(linha.get("pid") or "sem_id")
    nome_base = f"{identificador}_{linha.get('titulo') or 'produto'}"
    nome_seguro = re.sub(r'[<>:"/\\|?*\x00-\x1f\s]+', '_', nome_base)[:110]
    
    caminho = pasta / f"{nome_seguro}.png"

    try:
        await page.screenshot(path=str(caminho), full_page=True)
        return str(caminho.resolve())
    except Exception as exc:
        log("print", f"Falha ao salvar evidência: {exc}", nivel="AVISO")
        return ""

async def _criar_contexto_persistente(p: Any) -> BrowserContext:
    perfil = Path("perfil_carrefour").resolve()
    perfil.mkdir(parents=True, exist_ok=True)
    log("chrome", f"Iniciando Chrome em modo persistente (perfil_carrefour)...")
    contexto = await p.chromium.launch_persistent_context(
        user_data_dir=str(perfil),
        headless=False,
        viewport={"width": 1366, "height": 900},
        locale="pt-BR",
        args=["--disable-blink-features=AutomationControlled", "--start-maximized"],
    )
    return contexto

async def rodar_playwright_carrefour(
    query: str,
    queries: list[str],
    limite: int,
    base_anatel: BaseAnatel | None,
    url: str | None,
    saida: str | Path | None,
    max_paginas: int,
    pausar_inicio: bool,
    porta_chrome: int,
) -> dict[str, Any]:

    pasta_saida = criar_pastas_saida(saida)
    linhas: list[dict[str, Any]] = []
    
    buscas = queries or [query]
    urls_processadas: set[str] = set()
    total_processados = 0
    total_descartados = 0

    async with async_playwright() as p:
        context = await _criar_contexto_persistente(p)
        page = context.pages[0] if context.pages else await context.new_page()
        page.set_default_timeout(12000)

        try:
            if pausar_inicio:
                await page.goto("https://www.carrefour.com.br", wait_until="domcontentloaded", timeout=60000)
                secao("Pausa manual")
                print("Resolva login ou CEP no Chrome e deixe a página aberta.")
                input("Pressione ENTER no terminal para iniciar a coleta... ")

            for indice_busca, consulta_atual in enumerate(buscas, start=1):
                if limite > 0 and total_processados >= limite: break
                
                if not url:
                    destino = f"https://www.carrefour.com.br/busca/{quote(consulta_atual)}"
                    await page.goto(destino, wait_until="domcontentloaded", timeout=60000)
                    await page.wait_for_timeout(3000)
                    await fechar_popups_basicos(page)

                pagina_atual = 1
                while True:
                    if limite > 0 and total_processados >= limite: break
                    if max_paginas > 0 and pagina_atual > max_paginas: break

                    links_novos = await coletar_links_resultados(page, urls_processadas)
                    if not links_novos:
                        break 

                    for href in links_novos:
                        if limite > 0 and total_processados >= limite: break
                        
                        total_processados += 1
                        bloco(f"PRODUTO {total_processados}/{limite if limite > 0 else '∞'}")
                        log("produto", href)
                        
                        prod_page = await context.new_page()
                        prod_page.set_default_timeout(20000)
                        
                        try:
                            await prod_page.goto(href, wait_until="domcontentloaded", timeout=60000)
                            dados = await extrair_produto_carrefour(prod_page)
                            momento = datetime.now().astimezone()

                            analise_dimensional = analisar_mini_celular_carrefour(dados, maior_max_cm=12.0, largura_max_cm=5.5)
                            modelo_anatel = dados.modelo

                            anatel = analisar_situacao_anatel(dados.codigo_anatel_principal, dados.marca, modelo_anatel, base_anatel)
                            classificacao = classificar_produto(dados, analise_dimensional, anatel)
                            classificacao_final = classificacao.get("classificacao", "DESCARTADO")

                            linha = {
                                "pid": gerar_id(dados.titulo, dados.url),
                                "marketplace_id": "3",
                                "marketplace": "carrefour",
                                "titulo": dados.titulo,
                                "link": dados.url,
                                "codigo_anatel_principal": dados.codigo_anatel_principal,
                                "codigo_anatel": anatel.get("codigo_anatel_normalizado") or dados.codigo_anatel_principal,
                                "marca": dados.marca,
                                "preco": dados.preco,
                                "modelo": dados.modelo,
                                "modelo_decisivo": modelo_anatel,
                                "classificacao": classificacao_final,
                                "status_validacao": classificacao_final,
                                "motivo_validacao": classificacao.get("motivo_classificacao", ""),
                                "motivo_irregularidade": classificacao.get("motivo_classificacao", "") if classificacao_final == "IRREGULAR" else "",
                                "warning": classificacao.get("motivo_classificacao", "") if classificacao_final == "SUSPEITO" else anatel.get("motivo_anatel", ""),
                                "dimensoes_encontradas": f"{analise_dimensional.get('altura_cm', 'N/A')} x {analise_dimensional.get('largura_cm', 'N/A')} cm" if analise_dimensional.get('altura_cm') else "NAO ENCONTRADAS",
                            }
                            linha.update(anatel)
                            linha.update(metadados_captura(pasta_saida, momento))
                            
                            linha["print_path"] = await _salvar_print(prod_page, pasta_saida, linha)

                            _log_auditoria_dimensoes(analise_dimensional)
                            _log_auditoria_anatel(dados, anatel, modelo_anatel)
                            _log_auditoria_classificacao(linha)
                            
                            if classificacao_final == "DESCARTADO":
                                total_descartados += 1
                                continue

                            linhas.append(linha)
                            salvar_parquet_incremental(pasta_saida, linhas, [])

                        except Exception as exc:
                            log("erro", f"Falha ao processar anúncio: {exc}")
                        finally:
                            await prod_page.close()
                    
                    pagina_atual += 1
                    break
                
                if url: break
        finally:
            log("chrome", "Execução finalizada.")

    return {
        "pasta_saida": str(pasta_saida.resolve()), 
        "total_visitados": total_processados,
        "total_descartados": total_descartados,
        "total_produtos_no_parquet": len(linhas)
    }