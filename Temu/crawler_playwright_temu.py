from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from playwright.sync_api import BrowserContext, Page, sync_playwright

from base_anatel import BaseAnatel, analisar_situacao_anatel
from classificacao_ml import analisar_dimensoes_produto, classificar_produto
from extracao_temu import extrair_produto_temu, fechar_modais_iniciais

from crawler_playwright_ml import (
    _conectar_chrome_existente, 
    _linha_produto, 
    _log_auditoria_dimensoes, 
    _log_auditoria_anatel, 
    _log_auditoria_classificacao, 
    _salvar_print
)
from utils import log, criar_pastas_saida, salvar_parquet_incremental, secao


def _aplicar_camuflagem(page: Page) -> None:
    try:
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
            window.navigator.chrome = {
                runtime: {},
            };
            Object.defineProperty(navigator, 'languages', {
                get: () => ['pt-BR', 'pt', 'en-US', 'en']
            });
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });
        """)
    except Exception:
        pass


def _pesquisar_como_humano(page: Page, query: str) -> None:
    """Abre a home da Temu e digita na barra de pesquisa como um usuário real."""
    print("Navegando para a home da Temu...")
    page.goto("https://www.temu.com/br/", wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(3000)
    fechar_modais_iniciais(page)

    # --- PAUSA MANUAL ---
    secao("Pausa manual")
    print("A home da Temu foi aberta no Chrome.")
    print("Faça login ou resolva qualquer CAPTCHA se necessário.")
    input("Quando estiver livre na página inicial, clique aqui no terminal e pressione ENTER para o robô pesquisar... ")
    # --------------------

    print(f"Digitando a busca por: '{query}'...")
    try:
        # Seletores comuns da barra de pesquisa da Temu
        seletor_input = "input[aria-label*='Pesquisar'], input[placeholder*='Pesquisar'], input[type='text']"
        page.locator(seletor_input).first.click(timeout=3000)
        page.wait_for_timeout(500)
        
        # Digita com intervalo humano entre as letras
        page.keyboard.type(query, delay=120)
        page.wait_for_timeout(800)
        page.keyboard.press("Enter")
        
        # Aguarda a listagem de resultados carregar
        page.wait_for_timeout(5000)
        fechar_modais_iniciais(page)
    except Exception as e:
        log("busca", f"Erro ao tentar digitar na barra de pesquisa: {e}", nivel="AVISO")


def _coletar_links_scroll_infinito(page: Page, max_scrolls: int = 15) -> list[str]:
    script = r"""
    () => {
      const saida = new Set();
      for (const ancora of document.querySelectorAll('a[href]')) {
        const href = ancora.href || '';
        if (!href.includes('temu.com')) continue;
        
        const textoAncora = (ancora.innerText || '').toLowerCase();
        const lixo = ['capa', 'pelicula', 'tampão', 'tampao', 'suporte', 'cabo', 'carregador', 'cordão', 'cordao', 'pulseira'];
        const contemLixo = lixo.some(termo => textoAncora.includes(termo) || href.toLowerCase().includes(termo));

        const pareceProduto = href.includes('-g-') || href.includes('goods.html') || href.includes('goods_id');
        const pareceIgnorado = href.includes('cart') || href.includes('login') || href.includes('user');
        
        if (pareceProduto && !pareceIgnorado && !contemLixo) {
          saida.add(href.split('?')[0]); 
        }
      }
      return Array.from(saida);
    }
    """
    
    links_totais = set()
    
    for tentativa in range(1, max_scrolls + 1):
        try:
            encontrados = page.evaluate(script) or []
            for href in encontrados:
                links_totais.add(href)
        except Exception:
            pass
            
        try:
            page.mouse.wheel(0, 1500)
            page.wait_for_timeout(1800)
        except Exception:
            break
            
    return list(links_totais)


def rodar_playwright_temu(
    query: str,
    limite: int = 0,
    base_anatel: BaseAnatel | None = None,
    porta_chrome: int = 9225,
) -> None:
    pasta_saida = criar_pastas_saida()
    produtos = []
    
    with sync_playwright() as p:
        contexto = _conectar_chrome_existente(p, porta=porta_chrome)
        pagina_busca = contexto.new_page()
        
        _aplicar_camuflagem(pagina_busca)
        
        # Executa a pesquisa simulando o clique e digitação na home
        _pesquisar_como_humano(pagina_busca, query)
        
        log("busca", f"Iniciando coleta para a listagem gerada.")
        links = _coletar_links_scroll_infinito(pagina_busca)
        log("listagem", f"Encontrados {len(links)} anúncios válidos.")

        total_visitados = 0
        
        for link in links:
            if limite > 0 and total_visitados >= limite:
                break
                
            pagina_produto = contexto.new_page()
            _aplicar_camuflagem(pagina_produto)
            
            try:
                pagina_produto.goto(link, wait_until="domcontentloaded")
                pagina_produto.wait_for_timeout(2500)
                
                dados = extrair_produto_temu(pagina_produto)
                
                if not dados:
                    log("produto", "Item esgotado ou bloqueado. Pulando...", nivel="AVISO")
                    continue

                momento = datetime.now().astimezone()

                analise_dimensional = analisar_dimensoes_produto(dados)
                _log_auditoria_dimensoes(analise_dimensional)

                anatel = analisar_situacao_anatel(
                    codigo=dados.get("codigo_anatel_principal", ""),
                    marca=dados.get("marca", ""),
                    modelo_tecnico=dados.get("modelo", ""),
                    nome_comercial=dados.get("modelo", ""),
                    base=base_anatel,
                )
                
                classificacao = classificar_produto(dados, analise_dimensional, anatel)
                classificacao.update(analise_dimensional)

                linha = _linha_produto(dados, classificacao, anatel, pasta_saida, query, momento)
                
                if linha["classificacao"] != "DESCARTADO":
                    linha["print_path"] = _salvar_print(pagina_produto, pasta_saida, linha)
                    produtos.append(linha)
                    salvar_parquet_incremental(pasta_saida, produtos, [])
                    
                total_visitados += 1
                
            except Exception as e:
                log("erro", f"Falha no produto {link}: {e}", nivel="ERRO")
            finally:
                pagina_produto.close()