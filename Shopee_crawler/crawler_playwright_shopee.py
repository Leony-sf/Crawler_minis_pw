from __future__ import annotations

from pathlib import Path
from typing import Any
import os
import re
from urllib.parse import urlsplit, parse_qsl, urlencode, urlunsplit
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

from .extracao_shopee import analisar_mini_celular, extrair_dados_html, validar_produto
from .utils import (
    construir_url_busca,
    criar_pasta_saida,
    encurtar_texto,
    linha,
    limpar_url,
    log,
    log_aviso,
    log_debug,
    log_erro,
    log_ok,
    normalizar_texto,
    pasta_print_por_status,
    salvar_comentarios,
    salvar_products,
    salvar_products_descartados_mini,
    salvar_products_suspeitos_mini,
    secao,
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


def _pausa(page, segundos: float, motivo: str = "") -> None:
    if motivo:
        log_debug("pausa", f"{segundos:.1f}s - {motivo}")

    page.wait_for_timeout(int(segundos * 1000))


def _abrir_contexto_chrome_persistente(p, headless: bool = False):
    """
    Abre Chrome normal com perfil persistente.

    Isso ajuda a Shopee porque:
    - mantém cookies;
    - mantém login;
    - reaproveita sessão;
    - evita abrir sempre um navegador zerado.
    """
    if headless:
        log_aviso(
            "navegador",
            "Headless não é recomendado para Shopee. Vou abrir com interface visual.",
        )

    headless_efetivo = False

    try:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PERFIL_CHROME_SHOPEE),
            channel="chrome",
            headless=headless_efetivo,
            no_viewport=True,
            locale="pt-BR",
            args=[
                "--start-maximized",
                "--disable-blink-features=AutomationControlled",
            ],
        )

        log_ok("navegador", f"Chrome persistente aberto em: {PERFIL_CHROME_SHOPEE}")
        return context

    except Exception as exc:
        log_aviso(
            "navegador",
            f"Não consegui abrir o Chrome normal pelo channel='chrome': {exc}",
        )
        log_aviso(
            "navegador",
            "Vou tentar abrir o Chromium do Playwright com perfil persistente.",
        )

        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PERFIL_CHROME_SHOPEE),
            headless=headless_efetivo,
            no_viewport=True,
            locale="pt-BR",
            args=[
                "--start-maximized",
                "--disable-blink-features=AutomationControlled",
            ],
        )

        return context


def _fechar_popups_se_existir(page) -> None:
    """
    Fecha apenas popups seguros.
    Evita clicar em OK genérico, porque isso estava bagunçando a navegação.
    """
    try:
        texto = page.locator("body").inner_text(timeout=3000)
        texto_norm = normalizar_texto(texto)
    except Exception:
        texto_norm = ""

    # Cookies
    if "cookies" in texto_norm or "usamos cookies" in texto_norm:
        candidatos_cookie = [
            "Aceitar todos os cookies",
            "Aceitar todos",
            "Aceitar",
        ]

        for texto_botao in candidatos_cookie:
            try:
                botao = page.get_by_text(texto_botao, exact=False).first

                if botao.count() > 0 and botao.is_visible(timeout=1500):
                    botao.click(timeout=2500, force=True)
                    page.wait_for_timeout(700)
                    log("popup", f"Cliquei em cookies: {texto_botao}")
                    return

            except Exception:
                pass

    # Botões reais de fechar modal
    seletores_fechar = [
        "button[aria-label='Close']",
        "button[aria-label='Fechar']",
        ".shopee-popup__close-btn",
        ".shopee-modal__close",
    ]

    for seletor in seletores_fechar:
        try:
            loc = page.locator(seletor).first

            if loc.count() > 0 and loc.is_visible(timeout=1500):
                loc.click(timeout=2500, force=True)
                page.wait_for_timeout(700)
                log("popup", f"Fechei popup com seletor: {seletor}")
                return

        except Exception:
            pass


def _selecionar_idioma_portugues_se_aparecer(page) -> None:
    """
    Clica em Português (BR) somente se a janela real de idioma aparecer.
    Não confunde com 'Português' no rodapé da página.
    """
    try:
        texto = page.locator("body").inner_text(timeout=3000)
        texto_norm = normalizar_texto(texto)

        if "selecione seu idioma" not in texto_norm:
            return

    except Exception:
        return

    candidatos = [
        "Português (BR)",
        "Portugues (BR)",
        "Português",
        "Portugues",
    ]

    for texto in candidatos:
        try:
            loc = page.get_by_text(texto, exact=True).first

            if loc.count() > 0 and loc.is_visible(timeout=2000):
                loc.click(timeout=4000, force=True)
                page.wait_for_timeout(1500)
                log_ok("idioma", f"Cliquei em: {texto}")
                return

        except Exception:
            pass

    log_aviso("idioma", "Janela de idioma apareceu, mas não consegui clicar em Português (BR).")


def _esta_logado_shopee(page) -> bool:
    try:
        texto = page.locator("body").inner_text(timeout=5000)
        texto_norm = normalizar_texto(texto)

        sinais_logado = [
            "minha conta",
            "meus pedidos",
            "notificacoes",
            "notificações",
            "sair",
            "minhas compras",
        ]

        return any(sinal in texto_norm for sinal in sinais_logado)

    except Exception:
        return False


def _precisa_intervencao_manual(page) -> bool:
    """
    Detecta situações que precisam de ação manual:
    login, captcha, SMS, 2FA, idioma ou verificação.
    """
    try:
        url_atual = (page.url or "").lower()
        texto = page.locator("body").inner_text(timeout=4000)
        texto_norm = normalizar_texto(texto)

        sinais = [
            "captcha",
            "verificacao",
            "verificação",
            "nao sou um robo",
            "não sou um robô",
            "atividade suspeita",
            "suspicious activity",
            "security check",
            "codigo de verificacao",
            "código de verificação",
            "sms",
            "selecione seu idioma",
        ]

        return (
            "captcha" in url_atual
            or "verify" in url_atual
            or "buyer/login" in url_atual
            or any(sinal in texto_norm for sinal in sinais)
        )

    except Exception:
        return False


