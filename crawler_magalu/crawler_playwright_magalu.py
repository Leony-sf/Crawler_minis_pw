# -*- coding: utf-8 -*-
"""Crawler Magalu com Playwright."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from playwright.async_api import async_playwright, BrowserContext, Page, TimeoutError as PlaywrightTimeoutError

from classificacao_magalu import classificar_produto
from extracao_magalu import coletar_links_resultados, esperar_carregamento, extrair_produto, fechar_popups_basicos
from utils_magalu import carregar_termos_busca, montar_url_busca, slugify, criar_pastas_saida_magalu
from base_anatel import BaseAnatel, analisar_situacao_anatel
from utils import log, secao, bloco, gerar_id, metadados_captura, salvar_parquet_incremental


@dataclass
class ConfigMagalu:
    txt: str = "buscar_magalu.txt"
    saida: Optional[Path] = None
    base_anatel: Optional[BaseAnatel] = None
    limit: int = 100
    max_paginas: int = 2
    headless: bool = False
    slow_mo: int = 0
    timeout_ms: int = 30000
    salvar_descartados: bool = False
    limpar_prints: bool = False
    pausar_inicio: bool = False


def _comentarios_para_linhas(produto: dict[str, Any], comentarios: list[str]) -> list[dict[str, Any]]:
    linhas: list[dict[str, Any]] = []

    for ordem, comentario in enumerate(comentarios, start=1):
        linhas.append({
            "pid": produto.get("pid", ""),
            "marketplace_id": "3", # Identificador Magalu
            "url": produto.get("url", ""),
            "link": produto.get("link", ""),
            "titulo": produto.get("titulo", ""),
            "name": produto.get("name", ""),
            "comentario_ordem": ordem,
            "comment": comentario,
            "comentario": comentario,
            "created_at": produto.get("created_at", ""),
            "query_busca": produto.get("query_busca", ""),
            "classificacao": produto.get("classificacao", ""),
            "status": produto.get("status", ""),
            "status_validacao": produto.get("status_validacao", ""),
            "codigo_anatel_principal": produto.get("codigo_anatel_principal", ""),
            "anatel_number": produto.get("anatel_number", ""),
            "marca": produto.get("marca", ""),
            "brand": produto.get("brand", ""),
            "modelo": produto.get("modelo", ""),
            "data_hora_captura": produto.get("data_hora_captura", ""),
            "data_hora_captura_iso": produto.get("data_hora_captura_iso", ""),
            "referencia_captura": produto.get("referencia_captura", ""),
            "pasta_saida_execucao": produto.get("pasta_saida_execucao", ""),
            "caminho_saida_execucao": produto.get("caminho_saida_execucao", ""),
        })

    return linhas


async def executar_crawler_magalu(config: ConfigMagalu) -> List[Dict[str, Any]]:
    termos = carregar_termos_busca(config.txt)
    config.saida = criar_pastas_saida_magalu(config.saida)
    
    secao("CRAWLER MAGALU | MINI CELULARES")
    log("arquivos", f"Pasta desta execução: {config.saida.resolve()}")

    resultados: List[Dict[str, Any]] = []
    comentarios: List[Dict[str, Any]] = []
    visitados: set[str] = set()
    total_cards = 0
    total_descartados = 0
    total_erros = 0
    total_analisados = 0

    # Inicializa os parquets vazios no formato oficial
    salvar_parquet_incremental(config.saida, resultados, comentarios)

    async with async_playwright() as p:
        contexto = await _criar_contexto(p, config)
        page = await _obter_pagina_principal(contexto)
        page.set_default_timeout(config.timeout_ms)

        if config.pausar_inicio:
            await _abrir_pagina_para_pausa(page, config, termos[0])
            log("pausa", "Resolva CEP/login/captcha/verificação no navegador. Pressione ENTER aqui para continuar.")
            input("")

        for pagina in range(1, config.max_paginas + 1):
            if total_analisados >= config.limit:
                break

            secao(f"RODADA DE BUSCA | PÁGINA {pagina}/{config.max_paginas}")

            for idx_termo, termo in enumerate(termos, start=1):
                if total_analisados >= config.limit:
                    break

                url_busca = montar_url_busca(termo, pagina)
                bloco(f"Busca: {termo} (Pag. {pagina})")
                
                try:
                    await page.goto(url_busca, wait_until="domcontentloaded", timeout=config.timeout_ms)
                    await esperar_carregamento(page, timeout_ms=config.timeout_ms)
                    await fechar_popups_basicos(page)
                except PlaywrightTimeoutError:
                    log("aviso", "Timeout na busca. Tentando aproveitar o que carregou.")
                except Exception as exc:
                    log("erro", f"Erro ao abrir busca: {str(exc)[:120]}")
                    total_erros += 1
                    continue

                cards = await coletar_links_resultados(page)
                total_cards += len(cards)
                log("listagem", f"Links candidatos localizados: {len(cards)}")

                if not cards:
                    await _salvar_print_debug(page, config.saida, termo, pagina)
                    continue

                for indice, card in enumerate(cards, start=1):
                    if total_analisados >= config.limit:
                        break

                    url_produto = card.get("url", "")
                    if not url_produto or url_produto in visitados:
                        continue
                    visitados.add(url_produto)

                    numero_atual = total_analisados + 1
                    total_analisados += 1

                    bloco(f"Produto {indice}/{len(cards)} | Total {numero_atual}/{config.limit}")
                    log("produto", url_produto)

                    registro = await _processar_produto(
                        contexto=contexto, url_produto=url_produto, card=card,
                        config=config, termo=termo, indice_item=indice
                    )
                    
                    if not registro:
                        total_erros += 1
                        continue

                    if registro.get("classificacao") == "DESCARTADO":
                        total_descartados += 1
                        if not config.salvar_descartados:
                            continue

                    # Extrai os comentários brutos antes de adicionar aos resultados principais
                    comentarios_brutos = registro.pop("comentarios", [])
                    
                    resultados.append(registro)
                    
                    # Converte os comentários para o Schema e adiciona na lista global
                    comentarios.extend(_comentarios_para_linhas(registro, comentarios_brutos))
                    
                    # Salva utilizando a função oficial atualizada
                    salvar_parquet_incremental(config.saida, resultados, comentarios)

        await contexto.close()

    # Salva estado final
    salvar_parquet_incremental(config.saida, resultados, comentarios)
    _imprimir_final(resultados, config, total_descartados, total_erros, total_analisados)
    
    return resultados


async def _obter_pagina_principal(contexto: BrowserContext) -> Page:
    if contexto.pages:
        page = contexto.pages[0]
        for extra in contexto.pages[1:]:
            try:
                if extra.url == "about:blank":
                    await extra.close()
            except Exception:
                pass
        return page
    return await contexto.new_page()


async def _abrir_pagina_para_pausa(page: Page, config: ConfigMagalu, primeiro_termo: str) -> None:
    url_inicial = montar_url_busca(primeiro_termo, 1)
    log("inicio", "Abrindo Magalu para verificação inicial...")
    try:
        await page.goto(url_inicial, wait_until="domcontentloaded", timeout=config.timeout_ms)
        await esperar_carregamento(page, timeout_ms=config.timeout_ms)
        await fechar_popups_basicos(page)
    except Exception as exc:
        log("aviso", f"Não foi possível abrir a página inicial: {str(exc)[:120]}")


async def _criar_contexto(p: Any, config: ConfigMagalu) -> BrowserContext:
    perfil = Path("perfil_magalu").resolve()
    perfil.mkdir(parents=True, exist_ok=True)
    contexto = await p.chromium.launch_persistent_context(
        user_data_dir=str(perfil),
        headless=config.headless,
        slow_mo=config.slow_mo,
        viewport={"width": 1366, "height": 900},
        locale="pt-BR",
        args=[
            "--disable-blink-features=AutomationControlled",
            "--start-maximized",
        ],
    )
    return contexto


async def _processar_produto(
    contexto: BrowserContext, url_produto: str, card: Dict[str, Any],
    config: ConfigMagalu, termo: str, indice_item: int
) -> Optional[Dict[str, Any]]:
    page: Optional[Page] = None
    try:
        page = await contexto.new_page()
        page.set_default_timeout(config.timeout_ms)
        await page.goto(url_produto, wait_until="domcontentloaded", timeout=config.timeout_ms)
        
        produto = await extrair_produto(page, url_produto, card)
        
        anatel = analisar_situacao_anatel(
            produto.get("codigo_anatel_principal", ""),
            produto.get("marca", ""),
            produto.get("modelo", ""),
            config.base_anatel
        )
        
        classificacao = classificar_produto(produto, anatel)

        # Auditoria padronizada
        log("dimensões", f"Maior dimensão capturada: {classificacao.maior_dimensao_mm or 'Não localizada'} mm")
        log("anatel", f"Código: {anatel.get('codigo_anatel_normalizado', 'N/A')} | "
                      f"Confere Base: {anatel.get('codigo_confere_base', 'N/A')} | "
                      f"Marca/Mod. Confere: {anatel.get('marca_confere_base', 'N/A')}/{anatel.get('modelo_confere_base', 'N/A')}")
        log("classificação", f"Destino: {classificacao.status}")
        if classificacao.motivos:
            log("classificação", f"Motivo : {classificacao.motivos[0][:110]}")

        classificacao_final = classificacao.status
        motivo_final = classificacao.motivos[0] if classificacao.motivos else ""

        if classificacao_final == "IRREGULAR":
            status_legado = "Irregular"
        elif classificacao_final == "SUSPEITO":
            status_legado = "Suspeito"
        else:
            status_legado = "Descartado"

        dimensoes = []
        if classificacao.altura_cm:
            dimensoes.append(str(classificacao.altura_cm).replace('.', ','))
        if classificacao.largura_cm:
            dimensoes.append(str(classificacao.largura_cm).replace('.', ','))
        dimensoes_fmt = " x ".join(dimensoes) + " cm" if dimensoes else "NÃO LOCALIZADAS"

        pid = gerar_id(
            produto.get("titulo"),
            produto.get("marca"),
            anatel.get("codigo_anatel_normalizado"),
            url_produto
        )

        registro: Dict[str, Any] = {
            "pid": pid,
            "marketplace_id": "3",
            "name": produto.get("titulo", ""),
            "titulo": produto.get("titulo", ""),
            "link": url_produto,
            "url": url_produto,
            "anatel_number": anatel.get("codigo_anatel_normalizado", ""),
            "codigo_anatel_principal": produto.get("codigo_anatel_principal", ""),
            "brand": produto.get("marca", ""),
            "marca": produto.get("marca", ""),
            "price": produto.get("preco", ""),
            "preco": produto.get("preco", ""),
            "reviewers": "",
            "status": status_legado,
            "status_validacao": classificacao_final,
            "irregularity_reasons": motivo_final if classificacao_final == "IRREGULAR" else "",
            "motivo_validacao": motivo_final,
            "warnings": motivo_final if classificacao_final == "SUSPEITO" else anatel.get("motivo_anatel", ""),
            "created_at": datetime.now().strftime("%Y-%m-%d"),
            "modelo": produto.get("modelo", ""),
            "modelo_detalhado": "",
            "modelo_alfanumerico": "",
            "numero_modelo": "",
            "modelo_decisivo_label": "Modelo",
            "modelo_decisivo": produto.get("modelo", ""),
            "modelo_decisivo_partes_json": "[]",
            "modelos_capturados_json": "[]",
            "fabricante": produto.get("fornecedor", ""),
            "modo_match_base": anatel.get("situacao_anatel", ""),
            "query_busca": termo,
            "descricao": produto.get("detalhes", ""),
            "texto_pagina": produto.get("texto_pagina", ""),
            "atributos_json": "{}",
            "total_comentarios": len(produto.get("comentarios", [])),
            "comentarios": produto.get("comentarios", []),
            "print_path": "",
            "codigo_anatel": anatel.get("codigo_anatel_normalizado") or produto.get("codigo_anatel_principal", ""),
            "motivo_irregularidade": motivo_final if classificacao_final == "IRREGULAR" else "",
            "warning": motivo_final if classificacao_final == "SUSPEITO" else "",
            "dimensoes_encontradas": dimensoes_fmt,
            "classificacao": classificacao_final,
            "evidencia_mini": "; ".join(classificacao.evidencias),
            "codigo_confere_base": anatel.get("codigo_confere_base", ""),
            "marca_confere_base": anatel.get("marca_confere_base", ""),
            "modelo_confere_base": anatel.get("modelo_confere_base", ""),
            "motivo_anatel": anatel.get("motivo_anatel", ""),
        }

        registro.update(metadados_captura(config.saida))

        if classificacao_final != "DESCARTADO" and classificacao.categoria_print:
            registro["print_path"] = await _tirar_print_produto(
                page, config.saida, registro, classificacao.categoria_print
            )

        return registro
    except PlaywrightTimeoutError:
        log("erro", "Timeout ao abrir/coletar produto.")
        return None
    except Exception as exc:
        log("erro", f"Erro no processamento: {str(exc)[:110]}")
        return None
    finally:
        if page:
            try:
                await page.close()
            except Exception:
                pass


async def _tirar_print_produto(page: Page, saida: Path, registro: Dict[str, Any], categoria: str) -> str:
    pasta = saida / "prints" / categoria
    pasta.mkdir(parents=True, exist_ok=True)
    titulo = slugify(registro.get("titulo", "produto"), max_len=70)
    indice = abs(hash(registro.get("url", ""))) % 10_000_000
    caminho = pasta / f"{indice}_{titulo}.png"
    try:
        await page.screenshot(path=str(caminho), full_page=True)
        return str(caminho)
    except Exception:
        return ""


async def _salvar_print_debug(page: Page, saida: Path, termo: str, pagina: int) -> None:
    pasta = saida / "prints" / "debug_busca_sem_links"
    pasta.mkdir(parents=True, exist_ok=True)
    caminho = pasta / f"{slugify(termo)}_pagina_{pagina}.png"
    try:
        await page.screenshot(path=str(caminho), full_page=True)
    except Exception:
        pass


def _imprimir_final(
    resultados: List[Dict[str, Any]], config: ConfigMagalu, 
    total_descartados: int, total_erros: int, total_analisados: int,
) -> None:
    qtd_irregulares = sum(1 for r in resultados if r.get("classificacao") == "IRREGULAR")
    qtd_suspeitos = sum(1 for r in resultados if r.get("classificacao") == "SUSPEITO")

    secao("FINALIZADO")
    log("resumo", f"Analisados: {total_analisados}/{config.limit} | Salvos: {len(resultados)}")
    log("resumo", f"Irregulares: {qtd_irregulares} | Suspeitos: {qtd_suspeitos}")
    log("resumo", f"Descartados não salvos: {total_descartados if not config.salvar_descartados else 0} | Erros: {total_erros}")
    log("resumo", f"Saída: {config.saida.resolve()}")

def run(config: ConfigMagalu) -> List[Dict[str, Any]]:
    return asyncio.run(executar_crawler_magalu(config))