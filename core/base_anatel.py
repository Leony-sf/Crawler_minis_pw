import re
import pandas as pd
from typing import Dict, Any, Tuple, Optional

# Listas categorizadas para exclusão semântica de itens indesejados
EXCLUSION_PATTERNS = [
    # --- DOCES, BALAS E ALIMENTOS ---
    r"\bdoce\b", r"\bdoces\b", r"\bchiclete\b", r"\bchicletes\b", 
    r"\bbala\b", r"\bbalas\b", r"\bpirulito\b", r"\bguloseima\b", 
    r"\bcandy\b", r"\bsnack\b", r"\bconfeito\b", r"\bcomida\b",

    # --- BRINQUEDOS, RÉPLICAS E MODELOS FALSOS ---
    r"\bbrinquedo\b", r"\bbrinquedos\b", r"\btoy\b", r"\btoys\b", 
    r"\binfantil\b", r"\bfalso\b", r"\bdummy\b", r"\bmaquete\b", 
    r"\bréplica\b", r"\breplica\b", r"\bsimulado\b", r"\bde mentira\b",
    r"\bmorcego de plástico\b", r"\bmodelo de exibição\b",

    # --- ACESSÓRIOS & PEÇAS ---
    r"\bcapa\b", r"\bcapinha\b", r"\bpelícula\b", r"\bpelicula\b", 
    r"\bsuporte\b", r"\bcase\b", r"\bcarregador\b", r"\bcabo\b", 
    r"\bfone\b", r"\bfone de ouvido\b", r"\bcapa protetora\b", 
    r"\badesivo\b", r"\bbateria\b", r"\btela\b", r"\bpeça\b", r"\bpeca\b",
    r"\badaptador\b", r"\bcordão\b", r"\bcordao\b", r"\bchaveiro\b", r"\bpingente\b",

    # --- DISPOSITIVOS NÃO-CELULARES ---
    r"\brelógio\b", r"\brelogio\b", r"\bsmartwatch\b", r"\bcalculadora\b", 
    r"\brádio\b", r"\bradio\b", r"\bwalkie talkie\b", r"\bcaixa de som\b"
]

# Limites oficiais de dimensão para mini celular
MAX_ALTURA_CM = 12.5
MAX_LARGURA_CM = 5.5

class AnatelValidator:
    def __init__(self, base_csv_path: str = "Produtos_Homologados_Anatel.csv"):
        self.base_path = base_csv_path
        self.homologated_codes = set()
        self.homologated_models = set()
        self._load_base()

    def _load_base(self):
        """Carrega e indexa códigos de homologação e modelos da base da Anatel."""
        try:
            df = pd.read_csv(self.base_path, dtype=str, sep=";")
            
            # Indexa códigos de homologação
            col_code = [c for c in df.columns if "homolog" in c.lower() or "codigo" in c.lower()]
            if col_code:
                codes = df[col_code[0]].dropna().astype(str).str.replace(r"\D", "", regex=True)
                self.homologated_codes = set(codes)

            # Indexa nomes de modelos/produtos
            col_model = [c for c in df.columns if "modelo" in c.lower() or "produto" in c.lower()]
            if col_model:
                models = df[col_model[0]].dropna().astype(str).str.strip().str.upper()
                self.homologated_models = set(models)

        except Exception:
            self.homologated_codes = set()
            self.homologated_models = set()

    def clean_code(self, code: str) -> str:
        """Extrai apenas os números do código de homologação."""
        if not code or pd.isna(code):
            return ""
        return re.sub(r"\D", "", str(code))

    def is_homologated(self, code: str = "", model: str = "") -> bool:
        """Verifica se o produto consta na base oficial da Anatel por código ou modelo."""
        cleaned_code = self.clean_code(code)
        if cleaned_code and self.homologated_codes:
            if cleaned_code in self.homologated_codes:
                return True

        if model and self.homologated_models:
            model_clean = str(model).strip().upper()
            if model_clean in self.homologated_models:
                return True

        return False

def is_ignored_item(title: str) -> bool:
    """Verifica se o título contém qualquer palavra da lista de exclusão (doces, brinquedos, capas)."""
    if not title:
        return True
    title_lower = title.lower()
    for pattern in EXCLUSION_PATTERNS:
        if re.search(pattern, title_lower):
            return True
    return False

def parse_dimensions_cm(text: str) -> Tuple[Optional[float], Optional[float]]:
    """Extrai dimensões (altura x largura) em cm a partir do texto do anúncio."""
    if not text:
        return None, None

    # Procura padrão em cm (ex: '11.5 x 4.8 cm' ou '12,5x5,5cm')
    match_cm = re.search(r"(\d+[\.,]?\d*)\s*x\s*(\d+[\.,]?\d*)\s*cm", text, re.IGNORECASE)
    if match_cm:
        h = float(match_cm.group(1).replace(",", "."))
        w = float(match_cm.group(2).replace(",", "."))
        return h, w

    # Procura padrão em mm (ex: '85 x 35 mm')
    match_mm = re.search(r"(\d+[\.,]?\d*)\s*x\s*(\d+[\.,]?\d*)\s*mm", text, re.IGNORECASE)
    if match_mm:
        h = float(match_mm.group(1).replace(",", ".")) / 10.0
        w = float(match_mm.group(2).replace(",", ".")) / 10.0
        return h, w

    return None, None

def is_mini_celular(title: str, description: str = "", height_cm: Optional[float] = None, width_cm: Optional[float] = None) -> bool:
    """Valida se o produto respeita as dimensões limite de mini celular (<= 12.5cm x 5.5cm)."""
    if height_cm is not None and width_cm is not None:
        return height_cm <= MAX_ALTURA_CM and width_cm <= MAX_LARGURA_CM

    h_ext, w_ext = parse_dimensions_cm(f"{title} {description}")
    if h_ext is not None and w_ext is not None:
        return h_ext <= MAX_ALTURA_CM and w_ext <= MAX_LARGURA_CM

    # Fallback por termos característicos de mini celular no título
    title_lower = title.lower()
    return any(term in title_lower for term in ["mini", "bm10", "l8star", "j9", "tinyme"])

def normalize_item(item: Dict[str, Any]) -> Dict[str, Any]:
    """Normaliza e marca sinalizadores de limpeza no item extraído."""
    title = str(item.get("title", "")).strip()
    price = item.get("price", 0.0)
    
    if isinstance(price, str):
        price = price.replace("R$", "").replace(".", "").replace(",", ".").strip()
        try:
            price = float(price)
        except ValueError:
            price = 0.0

    is_ignored = is_ignored_item(title)
    is_mini = is_mini_celular(title, item.get("description", ""), item.get("height_cm"), item.get("width_cm"))

    return {
        "marketplace": str(item.get("marketplace", "")).strip(),
        "query": str(item.get("query", "")).strip(),
        "title": title,
        "price": float(price),
        "seller": str(item.get("seller", "N/A")).strip(),
        "url": str(item.get("url", "")).strip(),
        "anatel_code": str(item.get("anatel_code", "")).strip(),
        "model": str(item.get("model", "")).strip(),
        "is_ignored_item": is_ignored,  # True se for doce, brinquedo ou acessório
        "is_mini_celular": is_mini and not is_ignored,  # Só é válido se respeitar medidas e NÃO for item ignorado
        "scraped_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
    }