def _salvar_estado_sessao_debug(page) -> None:
    if os.getenv(SALVAR_SESSAO_DEBUG_ENV, "").strip().lower() not in {"1", "true", "sim", "yes"}:
        log_debug(
            "sessao",
            f"Estado debug nao salvo. Defina {SALVAR_SESSAO_DEBUG_ENV}=1 para habilitar.",
        )
        return

    estado_path = RAIZ_PROJETO / "shopee_state_debug.json"

    try:
        page.context.storage_state(path=str(estado_path))
        log_ok("sessao", f"Estado da sessao salvo em {estado_path}")
    except Exception as exc:
        log_aviso("sessao", f"Nao consegui salvar estado debug da sessao: {exc}")


def _pausar_intervencao_manual(page, etapa: str = "") -> None:
    print()
    print("=" * 70)
    print("INTERVENÇÃO MANUAL NECESSÁRIA")
    print("=" * 70)
    print(f"A Shopee precisa de ação manual {etapa}.")
    print("Faça no navegador aberto:")
    print("1. Escolha Português (BR), se aparecer.")
    print("2. Faça login, se necessário.")
    print("3. Resolva CAPTCHA, SMS ou confirmação, se aparecer.")
    print("4. Quando a página estiver liberada, volte aqui e aperte ENTER.")
    input("Pressione ENTER para continuar o crawler... ")

    _salvar_estado_sessao_debug(page)


