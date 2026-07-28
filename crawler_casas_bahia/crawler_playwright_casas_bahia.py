# -*- coding: utf-8 -*-
"""Crawler Casas Bahia — fluxo com Chromium + Stealth (Blindado)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import time
import random
import pandas as pd
from playwright.sync_api import (
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeoutError,
    sync_playwright,
)
from playwright_stealth import stealth_sync

from classificacao_casas_bahia import classificar_produto
from extracao_casas_bahia import (
    aceitar_cookies_se_aparecer,
    coletar_links_resultados,
    esperar_carregamento,
    extrair_produto,
    pagina_erro_casas_bahia,
)
from utils_casas_bahia import (
    agora_iso,
    carregar_termos_busca,
    escrever_resumo_txt,
    montar_urls_busca,
    preparar_saida,
    slugify,
)


@dataclass
class ConfigCasasBahia:
    txt: str = "buscar_casas_bahia.txt"
    saida: Path = Path("saidas_casas_bahia")
    perfil: Path = Path("perfil_casas_bahia")
    limit: int = 100
    max_paginas: int = 2
    headless: bool = False
    slow_mo: int = 0
    timeout_ms: int = 30000
    salvar_descartados: bool = False
    limpar_prints: bool = False
    pausar_inicio: bool = False


def run(config: ConfigCasasBahia) -> List[Dict[str, Any]]:
    return executar_crawler_casas_bahia(config)


def executar_crawler_casas_bahia(config: ConfigCasasBahia) -> List[Dict[str, Any]]:
    termos = carregar_termos_busca(config.txt)
    preparar_saida(config.saida, limpar_prints=config.limpar_prints)

    resultados: List[Dict[str, Any]] = []
    visitados: set[str] = set()
    total_cards = 0
    total_descartados = 0
    total_erros = 0
    total_analisados = 0

    _imprimir_cabecalho(config, termos)

    with sync_playwright() as p:
        contexto = _criar_contexto(p, config)
        page = contexto.new_page()
        stealth_sync(page)  # <-- Aplicando Stealth na página de busca
        page.set_default_timeout(config.timeout_ms)

        if config.pausar_inicio:
            _abrir_home_para_pausa(page, config)
            print("\n[PAUSA] Verifique cookies/captcha, se aparecer.")
            input("        Pressione ENTER aqui no terminal para iniciar a coleta...")

        try:
            for pagina in range(1, config.max_paginas + 1):
                if total_analisados >= config.limit:
                    break

                _imprimir_secao(f"RODADA DE BUSCA | PÁGINA {pagina}/{config.max_paginas}")

                for idx_termo, termo in enumerate(termos, start=1):
                    if total_analisados >= config.limit:
                        break

                    print(f"\n[BUSCA] Página {pagina}/{config.max_paginas} | Linha {idx_termo}/{len(termos)} do TXT")
                    print(f"        Termo: {termo}")

                    cards = _abrir_busca_e_coletar(page, config, termo, pagina)
                    total_cards += len(cards)
                    print(f"        Links candidatos: {len(cards)}")

                    time.sleep(random.uniform(4.0, 7.5))

                    cards = _abrir_busca_e_coletar(page, config, termo, pagina)

                    if not cards:
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

                        registro = _processar_produto(
                            contexto=contexto,
                            url_produto=url_produto,
                            card=card,
                            config=config,
                            termo=termo,
                            pagina=pagina,
                            indice_item=indice,
                            total_itens=len(cards),
                            numero_processado=numero_atual,
                        )

                        if not registro:
                            total_erros += 1
                            continue

                        if registro.get("status") == "DESCARTADO":
                            total_descartados += 1
                            if not config.salvar_descartados:
                                continue

                        resultados.append(registro)
                        _salvar_parquets_incrementais(resultados, config.saida)
        
        except KeyboardInterrupt:
            print("\n[AVISO] Execução interrompida pelo usuário (Ctrl+C)! Salvando progresso...")
        finally:
            contexto.close()

    _salvar_parquets_incrementais(resultados, config.saida)
    _salvar_resumo(resultados, config, termos, total_cards, total_descartados, total_erros, total_analisados)
    _imprimir_final(resultados, config, total_descartados, total_erros, total_analisados)
    return resultados


def _criar_contexto(p, config: ConfigCasasBahia) -> BrowserContext:
    print("[INFO] Iniciando Chrome nativo pelo Playwright...")
    config.perfil.mkdir(parents=True, exist_ok=True)
    
    return p.chromium.launch_persistent_context(
        user_data_dir=str(config.perfil.resolve()),
        headless=config.headless,
        slow_mo=config.slow_mo,
        viewport={"width": 1366, "height": 900},
        locale="pt-BR",
        args=["--disable-blink-features=AutomationControlled"],
        ignore_default_args=["--enable-automation"]
    )


def _abrir_home_para_pausa(page: Page, config: ConfigCasasBahia) -> None:
    print("[INÍCIO] Abrindo Casas Bahia para verificação inicial...")
    try:
        page.goto("https://www.casasbahia.com.br", wait_until="domcontentloaded", timeout=config.timeout_ms)
        esperar_carregamento(page, timeout_ms=config.timeout_ms)
        aceitar_cookies_se_aparecer(page)
    except Exception as exc:
        print(f"        Aviso: não foi possível abrir a página inicial: {_texto_curto(str(exc), 120)}")


def _localizar_campo_busca(page: Page):
    seletores = [
        "input[placeholder*='procurando' i]",
        "input[placeholder*='busca' i]",
        "input[placeholder*='buscar' i]",
        "input[type='search']",
        "input[name*='search' i]",
        "input[name*='termo' i]",
        "input[id*='search' i]",
        "input[id*='busca' i]",
    ]

    for seletor in seletores:
        try:
            campo = page.locator(seletor).first
            if campo.count():
                return campo
        except Exception:
            continue
    return None


def _acionar_botao_busca(page: Page) -> bool:
    seletores = [
        "button[aria-label*='buscar' i]",
        "button[title*='buscar' i]",
        "button[type='submit']",
        "button:has-text('Buscar')",
        "[aria-label*='buscar' i]",
        "svg[aria-label*='buscar' i]",
        "form button",
    ]

    for seletor in seletores:
        try:
            botao = page.locator(seletor).first
            if botao.count():
                botao.click(timeout=1000)
                return True
        except Exception:
            continue
    return False


def _buscar_pela_caixa_organizada(page: Page, config: ConfigCasasBahia, termo: str) -> List[Dict[str, Any]]:
    try:
        campo = _localizar_campo_busca(page)
        if campo is None:
            return []

        campo.click(timeout=1000)
        page.keyboard.press("Control+A")
        page.keyboard.type(termo, delay=35)

        try:
            page.keyboard.press("Escape")
        except Exception:
            pass

        page.wait_for_timeout(250)

        if not _acionar_botao_busca(page):
            page.keyboard.press("Enter")

        esperar_carregamento(page, timeout_ms=config.timeout_ms)
        aceitar_cookies_se_aparecer(page)
        page.wait_for_timeout(900)

        if pagina_erro_casas_bahia(page):
            print("\n🚨 [BLOQUEIO NA BUSCA] Resolva o Captcha na janela do Chrome aberta.")
            input("🚨 Pressione [ENTER] aqui APÓS a página de resultados carregar normalmente...")

        return coletar_links_resultados(page)

    except Exception:
        return []


def _buscar_pela_home_organizada(page: Page, config: ConfigCasasBahia, termo: str) -> List[Dict[str, Any]]:
    try:
        page.goto("https://www.casasbahia.com.br", wait_until="domcontentloaded", timeout=config.timeout_ms)
        esperar_carregamento(page, timeout_ms=config.timeout_ms)
        aceitar_cookies_se_aparecer(page)
        page.wait_for_timeout(500)
        return _buscar_pela_caixa_organizada(page, config, termo)
    except Exception:
        return []


def _abrir_busca_e_coletar(page: Page, config: ConfigCasasBahia, termo: str, pagina: int) -> List[Dict[str, Any]]:
    for url_busca in montar_urls_busca(termo, pagina=pagina):
        try:
            print(f"        URL: {url_busca}")
            page.goto(url_busca, wait_until="domcontentloaded", timeout=config.timeout_ms)
            esperar_carregamento(page, timeout_ms=config.timeout_ms)
            aceitar_cookies_se_aparecer(page)

            if pagina_erro_casas_bahia(page):
                print("\n🚨 [BLOQUEIO NA BUSCA] O site travou a requisição.")
                print("🚨 Vá na janela do Chrome e resolva o CAPTCHA ou recarregue a página.")
                input("🚨 Pressione [ENTER] aqui no terminal APÓS carregar os resultados...")

            cards = coletar_links_resultados(page)
            if cards:
                return cards

        except PlaywrightTimeoutError:
            print("        Aviso: timeout na busca. Tentando aproveitar o que carregou.")
            try:
                cards = coletar_links_resultados(page)
                if cards:
                    return cards
            except Exception:
                pass
        except Exception as exc:
            print(f"        Erro na busca: {_texto_curto(str(exc), 120)}")

    print("        Fallback: tentando buscar pela caixa da home, sem autocomplete/topterms...")
    return _buscar_pela_home_organizada(page, config, termo)


def _processar_produto(
    contexto: BrowserContext,
    url_produto: str,
    card: Dict[str, Any],
    config: ConfigCasasBahia,
    termo: str,
    pagina: int,
    indice_item: int,
    total_itens: int,
    numero_processado: int,
) -> Optional[Dict[str, Any]]:
    page: Optional[Page] = None

    try:
        # Pega os cookies atuais do contexto e injeta na nova aba para manter a sessão humana
        cookies_atuais = contexto.cookies()
        page = contexto.new_page()
        page.context.add_cookies(cookies_atuais)
        
        page.set_default_timeout(config.timeout_ms)

        # Respiro humano antes de navegar para o produto
        time.sleep(random.uniform(2.0, 4.0))

        page.goto(
            url_produto, 
            referer="https://www.casasbahia.com.br/",
            wait_until="commit", 
            timeout=config.timeout_ms
        )
        
        # Pausa para o servidor respirar antes de rodar os seletores
        time.sleep(random.uniform(1.5, 3.0))
        esperar_carregamento(page, timeout_ms=config.timeout_ms)

        # Auto-Recuperação: Tenta dar F5 até 3 vezes se cair na tela de erro
        tentativas_f5 = 0
        while pagina_erro_casas_bahia(page) and tentativas_f5 < 3:
            print(f"\n[AUTO-RECUPERAÇÃO] Bloqueio detectado. Tentativa {tentativas_f5 + 1} de recarregar a página (F5)...")
            time.sleep(random.uniform(4.0, 8.0))
            page.reload(wait_until="commit", timeout=config.timeout_ms)
            esperar_carregamento(page, timeout_ms=config.timeout_ms)
            tentativas_f5 += 1

        # Mecanismo de Pausa Inteligente caso o F5 automático falhe
        if pagina_erro_casas_bahia(page):
            print("\n🚨 [BLOQUEIO PERSISTENTE] Site limitou o acesso rápido.")
            print("🚨 Vá na janela do Chrome aberta, resolva o desafio ou recarregue manualmente.")
            input("🚨 Pressione [ENTER] aqui no terminal DEPOIS que o produto estiver na tela para continuar...")
            
            if pagina_erro_casas_bahia(page):
                registro_erro = _registro_erro_timeout(url_produto, card, termo, pagina, indice_item)
                registro_erro["motivo"] = "Página de erro persistente mesmo após F5 e pausa manual."
                _imprimir_produto(registro_erro, numero_processado, config.limit, indice_item, total_itens)
                return registro_erro

        produto = extrair_produto(page, url_produto, card)
        classificacao = classificar_produto(produto)

        registro: Dict[str, Any] = {
            "data_coleta": agora_iso(),
            "marketplace": "Casas Bahia",
            "termo_busca": termo,
            "pagina_busca": pagina,
            "item_busca": indice_item,
            "status": classificacao.status,
            **classificacao.as_dict(),
            "titulo": produto.get("titulo", ""),
            "preco": produto.get("preco", ""),
            "fornecedor": produto.get("fornecedor", ""),
            "moq": produto.get("moq", ""),
            "vendidos_pedidos": produto.get("vendidos_pedidos", ""),
            "url": produto.get("url", url_produto),
            "url_canonica": produto.get("url_canonica", url_produto),
            "imagem": produto.get("imagem", ""),
            "detalhes": produto.get("detalhes", "")[:6000],
            "ficha_tecnica": produto.get("ficha_tecnica", "")[:6000],
            "texto_card": produto.get("texto_card", "")[:2000],
            "print_comprovante": "",
        }

        if classificacao.status != "DESCARTADO" and classificacao.categoria_print:
            registro["print_comprovante"] = _tirar_print_produto(
                page,
                config.saida,
                registro,
                classificacao.categoria_print,
            )

        _imprimir_produto(registro, numero_processado, config.limit, indice_item, total_itens)
        
        # Atraso aleatório longo e realista
        time.sleep(random.uniform(4.5, 12.8))

        # Respiro longo em lotes para esfriar o IP a cada 10 produtos
        if numero_processado % 10 == 0:
            print(f"\n[RESPIRO] Lote de {numero_processado} atingido. Pausa longa (30 a 50s) para esfriar o IP...")
            time.sleep(random.uniform(30.0, 50.0))
            
        return registro

    except PlaywrightTimeoutError:
        registro_erro = _registro_erro_timeout(url_produto, card, termo, pagina, indice_item)
        _imprimir_produto(registro_erro, numero_processado, config.limit, indice_item, total_itens)
        return registro_erro

    except Exception as exc:
        print(f"[{numero_processado:03d}] ERRO | {_texto_curto(str(exc), 110)}")
        return None

    finally:
        if page:
            try:
                page.close()
            except Exception:
                pass

def _registro_erro_timeout(url_produto: str, card: Dict[str, Any], termo: str, pagina: int, indice_item: int) -> Dict[str, Any]:
    return {
        "data_coleta": agora_iso(),
        "marketplace": "Casas Bahia",
        "termo_busca": termo,
        "pagina_busca": pagina,
        "item_busca": indice_item,
        "status": "ERRO",
        "categoria_print": "",
        "motivo": "Timeout ao abrir/coletar produto.",
        "evidencias": "",
        "codigo_anatel": "",
        "tela_extraida": "",
        "tela_polegadas": None,
        "tela_mini": False,
        "tela_suspeita": False,
        "tela_grande": False,
        "eh_mini_celular": False,
        "eh_acessorio": False,
        "sem_tela": False,
        "regra_classificacao": "timeout",
        "medidas_extraidas": "",
        "altura_cm": None,
        "largura_cm": None,
        "medida_proxima_ou_menor": False,
        "sem_medidas": False,
        "maior_dimensao_mm": None,
        "altura_mm": None,
        "largura_mm": None,
        "comprimento_mm": None,
        "titulo": card.get("titulo_busca", ""),
        "preco": "",
        "fornecedor": "",
        "moq": "",
        "vendidos_pedidos": "",
        "url": url_produto,
        "url_canonica": url_produto,
        "imagem": "",
        "detalhes": "",
        "ficha_tecnica": "",
        "texto_card": card.get("texto_card", ""),
        "print_comprovante": "",
    }


def _tirar_print_produto(page: Page, saida: Path, registro: Dict[str, Any], categoria: str) -> str:
    pasta = saida / "prints" / categoria
    pasta.mkdir(parents=True, exist_ok=True)

    titulo = slugify(registro.get("titulo") or registro.get("url_canonica", "produto"), max_len=70)
    indice = abs(hash(registro.get("url_canonica", ""))) % 10_000_000
    caminho = pasta / f"{indice}_{titulo}.png"

    try:
        page.screenshot(path=str(caminho), full_page=True)
        return str(caminho)
    except Exception as exc:
        print(f"        Aviso: não foi possível tirar print: {_texto_curto(str(exc), 100)}")
        return ""


def _salvar_parquets_incrementais(resultados: List[Dict[str, Any]], saida: Path) -> None:
    if not resultados:
        return

    df = pd.DataFrame(resultados)
    df.to_parquet(saida / "products.parquet", index=False)

    suspeitos = pd.DataFrame()
    if "status" in df.columns:
        suspeitos = df[df["status"].isin(["SUSPEITO", "REVISAR"])].copy()

    pasta_suspeitos = saida / "suspeitos"
    pasta_suspeitos.mkdir(parents=True, exist_ok=True)
    caminho_suspeitos = pasta_suspeitos / "suspeitos.parquet"

    if not suspeitos.empty:
        suspeitos.to_parquet(caminho_suspeitos, index=False)
    elif caminho_suspeitos.exists():
        caminho_suspeitos.unlink()


def _salvar_resumo(
    resultados: List[Dict[str, Any]],
    config: ConfigCasasBahia,
    termos: List[str],
    total_cards: int,
    total_descartados: int,
    total_erros: int,
    total_analisados: int,
) -> None:
    df = pd.DataFrame(resultados)
    qtd_sem_medidas = 0
    qtd_irregulares_dimensao = 0
    qtd_suspeitos_dimensao = 0

    if not df.empty:
        if "sem_medidas" in df.columns:
            qtd_sem_medidas = int(((df["sem_medidas"] == True) & (df["status"] == "REVISAR")).sum())  # noqa: E712
        if "status" in df.columns:
            qtd_irregulares_dimensao = int((df["status"] == "IRREGULAR").sum())
            qtd_suspeitos_dimensao = int((df["status"] == "SUSPEITO").sum())

    linhas = [
        "Resumo da coleta Casas Bahia",
        "==============================",
        f"Data/hora: {agora_iso()}",
        "Fluxo: URL de busca -> scroll sem clique -> coleta links -> abre produto por URL -> análise.",
        "Regra aplicada: celular com maior dimensão física <= 80 mm = IRREGULAR; acima de 80 até 90 mm = SUSPEITO",
        f"Termos de busca: {', '.join(termos)}",
        f"Páginas por termo: {config.max_paginas}",
        f"Limite configurado: {config.limit}",
        f"Produtos analisados nesta execução: {total_analisados}",
        f"Links candidatos em páginas de busca: {total_cards}",
        f"Registros salvos no products.parquet: {len(resultados)}",
        f"Irregulares por dimensão <= 80 mm: {qtd_irregulares_dimensao}",
        f"Suspeitos por dimensão próxima (>80 até 90 mm): {qtd_suspeitos_dimensao}",
        f"Celulares sem medida física capturada: {qtd_sem_medidas}",
        f"Descartados não salvos: {total_descartados if not config.salvar_descartados else 0}",
        f"Erros/timeout: {total_erros}",
        "",
        "Contagem por status:",
    ]

    if df.empty:
        linhas.append("- Nenhum registro salvo.")
    else:
        for status, qtd in df["status"].value_counts(dropna=False).items():
            linhas.append(f"- {status}: {qtd}")

        if "categoria_print" in df.columns:
            linhas.extend(["", "Contagem por categoria de print:"])
            for cat, qtd in df["categoria_print"].fillna("").value_counts().items():
                if cat:
                    linhas.append(f"- {cat}: {qtd}")

    escrever_resumo_txt(config.saida, linhas)


def _imprimir_cabecalho(config: ConfigCasasBahia, termos: List[str]) -> None:
    _imprimir_secao("CRAWLER CASAS BAHIA | MINI CELULARES")
    print(f"Termos: {len(termos)} | Páginas/termo: {config.max_paginas} | Limite: {config.limit}")
    print(f"Saída: {config.saida.resolve()}")
    print(f"Perfil: {config.perfil.resolve()}")
    print("Arquivos: products.parquet + suspeitos/suspeitos.parquet")
    print("Fluxo  : URL busca -> se necessário caixa organizada -> scroll sem clique -> links -> produto por URL")
    print("Filtro : dimensão <= 80 mm = IRREGULAR; > 80 até 90 mm = SUSPEITO; > 90 mm = DESCARTADO")


def _imprimir_secao(titulo: str) -> None:
    print("\n" + "=" * 72)
    print(titulo)
    print("=" * 72)


def _imprimir_produto(registro: Dict[str, Any], numero: int, limite: int, item: int, total_itens: int) -> None:
    status = registro.get("status", "")
    categoria = registro.get("categoria_print", "") or "sem_print"
    categoria_curta = categoria.split("/")[-1] if categoria else "sem_print"
    titulo = _texto_curto(registro.get("titulo") or registro.get("url_canonica", ""), 86)
    motivo = _texto_curto(registro.get("motivo", ""), 110)
    maior_dim = registro.get("maior_dimensao_mm", None)

    print(f"[{numero:03d}/{limite}] {status:<10} | {categoria_curta:<18} | item {item}/{total_itens}")

    if titulo:
        print(f"        Título   : {titulo}")

    if maior_dim not in (None, ""):
        print(f"        Dimensão : maior dimensão {maior_dim} mm")
    else:
        print("        Dimensão : não localizada")

    if motivo and status != "DESCARTADO":
        print(f"        Motivo   : {motivo}")


def _imprimir_final(
    resultados: List[Dict[str, Any]],
    config: ConfigCasasBahia,
    total_descartados: int,
    total_erros: int,
    total_analisados: int,
) -> None:
    df = pd.DataFrame(resultados)
    qtd_sem_medidas = 0
    qtd_irregulares = 0
    qtd_suspeitos = 0

    if not df.empty:
        if "sem_medidas" in df.columns:
            qtd_sem_medidas = int(((df["sem_medidas"] == True) & (df["status"] == "REVISAR")).sum())  # noqa: E712
        if "status" in df.columns:
            qtd_irregulares = int((df["status"] == "IRREGULAR").sum())
            qtd_suspeitos = int((df["status"] == "SUSPEITO").sum())

    _imprimir_secao("FINALIZADO")
    print(f"Produtos analisados: {total_analisados}/{config.limit}")
    print(f"Registros no products.parquet: {len(resultados)}")
    print(f"Irregulares por dimensão <= 80 mm: {qtd_irregulares}")
    print(f"Suspeitos por dimensão > 80 e <= 90 mm: {qtd_suspeitos}")
    print(f"Celulares sem medida física capturada: {qtd_sem_medidas}")
    print(f"Descartados não salvos: {total_descartados if not config.salvar_descartados else 0}")
    print(f"Erros/timeout: {total_erros}")
    print(f"Pasta de saída: {config.saida.resolve()}")


def _texto_curto(texto: str, limite: int = 90) -> str:
    texto = " ".join(str(texto or "").split())
    return texto if len(texto) <= limite else texto[: limite - 3] + "..."