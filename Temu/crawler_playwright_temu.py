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


def _pesquisar_como_humano(page: Page, query: str) -> bool:
    print("Navegando para a home da Temu...")
    page.goto("https://www.temu.com/br/", wait_until="domcontentloaded", timeout=45000)
    page.wait_for_timeout(3000)
    fechar_modais_iniciais(page)

    secao("Pausa manual")
    print("A home da Temu foi aberta no Chrome.")
    print("Faça login ou resolva qualquer CAPTCHA se necessário.")
    input("Quando estiver livre na página inicial, clique aqui no terminal e pressione ENTER para o robô pesquisar... ")

    print(f"A digitar a busca por: '{query}'...")
    try:
        seletores = [
            "input[type='search']",
            "input[id*='search']",
            "input[name*='search']",
            "input[aria-label*='earch']", 
            "input[aria-label*='esquisa']"
        ]
        
        input_locator = None
        for sel in seletores:
            if page.locator(sel).count() > 0 and page.locator(sel).first.is_visible():
                input_locator = page.locator(sel).first
                break
                
        if not input_locator:
            input_locator = page.locator("input[type='text']").first

        input_locator.click(timeout=5000)
        page.wait_for_timeout(500)
        
        page.keyboard.type(query, delay=120)
        page.wait_for_timeout(800)
        page.keyboard.press("Enter")
        
        page.wait_for_timeout(5000)
        fechar_modais_iniciais(page)
        return True
    except Exception as e:
        log("busca", f"Erro ao tentar encontrar ou digitar na barra de pesquisa: {e}", nivel="ERRO")
        return False


def _coletar_links_scroll_infinito(page: Page, max_scrolls: int = 15) -> list[str]:
    script = r"""
    () => {
      const saida = new Set();
      for (const ancora of document.querySelectorAll('a[href]')) {
        const href = ancora.href || '';
        if (!href.includes('temu.com')) continue;
        
        const textoAncora = (ancora.innerText || '').toLowerCase();
        
        const lixo = [
            'capa', 'pelicula', 'tampão', 'tampao', 'suporte', 'cabo', 'carregador', 
            'cordão', 'cordao', 'pulseira', 'case', 'filtro', 'pó', 'po', 'pendente', 
            'pingente', 'flor', 'laço', 'laco', 'tampa', 'acessorio', 'telemóvel', 
            'telemovel', 'protetor', 'corrente', 'berloque'
        ];
        
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
        
        sucesso = _pesquisar_como_humano(pagina_busca, query)
        
        if not sucesso:
            log("falha", "A execução foi interrompida porque a pesquisa falhou.", nivel="ERRO")
            return
            
        log("busca", f"Iniciando recolha para a listagem gerada.")
        links = _coletar_links_scroll_infinito(pagina_busca)
        log("listagem", f"Encontrados {len(links)} anúncios válidos.")

        total_visitados = 0
        url_pesquisa_atual = pagina_busca.url
        
        for link in links:
            if limite > 0 and total_visitados >= limite:
                break
                
            log("acesso", f"A abrir o link: {link}")
            
            pagina_produto = contexto.new_page()
            _aplicar_camuflagem(pagina_produto)
            
            try:
                pagina_produto.goto(link, referer=url_pesquisa_atual, wait_until="domcontentloaded", timeout=45000)
                pagina_produto.wait_for_timeout(3000)
                
                try:
                    pagina_produto.mouse.wheel(0, 800)
                    pagina_produto.wait_for_timeout(1500)
                except Exception:
                    pass
                
                # --- PAUSA PARA INSPEÇÃO ---
                print("\n" + "="*60)
                print(f"🔗 LINK DO PRODUTO: {link}")
                print("👀 Olhe para a janela do Chrome de depuração agora!")
                input("Pressione ENTER após verificar a página para o robô extrair os dados... ")
                print("="*60 + "\n")
                # ---------------------------

                dados = extrair_produto_temu(pagina_produto)
                
                if not dados:
                    log("produto", "O extrator considerou o item esgotado ou bloqueado. A saltar...", nivel="AVISO")
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