def _garantir_sessao_shopee(page, url_busca: str, login_manual: bool = False) -> None:
    """
    Fluxo seguro para Shopee:
    - escolhe idioma;
    - fecha popups;
    - se login_manual=True, abre login e pausa;
    - se detectar bloqueio/login/verificação, pausa;
    - volta para a busca depois.
    """
    _selecionar_idioma_portugues_se_aparecer(page)
    _fechar_popups_se_existir(page)

    if login_manual and not _esta_logado_shopee(page):
        log("login", "Modo login manual ativado. Abrindo tela de login da Shopee...")

        try:
            page.goto(LOGIN_SHOPEE_URL, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(4000)
        except Exception as exc:
            log_aviso("login", f"Falha ao abrir tela de login: {exc}")

        _selecionar_idioma_portugues_se_aparecer(page)
        _fechar_popups_se_existir(page)
        _pausar_intervencao_manual(page, etapa="no login manual")

    else:
        if _precisa_intervencao_manual(page):
            _selecionar_idioma_portugues_se_aparecer(page)
            _fechar_popups_se_existir(page)
            _pausar_intervencao_manual(page, etapa="na página atual")

    try:
        page.goto(url_busca, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4000)
        _selecionar_idioma_portugues_se_aparecer(page)
        _fechar_popups_se_existir(page)
    except Exception as exc:
        log_aviso("busca", f"Não consegui voltar para a busca após sessão/login: {exc}")


def _rolar_para_carregar(page, vezes: int = 3, pausa_ms: int = 1200) -> None:
    for _ in range(vezes):
        page.mouse.wheel(0, 1200)
        page.wait_for_timeout(pausa_ms)


def _clicar_ver_mais_se_existir(page) -> None:
    """
    Expande descrição/detalhes do produto.
    Evita clicar em botão genérico 'Mais', pois pode abrir coisa errada.
    """
    candidatos = [
        "Ver mais",
        "Mostrar mais",
        "Ler mais",
        "Ver tudo",
        "Ver Tudo",
    ]

    for texto in candidatos:
        try:
            botao = page.get_by_text(texto, exact=True).first

            if botao.count() > 0 and botao.is_visible(timeout=1500):
                botao.click(timeout=2000, force=True)
                page.wait_for_timeout(800)
                log("produto", f"Cliquei em: {texto}")
                return

        except Exception:
            pass


def _rolar_para_detalhes_produto(page) -> str:
    """
    Desce até Detalhes/Especificações/Descrição da Shopee.

    A Shopee costuma carregar a ficha técnica e descrição depois do scroll.
    O retorno é o texto visível da página, usado na extração junto com o HTML.
    """
    log("produto", "Buscando detalhes/especificações do produto...")

    textos_alvo = [
        "Detalhes do produto",
        "Especificações do produto",
        "Informações do produto",
        "Descrição do produto",
        "Marca",
        "Modelo",
        "ANATEL",
        "Anatel",
        "Homologação",
    ]

    for texto in textos_alvo:
        try:
            loc = page.get_by_text(texto, exact=False).first

            if loc.count() > 0 and loc.is_visible(timeout=2000):
                loc.scroll_into_view_if_needed(timeout=3500)
                page.wait_for_timeout(1200)
                _clicar_ver_mais_se_existir(page)
                break

        except Exception:
            pass

    ultimo_texto = ""

    for tentativa in range(1, 12):
        try:
            ultimo_texto = page.locator("body").inner_text(timeout=6000)
            texto_norm = normalizar_texto(ultimo_texto)

            achou_detalhes = (
                "detalhes do produto" in texto_norm
                or "especificacoes do produto" in texto_norm
                or "especificações do produto" in texto_norm
                or "informacoes do produto" in texto_norm
                or "informações do produto" in texto_norm
                or "descricao do produto" in texto_norm
                or "descrição do produto" in texto_norm
                or "anatel" in texto_norm
                or "homologacao" in texto_norm
                or "homologação" in texto_norm
            )

            if achou_detalhes:
                log("produto", f"Detalhes encontrados na tentativa {tentativa}.")
                _clicar_ver_mais_se_existir(page)
                return ultimo_texto

        except Exception:
            pass

        page.mouse.wheel(0, 900)
        page.wait_for_timeout(900)
        _clicar_ver_mais_se_existir(page)

    log_aviso("produto", "Não confirmei a área de detalhes, vou extrair com o texto disponível.")

    try:
        return page.locator("body").inner_text(timeout=6000)
    except Exception:
        return ultimo_texto


def _texto_parece_produto_alvo(texto: str, query: str = "", mini_celulares: bool = False) -> bool:
    """
    Filtra cards da Shopee.

    No modo normal, mantém comportamento focado em celular/smartphone.
    No modo mini, aceita também termos de marcas/modelos e disfarces
    que podem aparecer em anúncios escondidos.
    """
    texto_norm = normalizar_texto(texto)
    query_norm = normalizar_texto(query)

    if not texto_norm:
        return False

    termos_fora_escopo = [
        "cordao",
        "cordão",
        "colar",
        "prata",
        "ouro",
        "roupa",
        "feminina",
        "feminino",
        "masculina",
        "masculino",
        "kit roupa",
        "vestido",
        "short",
        "camisa",
        "blusa",
        "brinco",
        "anel",
        "pulseira",
    ]

    acessorios_fortes = [
        "capinha",
        "capa para",
        "pelicula",
        "película",
        "carregador",
        "cabo usb",
        "fone de ouvido",
        "suporte",
        "case para",
        "display para",
        "tela para",
        "bateria para",
    ]

    if any(t in texto_norm for t in termos_fora_escopo):
        return False

    if any(t in texto_norm for t in acessorios_fortes):
        return False

    if mini_celulares:
        termos_mini = [
            "mini celular",
            "micro celular",
            "mini phone",
            "micro phone",
            "bluetooth dialer",
            "dialer gsm",
            "card phone",
            "key phone",
            "keyring phone",
            "celular chaveiro",
            "telefone chaveiro",
            "celular cartao",
            "celular cartão",
            "telefone cartao",
            "telefone cartão",
            "celular batom",
            "telefone batom",
            "celular caneta",
            "pen phone",
            "bm10",
            "bm20",
            "bm30",
            "bm70",
            "bt11",
            "j8",
            "j9",
            "long-cz",
            "l8star",
            "l8 star",
            "gtstar",
            "gt star",
            "zanco",
            "servo",
            "anica",
            "aizku",
            "kechaoda",
            "soyes",
            "melrose",
        ]

        termos_tecnicos_fracos = [
            "chip",
            "gsm",
            "sim",
            "dual sim",
            "2 chips",
        ]

        if any(t in texto_norm for t in termos_mini):
            return True

        # Não aceite "chip" ou "gsm" sozinhos no card, pois isso puxa muito ruído.
        # Eles só ajudam quando o card também tem indício de mini/telefone/formato.
        if any(t in texto_norm for t in termos_tecnicos_fracos) and any(
            t in texto_norm for t in ["mini", "celular", "telefone", "phone", "dialer", "card", "key", "chaveiro", "cartao", "cartão"]
        ):
            return True

        tokens_fracos = {"chip", "gsm", "sim", "dual"}
        termos_query = [t for t in query_norm.split() if len(t) >= 3 and t not in tokens_fracos]
        if termos_query and any(t in texto_norm for t in termos_query):
            return True

        return False

    termos_celular = [
        "celular",
        "smartphone",
        "telefone",
        "iphone",
        "samsung",
        "galaxy",
        "xiaomi",
        "redmi",
        "poco",
        "motorola",
        "moto g",
        "realme",
        "infinix",
        "oppo",
        "asus",
        "zenfone",
    ]

    acessorios = [
        "capinha",
        "capa",
        "pelicula",
        "película",
        "carregador",
        "cabo usb",
        "fone",
        "suporte",
        "case",
    ]

    if "celular" in query_norm or "smartphone" in query_norm:
        if any(t in texto_norm for t in acessorios):
            return False

        return any(t in texto_norm for t in termos_celular)

    termos_query = [t for t in query_norm.split() if len(t) >= 3]

    if termos_query:
        return any(t in texto_norm for t in termos_query)

    return True

def _texto_card_do_link(link_locator) -> str:
    """
    Tenta pegar o texto do card inteiro do produto, não só do <a>.
    Isso ajuda a saber se o link é realmente de celular.
    """
    try:
        return link_locator.evaluate(
            """
            el => {
                const card =
                    el.closest("[data-sqe='item']") ||
                    el.closest(".shopee-search-item-result__item") ||
                    el.closest("li") ||
                    el.closest("div");

                return card ? card.innerText : el.innerText;
            }
            """
        ) or ""
    except Exception:
        try:
            return link_locator.inner_text(timeout=1000)
        except Exception:
            return ""


def _coletar_links_produtos(page, limite: int, query: str = "", mini_celulares: bool = False) -> list[str]:
    links: list[str] = []
    ignorados = 0

    for seletor in LINK_PRODUTO_SELECTORS:
        try:
            loc = page.locator(seletor)
            total = loc.count()

            log_debug("seletor", f"{seletor} encontrou {total} links.")

            for i in range(total):
                link_loc = loc.nth(i)

                href = link_loc.get_attribute("href") or ""
                href = limpar_url(href)

                if not href:
                    continue

                if "shopee.com.br" not in href:
                    continue

                eh_produto = "-i." in href or "/product/" in href

                if not eh_produto:
                    continue

                texto_card = _texto_card_do_link(link_loc)

                if not _texto_parece_produto_alvo(texto_card, query=query, mini_celulares=mini_celulares):
                    ignorados += 1
                    continue

                if href not in links:
                    links.append(href)

                if len(links) >= limite:
                    if ignorados:
                        log("busca", f"Links fora do escopo ignorados: {ignorados}")
                    return links

        except Exception as exc:
            log("playwright", f"Falha ao coletar com seletor {seletor}: {exc}")

    if ignorados:
        log("busca", f"Links fora do escopo ignorados: {ignorados}")

    return links[:limite]


def _salvar_print(page, pasta_saida: Path, idx: int, status_validacao: str) -> str:
    pasta_print = pasta_print_por_status(pasta_saida, status_validacao)
    print_path = pasta_print / f"produto_{idx:03d}.png"

    try:
        page.screenshot(path=str(print_path), full_page=True)
        return str(print_path)
    except Exception as exc:
        log("playwright", f"Não consegui salvar print do produto {idx}: {exc}")
        return ""


def _limpar_comentario(texto: str) -> str:
    texto = " ".join(str(texto or "").split())
    return texto.strip()


def _linha_parece_comentario_real(linha: str) -> bool:
    linha = _limpar_comentario(linha)
    linha_norm = normalizar_texto(linha)

    if len(linha) < 5:
        return False

    if len(linha) > 500:
        return False

    padroes_invalidos = [
        r"^\d(?:\.\d)?\s+de\s+5",
        r"^todos\s+estrela",
        r"^\d\s+estrela",
        r"^com\s+comentarios",
        r"^com\s+comentários",
        r"^com\s+midia",
        r"^com\s+mídia",
        r"^reportar\s+comentario",
        r"^reportar\s+comentário",
        r"^\d+$",
        r"^\d+\s*$",
    ]

    for padrao in padroes_invalidos:
        if re.search(padrao, linha_norm):
            return False

    termos_invalidos = [
        "todos estrela",
        "com comentarios",
        "com comentários",
        "com midia",
        "com mídia",
        "reportar comentario",
        "reportar comentário",
        "classificacao do produto",
        "classificação do produto",
        "avaliações do produto",
        "avaliacoes do produto",
        "denunciar",
        "curtir",
        "útil",
        "util",
        "variação:",
        "variacao:",
        "qualidade do produto:",
        "parecido com anúncio:",
        "parecido com anuncio:",
        "comprar agora",
        "adicionar ao carrinho",
        "frete",
        "cookies",
        "política",
        "politica",
    ]

    if any(t in linha_norm for t in termos_invalidos):
        return False

    # Evita pegar data pura.
    if re.match(r"^\d{4}-\d{2}-\d{2}", linha_norm):
        return False

    # Precisa ter pelo menos alguma letra.
    if not re.search(r"[a-zA-ZÀ-ÿ]", linha):
        return False

    return True


def _comentario_parece_valido(texto: str) -> bool:
    texto = _limpar_comentario(texto)
    texto_norm = normalizar_texto(texto)

    if len(texto) < 5:
        return False

    if len(texto) > 800:
        return False

    invalidos = [
        "todos estrela",
        "com comentarios",
        "com comentários",
        "com midia",
        "com mídia",
        "reportar comentario",
        "reportar comentário",
        "classificacao do produto",
        "classificação do produto",
        "avaliações do produto",
        "avaliacoes do produto",
    ]

    if any(t in texto_norm for t in invalidos):
        return False

    return True


def _extrair_total_comentarios_do_texto(texto: str, fallback: int = 0) -> int:
    texto_norm = normalizar_texto(texto)

    padroes = [
        r"com\s+comentarios\s*\((\d[\d\.]*)\)",
        r"com\s+comentários\s*\((\d[\d\.]*)\)",
        r"(\d[\d\.]*)\s+comentarios",
        r"(\d[\d\.]*)\s+comentario",
        r"(\d[\d\.]*)\s+avaliações",
        r"(\d[\d\.]*)\s+avaliacoes",
        r"(\d[\d\.]*)\s+avaliação",
        r"(\d[\d\.]*)\s+avaliacao",
    ]

    for padrao in padroes:
        m = re.search(padrao, texto_norm)

        if m:
            try:
                return int(m.group(1).replace(".", ""))
            except Exception:
                pass

    return fallback


def _rolar_para_avaliacoes_produto(page) -> None:
    textos_alvo = [
        "Avaliações do Produto",
        "Avaliações",
        "Comentários",
        "Comentários do Produto",
        "Classificação do Produto",
        "Reviews",
    ]

    for texto in textos_alvo:
        try:
            loc = page.get_by_text(texto, exact=False).first

            if loc.count() > 0 and loc.is_visible(timeout=1500):
                loc.scroll_into_view_if_needed(timeout=3000)
                page.wait_for_timeout(1200)
                return

        except Exception:
            pass

    for _ in range(7):
        page.mouse.wheel(0, 1200)
        page.wait_for_timeout(700)


def _clicar_filtro_com_comentarios(page) -> None:
    """
    A Shopee geralmente mostra avaliações sem texto no filtro 'Todos'.
    Este clique força o filtro 'Com Comentários', quando disponível.
    """
    candidatos = [
        "Com Comentários",
        "Com Comentarios",
    ]

    for texto in candidatos:
        try:
            filtro = page.get_by_text(texto, exact=False).first

            if filtro.count() > 0 and filtro.is_visible(timeout=2000):
                filtro.scroll_into_view_if_needed(timeout=3000)
                page.wait_for_timeout(500)
                filtro.click(timeout=3000, force=True)
                page.wait_for_timeout(2500)
                log("comentarios", f"Cliquei no filtro: {texto}")
                return

        except Exception:
            pass


def _extrair_comentarios_por_js(page) -> list[str]:
    """
    Extrai textos visíveis da área de avaliações usando JS.
    Isso ajuda quando as classes da Shopee mudam/ficam obfuscadas.
    """
    try:
        textos = page.evaluate(
            """
            () => {
                const roots = Array.from(document.querySelectorAll(
                    '.product-ratings, .product-ratings__list, .shopee-product-rating-list, [class*="rating"], [class*="review"]'
                ));

                let root = roots.find(el => {
                    const txt = (el.innerText || '').toLowerCase();
                    return txt.includes('estrela') || txt.includes('avalia') || txt.includes('coment');
                }) || document.body;

                const cards = Array.from(root.querySelectorAll(
                    '.shopee-product-rating, [class*="product-rating"], [class*="ProductRating"], [class*="review"], [class*="Review"]'
                ));

                const saida = [];

                for (const card of cards) {
                    const rect = card.getBoundingClientRect();
                    const style = window.getComputedStyle(card);

                    if (
                        style.display === 'none' ||
                        style.visibility === 'hidden' ||
                        rect.width <= 0 ||
                        rect.height <= 0
                    ) {
                        continue;
                    }

                    let txt = (card.innerText || '').trim();

                    if (txt) {
                        saida.push(txt);
                    }
                }

                if (saida.length > 0) {
                    return saida;
                }

                const nodes = Array.from(root.querySelectorAll('div, span, p'));

                for (const node of nodes) {
                    const rect = node.getBoundingClientRect();
                    const style = window.getComputedStyle(node);

                    if (
                        style.display === 'none' ||
                        style.visibility === 'hidden' ||
                        rect.width <= 0 ||
                        rect.height <= 0
                    ) {
                        continue;
                    }

                    const txt = (node.innerText || '').trim();

                    if (txt) {
                        saida.push(txt);
                    }
                }

                return saida;
            }
            """
        )

        if isinstance(textos, list):
            return [str(t) for t in textos if str(t).strip()]

    except Exception:
        pass

    return []


def _extrair_comentarios_de_bloco(texto_bloco: str) -> list[str]:
    """
    Recebe o texto inteiro de um card/bloco de avaliação e tenta separar
    somente as linhas que parecem comentário real.
    """
    texto_bloco = str(texto_bloco or "")
    linhas = [l.strip() for l in texto_bloco.splitlines() if l.strip()]

    candidatos: list[str] = []

    for linha in linhas:
        linha = _limpar_comentario(linha)

        if _linha_parece_comentario_real(linha):
            candidatos.append(linha)

    # Às vezes o comentário vem como várias linhas curtas.
    # Junta linhas próximas, mas evita juntar blocos de filtro.
    if not candidatos:
        texto_limpo = _limpar_comentario(texto_bloco)

        if _comentario_parece_valido(texto_limpo):
            return [texto_limpo]

    return candidatos


def _coletar_comentarios_visiveis(page, limite: int = 10) -> list[str]:
    comentarios: list[str] = []

    blocos = _extrair_comentarios_por_js(page)

    for bloco in blocos:
        candidatos = _extrair_comentarios_de_bloco(bloco)

        for comentario in candidatos:
            comentario = _limpar_comentario(comentario)

            if not _comentario_parece_valido(comentario):
                continue

            comentario_norm = normalizar_texto(comentario)

            if any(comentario_norm == normalizar_texto(c) for c in comentarios):
                continue

            comentarios.append(comentario)

            if len(comentarios) >= limite:
                return comentarios

    return comentarios[:limite]


def _clicar_proxima_pagina_avaliacoes(page) -> bool:
    try:
        page.mouse.wheel(0, 1600)
        page.wait_for_timeout(800)
    except Exception:
        pass

    seletores_proxima = [
        ".product-ratings__page-controller button.shopee-icon-button--right",
        ".product-ratings__page-controller .shopee-icon-button--right",
        ".product-ratings .shopee-page-controller button.shopee-icon-button--right",
        ".product-ratings .shopee-page-controller .shopee-icon-button--right",
        ".shopee-product-rating-list .shopee-page-controller button.shopee-icon-button--right",
        ".shopee-product-rating-list .shopee-page-controller .shopee-icon-button--right",
        ".shopee-page-controller button.shopee-icon-button--right",
        ".shopee-page-controller .shopee-icon-button--right",
        "button.shopee-icon-button--right",
        ".shopee-icon-button--right",
    ]

    for seletor in seletores_proxima:
        try:
            loc = page.locator(seletor)
            total = loc.count()

            for i in range(total):
                botao = loc.nth(i)

                try:
                    if not botao.is_visible(timeout=1000):
                        continue
                except Exception:
                    continue

                classe = ""
                aria_disabled = ""
                disabled_attr = ""

                try:
                    classe = botao.get_attribute("class") or ""
                except Exception:
                    pass

                try:
                    aria_disabled = botao.get_attribute("aria-disabled") or ""
                except Exception:
                    pass

                try:
                    disabled_attr = botao.get_attribute("disabled") or ""
                except Exception:
                    pass

                classe_norm = normalizar_texto(classe)

                if (
                    "disabled" in classe_norm
                    or aria_disabled.lower() == "true"
                    or disabled_attr
                ):
                    continue

                try:
                    botao.scroll_into_view_if_needed(timeout=2000)
                except Exception:
                    pass

                botao.click(timeout=3000, force=True)
                page.wait_for_timeout(2500)
                log("comentarios", f"Cliquei na próxima página de avaliações com seletor: {seletor}")
                return True

        except Exception:
            pass

    return False


def _capturar_comentarios_produto(
    page,
    idx: int,
    link: str,
    titulo: str,
    limite: int = 10,
) -> list[dict[str, Any]]:
    comentarios: list[str] = []

    try:
        _rolar_para_avaliacoes_produto(page)
        _clicar_filtro_com_comentarios(page)

        for rodada in range(1, 8):
            encontrados = _coletar_comentarios_visiveis(page, limite=limite)

            novos_na_rodada = 0

            for comentario in encontrados:
                comentario_norm = normalizar_texto(comentario)

                if not any(comentario_norm == normalizar_texto(c) for c in comentarios):
                    comentarios.append(comentario)
                    novos_na_rodada += 1

                if len(comentarios) >= limite:
                    break

            log(
                "comentarios",
                f"Produto {idx}: rodada {rodada} | novos={novos_na_rodada} | acumulados={len(comentarios)}",
            )

            if len(comentarios) >= limite:
                break

            clicou_proxima = _clicar_proxima_pagina_avaliacoes(page)

            if not clicou_proxima:
                break

        try:
            texto_body = page.locator("body").inner_text(timeout=6000)
        except Exception:
            texto_body = ""

        total_detectado = _extrair_total_comentarios_do_texto(
            texto_body,
            fallback=len(comentarios),
        )

        capturados = comentarios[:limite]

        log(
            "comentarios",
            f"Produto {idx}: total detectado={total_detectado} | capturados={len(capturados)}",
        )

        linhas = []

        for pos, comentario in enumerate(capturados, start=1):
            linhas.append(
                {
                    "engine": "playwright",
                    "indice_produto": idx,
                    "url": link,
                    "titulo": titulo,
                    "comentarios_total_detectado": total_detectado,
                    "comentarios_capturados": len(capturados),
                    "comentario_indice": pos,
                    "comentario": comentario,
                    "erro": "",
                }
            )

        if not linhas:
            linhas.append(
                {
                    "engine": "playwright",
                    "indice_produto": idx,
                    "url": link,
                    "titulo": titulo,
                    "comentarios_total_detectado": total_detectado,
                    "comentarios_capturados": 0,
                    "comentario_indice": 0,
                    "comentario": "",
                    "erro": "",
                }
            )

        return linhas

    except Exception as exc:
        log("comentarios", f"Falha ao capturar comentários do produto {idx}: {exc}")

        return [
            {
                "engine": "playwright",
                "indice_produto": idx,
                "url": link,
                "titulo": titulo,
                "comentarios_total_detectado": 0,
                "comentarios_capturados": 0,
                "comentario_indice": 0,
                "comentario": "",
                "erro": str(exc),
            }
        ]
    
def _montar_url_busca_paginada(url_busca: str, pagina: int) -> str:
    """
    Monta URL paginada da Shopee.

    Na Shopee, normalmente:
    - primeira página: sem page ou page=0
    - segunda página: page=1
    - terceira página: page=2
    """
    if pagina <= 1:
        return url_busca

    partes = urlsplit(url_busca)
    query_params = dict(parse_qsl(partes.query, keep_blank_values=True))

    query_params["page"] = str(pagina - 1)

    nova_query = urlencode(query_params, doseq=True)

    return urlunsplit(
        (
            partes.scheme,
            partes.netloc,
            partes.path,
            nova_query,
            partes.fragment,
        )
    )

def _clicar_proxima_pagina_busca(page, pagina_atual: int) -> bool:
    """
    Clica na seta de próxima página da busca Shopee.
    Usado no rodapé da listagem, onde aparecem 1, 2, 3, 4, 5, ... >.
    """
    log("busca", f"Tentando avançar da página {pagina_atual} para a próxima pela seta...")

    try:
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1500)
    except Exception:
        pass

    seletores_proxima = [
        ".shopee-page-controller button.shopee-icon-button--right",
        ".shopee-page-controller .shopee-icon-button--right",
        "button.shopee-icon-button--right",
        ".shopee-icon-button--right",
        "button[aria-label*='Next']",
        "button[aria-label*='Próxima']",
        "button[aria-label*='Proxima']",
    ]

    for seletor in seletores_proxima:
        try:
            botoes = page.locator(seletor)
            total = botoes.count()

            # Usa o último botão visível, pois a Shopee pode ter setas/carrosséis na página.
            for i in range(total - 1, -1, -1):
                botao = botoes.nth(i)

                try:
                    if not botao.is_visible(timeout=1000):
                        continue
                except Exception:
                    continue

                classe = ""
                disabled_attr = ""
                aria_disabled = ""

                try:
                    classe = botao.get_attribute("class") or ""
                except Exception:
                    pass

                try:
                    disabled_attr = botao.get_attribute("disabled") or ""
                except Exception:
                    pass

                try:
                    aria_disabled = botao.get_attribute("aria-disabled") or ""
                except Exception:
                    pass

                classe_norm = normalizar_texto(classe)

                if (
                    "disabled" in classe_norm
                    or disabled_attr
                    or aria_disabled.lower() == "true"
                ):
                    continue

                botao.scroll_into_view_if_needed(timeout=3000)
                page.wait_for_timeout(500)

                url_antes = page.url

                botao.click(timeout=5000, force=True)
                page.wait_for_timeout(4000)

                try:
                    page.wait_for_load_state("networkidle", timeout=10000)
                except Exception:
                    pass

                url_depois = page.url

                log_ok(
                    "busca",
                    f"Avancei pela seta. URL antes: {url_antes} | URL depois: {url_depois}",
                )
                return True

        except Exception:
            pass

    # Fallback por JS: tenta clicar no último botão de seta direita visível.
    try:
        clicou = page.evaluate(
            """
            () => {
                const candidatos = Array.from(document.querySelectorAll(
                    '.shopee-page-controller button.shopee-icon-button--right, button.shopee-icon-button--right, .shopee-icon-button--right'
                ));

                const visiveis = candidatos.filter(el => {
                    const rect = el.getBoundingClientRect();
                    const style = window.getComputedStyle(el);
                    const cls = (el.className || '').toString().toLowerCase();

                    return (
                        rect.width > 0 &&
                        rect.height > 0 &&
                        style.display !== 'none' &&
                        style.visibility !== 'hidden' &&
                        !el.disabled &&
                        el.getAttribute('aria-disabled') !== 'true' &&
                        !cls.includes('disabled')
                    );
                });

                if (!visiveis.length) return false;

                visiveis[visiveis.length - 1].click();
                return true;
            }
            """
        )

        if clicou:
            page.wait_for_timeout(5000)

            try:
                page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass

            log_ok("busca", "Avancei para a próxima página usando fallback JS.")
            return True

    except Exception:
        pass

    log_aviso("busca", "Não consegui clicar na seta de próxima página.")
    return False



