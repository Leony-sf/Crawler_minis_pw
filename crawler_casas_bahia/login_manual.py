from playwright.sync_api import sync_playwright
from pathlib import Path

def abrir_login_manual():
    perfil = Path("perfil_casas_bahia")
    perfil.mkdir(parents=True, exist_ok=True)

    args = [
        "--disable-blink-features=AutomationControlled",
        "--start-maximized",
        "--no-sandbox"
    ]

    with sync_playwright() as p:
        print("[LOGIN] Abrindo navegador para login manual...")
        contexto = p.chromium.launch_persistent_context(
            user_data_dir=str(perfil.resolve()),
            headless=False,
            channel="chrome",
            args=args,
            ignore_default_args=["--enable-automation"],  # <-- O PULO DO GATO AQUI
            viewport={"width": 1366, "height": 900},
            locale="pt-BR"
        )

        page = contexto.new_page()
        
        js_stealth = """
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        window.chrome = { runtime: {} };
        """
        page.add_init_script(js_stealth)
        page.set_default_timeout(0) 

        page.goto("https://www.casasbahia.com.br")
        print("\nNavegue e teste os produtos. Feche no 'X' quando terminar.")

        page.wait_for_event("close", timeout=0)
        contexto.close()

if __name__ == "__main__":
    abrir_login_manual()