def rodar_playwright_shopee(
    query: str,
    limite: int,
    base_anatel=None,
    headless: bool = False,
    url: str | None = None,
    login_manual: bool = False,
    max_paginas: int = 3,
    queries: list[str] | None = None,
    mini_celulares: bool = False,
    mini_maior_cm: float = 12.0,
    mini_largura_cm: float = 5.5,
    mini_manter_sem_medida: bool = False,
) -> dict[str, Any]:
    pasta_saida = criar_pasta_saida("playwright")
    produtos_resultados: list[dict[str, Any]] = []
    comentarios_resultados: list[dict[str, Any]] = []
    descartados_mini: list[dict[str, Any]] = []
    suspeitos_mini: list[dict[str, Any]] = []

    def salvar_parcial() -> None:
        salvar_products(pasta_saida, produtos_resultados)
        salvar_comentarios(pasta_saida, comentarios_resultados)
        if mini_celulares:
            salvar_products_descartados_mini(pasta_saida, descartados_mini)
            salvar_products_suspeitos_mini(pasta_saida, suspeitos_mini)

    # Cria os arquivos vazios logo no início.
    salvar_parcial()

    queries_execucao = [q.strip() for q in (queries or []) if str(q or "").strip()]
    if not queries_execucao:
        queries_execucao = [query]

    if url:
        # URL direta deve ser usada apenas uma vez. O termo serve apenas para logs/filtro.
        queries_execucao = [query]

    urls_processadas: set[str] = set()
    total_processados = 0

    secao("Busca Shopee")
    log("busca", f"Buscas na fila: {len(queries_execucao)}")
    log("busca", f"Limite total de produtos: {limite}")
    log("busca", f"Máximo de páginas por busca: {max_paginas}")

    if mini_celulares:
        log("mini", "Modo mini celulares ativado.")
        log("mini", f"Limite dimensional: maior eixo <= {mini_maior_cm} cm e largura <= {mini_largura_cm} cm")
        log("mini", f"Sem medida explícita: suspeito manual em prints/irregulares")

    with sync_playwright() as p:
        context = _abrir_contexto_chrome_persistente(p, headless=headless)
        page = context.pages[0] if context.pages else context.new_page()

        try:
            for indice_query, termo_busca in enumerate(queries_execucao, start=1):
                if total_processados >= limite:
                    log_ok("busca", f"Limite total atingido: {total_processados}/{limite}.")
                    break

                url_busca = url or construir_url_busca(termo_busca)

                secao(f"Busca {indice_query}/{len(queries_execucao)}")
                log("busca", f"Termo: {termo_busca}")
                log("busca", f"URL base: {url_busca}")

                for pagina_atual in range(1, max_paginas + 1):
                    if total_processados >= limite:
                        log_ok(
                            "busca",
                            f"Limite total atingido: {total_processados}/{limite}.",
                        )
                        break

                    secao(f"Página Shopee {pagina_atual}/{max_paginas} | Busca {indice_query}/{len(queries_execucao)}")

                    if pagina_atual == 1:
                        url_pagina = url_busca
                        log("busca", f"Abrindo página inicial: {url_pagina}")

                        try:
                            page.goto(url_pagina, wait_until="domcontentloaded", timeout=60000)
                            _pausa(page, 6, f"após abrir página {pagina_atual}")
                        except Exception as exc:
                            log_aviso("busca", f"Falha ao abrir página {pagina_atual}: {exc}")
                            continue

                    else:
                        clicou_proxima = _clicar_proxima_pagina_busca(page, pagina_atual - 1)

                        if not clicou_proxima:
                            url_fallback = _montar_url_busca_paginada(url_busca, pagina_atual)
                            log_aviso(
                                "busca",
                                f"Nao consegui avancar pela seta. Tentando URL paginada: {url_fallback}",
                            )

                            try:
                                page.goto(url_fallback, wait_until="domcontentloaded", timeout=60000)
                                _pausa(page, 6, f"apos abrir pagina {pagina_atual} por URL")
                            except Exception as exc:
                                log_aviso(
                                    "busca",
                                    f"Nao consegui avancar para a pagina {pagina_atual}: {exc}",
                                )
                                break

                        url_pagina = page.url
                        _pausa(page, 5, f"após avançar para página {pagina_atual}")

                    _garantir_sessao_shopee(
                        page,
                        url_busca=url_pagina,
                        login_manual=login_manual if (pagina_atual == 1 and indice_query == 1) else False,
                    )

                    _rolar_para_carregar(page, vezes=6, pausa_ms=1300)
                    _fechar_popups_se_existir(page)
                    _selecionar_idioma_portugues_se_aparecer(page)

                    restante = max(limite - total_processados, 0)

                    links = _coletar_links_produtos(
                        page,
                        limite=restante,
                        query=termo_busca,
                        mini_celulares=mini_celulares,
                    )

                    if len(links) < restante:
                        log_aviso(
                            "busca",
                            "Poucos links encontrados. Vou tentar rolar mais a página.",
                        )

                        _rolar_para_carregar(page, vezes=6, pausa_ms=1000)
                        _fechar_popups_se_existir(page)
                        _selecionar_idioma_portugues_se_aparecer(page)

                        links = _coletar_links_produtos(
                            page,
                            limite=restante,
                            query=termo_busca,
                            mini_celulares=mini_celulares,
                        )

                    links_novos = []

                    for link in links:
                        if link not in urls_processadas:
                            links_novos.append(link)

                    log(
                        "playwright",
                        f"Busca '{termo_busca}' | página {pagina_atual}: links coletados={len(links)} | novos={len(links_novos)}",
                    )

                    if not links_novos:
                        log_aviso(
                            "busca",
                            f"Nenhum link novo encontrado na página {pagina_atual} para '{termo_busca}'.",
                        )

                        if pagina_atual == 1 and not produtos_resultados and not descartados_mini:
                            item = {
                                "engine": "playwright",
                                "indice": 0,
                                "url": url_pagina,
                                "titulo": "",
                                "preco": "",
                                "marca": "",
                                "modelo": "",
                                "versao": "",
                                "fabricante": "",
                                "codigo_anatel_principal": "",
                                "status_validacao": "IRREGULAR",
                                "motivo_validacao": (
                                    "Nenhum produto foi coletado na busca da Shopee. "
                                    "Possível bloqueio, carregamento incompleto ou mudança nos seletores."
                                ),
                                "fabricante_base": "",
                                "marca_base": "",
                                "modelo_base": "",
                                "versao_base": "",
                                "query_origem": termo_busca,
                                "pagina_origem": pagina_atual,
                                "erro": "SEM_LINKS",
                            }

                            item["print_path"] = _salvar_print(page, pasta_saida, 0, "IRREGULAR")
                            produtos_resultados.append(item)
                            salvar_parcial()

                        break

                    for link in links_novos:
                        if total_processados >= limite:
                            break

                        urls_processadas.add(link)
                        total_processados += 1
                        idx = total_processados

                        _pausa(page, 3, f"antes de abrir o produto {idx}")

                        linha(f"Produto {idx}/{limite} | Busca {indice_query}/{len(queries_execucao)} | Página {pagina_atual}")
                        log("produto", f"Abrindo anúncio: {encurtar_texto(link, 120)}")

                        produto_page = context.new_page()

                        item: dict[str, Any] = {
                            "engine": "playwright",
                            "indice": idx,
                            "url": link,
                            "query_origem": termo_busca,
                            "pagina_origem": pagina_atual,
                            "erro": "",
                        }

                        try:
                            produto_page.goto(link, wait_until="domcontentloaded", timeout=60000)

                            _pausa(produto_page, 6, f"após abrir o produto {idx}")
                            _fechar_popups_se_existir(produto_page)
                            _selecionar_idioma_portugues_se_aparecer(produto_page)

                            if _precisa_intervencao_manual(produto_page):
                                _pausar_intervencao_manual(
                                    produto_page,
                                    etapa=f"no produto {idx}",
                                )

                                try:
                                    produto_page.goto(link, wait_until="domcontentloaded", timeout=60000)
                                    produto_page.wait_for_timeout(3000)
                                except Exception:
                                    pass

                            texto_visivel = _rolar_para_detalhes_produto(produto_page)
                            html = produto_page.content()

                            dados = extrair_dados_html(
                                html,
                                url=link,
                                texto_extra=texto_visivel,
                            )

                            item.update(dados)

                            mini_info: dict[str, Any] = {}

                            if mini_celulares:
                                mini_info = analisar_mini_celular(
                                    dados,
                                    maior_max_cm=mini_maior_cm,
                                    largura_max_cm=mini_largura_cm,
                                )
                                item.update(mini_info)

                                mini_status = str(mini_info.get("mini_status") or "")
                                manter_por_medida = mini_status == "MANTER"
                                manter_sem_medida = mini_manter_sem_medida and mini_status in {"REVISAR_SEM_MEDIDA", "SUSPEITO_MANUAL"}

                                log("mini", f"Status: {mini_status or 'não classificado'}")
                                log("mini", f"Motivo: {mini_info.get('mini_motivo') or 'sem motivo'}")
                                if mini_info.get("mini_evidencia"):
                                    log("mini", f"Evidência: {encurtar_texto(str(mini_info.get('mini_evidencia')), 180)}")
                                if mini_info.get("mini_suspeito_manual"):
                                    log_aviso("mini", f"Suspeito manual: {mini_info.get('mini_motivos_suspeito') or 'sem detalhe'}")

                                if not (manter_por_medida or manter_sem_medida):
                                    item["status_validacao"] = "FORA_ESCOPO_MINI"
                                    item["motivo_validacao"] = mini_info.get("mini_motivo", "Fora do recorte de mini celular")
                                    item["fabricante_base"] = ""
                                    item["marca_base"] = ""
                                    item["modelo_base"] = ""
                                    item["versao_base"] = ""

                                    if mini_status == "SUSPEITO_MANUAL" or mini_info.get("mini_suspeito_manual"):
                                        # Suspeitos manuais não vão mais para descartados.
                                        # Eles ficam preservados em products_suspeitos_mini.parquet
                                        # e com evidência em prints/irregulares.
                                        item["print_path"] = _salvar_print(produto_page, pasta_saida, idx, "IRREGULAR")
                                        item_suspeito = dict(item)
                                        item_suspeito["status_validacao"] = "SUSPEITO_MANUAL"
                                        item_suspeito["motivo_validacao"] = item_suspeito.get("mini_motivo") or "Suspeito para análise manual"
                                        suspeitos_mini.append(item_suspeito)
                                        salvar_parcial()
                                        continue

                                    descartados_mini.append(item)
                                    salvar_parcial()
                                    continue

                            validacao = validar_produto(dados, base_anatel)

                            item.update(validacao)

                            log("produto", f"Título: {encurtar_texto(dados.get('titulo', ''), 100)}")
                            log("produto", f"Marca capturada: {dados.get('marca') or 'não encontrada'}")
                            log("produto", f"Modelo capturado: {dados.get('modelo') or 'não encontrado'}")
                            log(
                                "produto",
                                f"Fabricante capturado: {dados.get('fabricante') or 'não encontrado na Shopee'}",
                            )
                            log(
                                "anatel",
                                f"Código capturado: {dados.get('codigo_anatel_principal') or 'não encontrado'}",
                            )

                            comentarios_produto = _capturar_comentarios_produto(
                                produto_page,
                                idx=idx,
                                link=link,
                                titulo=dados.get("titulo", ""),
                                limite=10,
                            )
                            comentarios_resultados.extend(comentarios_produto)

                            item["print_path"] = _salvar_print(
                                produto_page,
                                pasta_saida,
                                idx,
                                item.get("status_validacao", "IRREGULAR"),
                            )

                            status = item.get("status_validacao", "IRREGULAR")
                            motivo = item.get("motivo_validacao", "")

                            if status == "REGULAR":
                                log_ok("resultado", "REGULAR")
                            else:
                                log_erro("resultado", "IRREGULAR")

                            if motivo:
                                log_aviso("motivo", encurtar_texto(motivo, 160))

                            produtos_resultados.append(item)

                            # Se o produto mantido também é suspeito, salva uma cópia na fila manual
                            # com print em prints/irregulares, sem mexer no status ANATEL do products.parquet.
                            if mini_celulares and (item.get("mini_suspeito_manual") or item.get("mini_status") == "SUSPEITO_MANUAL"):
                                item_suspeito = dict(item)
                                item_suspeito["status_validacao"] = "SUSPEITO_MANUAL"
                                item_suspeito["motivo_validacao"] = item_suspeito.get("mini_motivo") or "Suspeito para análise manual"
                                item_suspeito["print_path"] = _salvar_print(produto_page, pasta_saida, idx, "IRREGULAR")
                                suspeitos_mini.append(item_suspeito)

                        except PlaywrightTimeoutError as exc:
                            item.update(
                                {
                                    "status_validacao": "IRREGULAR",
                                    "motivo_validacao": "Timeout ao abrir ou coletar produto.",
                                    "erro": str(exc),
                                }
                            )
                            item["print_path"] = _salvar_print(
                                produto_page,
                                pasta_saida,
                                idx,
                                "IRREGULAR",
                            )
                            produtos_resultados.append(item)
                            log("erro", f"Timeout no produto {idx}: {exc}")

                        except Exception as exc:
                            item.update(
                                {
                                    "status_validacao": "IRREGULAR",
                                    "motivo_validacao": "Erro inesperado na coleta do produto.",
                                    "erro": str(exc),
                                }
                            )
                            item["print_path"] = _salvar_print(
                                produto_page,
                                pasta_saida,
                                idx,
                                "IRREGULAR",
                            )
                            produtos_resultados.append(item)
                            log("erro", f"Erro no produto {idx}: {exc}")

                        finally:
                            # Remove duplicidade eventual na fila de suspeitos pelo URL + mini_status.
                            if suspeitos_mini:
                                dedup: list[dict[str, Any]] = []
                                vistos_suspeitos: set[str] = set()

                                for suspeito in suspeitos_mini:
                                    chave = f"{suspeito.get('url')}|{suspeito.get('mini_status')}|{suspeito.get('mini_motivos_suspeito')}"
                                    if chave in vistos_suspeitos:
                                        continue
                                    vistos_suspeitos.add(chave)
                                    dedup.append(suspeito)

                                suspeitos_mini[:] = dedup

                            # Salva a cada produto para não perder resultado se o crawler parar no meio.
                            try:
                                salvar_parcial()
                            except Exception as exc:
                                log_aviso("salvar", f"Falha ao salvar parquets parciais: {exc}")

                            try:
                                produto_page.close()
                            except Exception:
                                pass

        finally:
            context.close()

    products_path = salvar_products(pasta_saida, produtos_resultados)
    comentarios_path = salvar_comentarios(pasta_saida, comentarios_resultados)

    descartados_path = ""
    suspeitos_path = ""

    if mini_celulares:
        descartados_path = str(salvar_products_descartados_mini(pasta_saida, descartados_mini))
        suspeitos_path = str(salvar_products_suspeitos_mini(pasta_saida, suspeitos_mini))

    return {
        "engine": "playwright",
        "pasta_saida": str(pasta_saida),
        "products_parquet": str(products_path),
        "comentarios_parquet": str(comentarios_path),
        "products_descartados_mini_parquet": descartados_path,
        "products_suspeitos_mini_parquet": suspeitos_path,
        "total_produtos": len(produtos_resultados),
        "total_comentarios_linhas": len(comentarios_resultados),
        "total_descartados_mini": len(descartados_mini),
        "total_suspeitos_mini": len(suspeitos_mini),
        "total_urls_processadas": len(urls_processadas),
        "total_buscas": len(queries_execucao),
        "max_paginas": max_paginas,
    }

