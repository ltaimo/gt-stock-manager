import re
import unicodedata


def normalize_text(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"\s+", " ", text.lower()).strip()


CATEGORY_RULES: list[tuple[str, tuple[str, ...]]] = [
    ("Climatização", (" ac ", "gree", "btu", "ar condicionado")),
    ("Informática e Equipamentos", ("computador", "monitor", "impressora", "scanner", "mouse", "teclado", "bar code", "barcode", "laser usb", "tv ", "samsung", "ups", "flash drive", "pos epson")),
    ("Consumíveis de Impressão", ("toner", "tonner", "tinta para carimbo", "rolo para pos", "rolos pos")),
    ("Material de Escritório", ("agrafo", "agrafador", "caneta", "papel a4", "fixador", "fita-cola", "marcador", "carimbo", "livro", "ticket", "pasta", "elastico", "borracha", "porta chaves", "quadro")),
    ("Limpeza e Higiene", ("ambientador", "detergente", "omo", "lixivia", "javel", "mop", "sabao", "lixo", "papel higienico", "alcool", "vim", "baygon", "papel aderente")),
    ("Equipamentos de Proteção", ("luva", "colete", "oculos", "mascara", "cone", "danger tape", "perneira", "anti-caleira")),
    ("Material Elétrico e Iluminação", ("lampada", "lampadas", "armadura", "arrancador", "fio pbc", "fita isoladora")),
    ("Canalização", ("bicha flexivel", "curva pvc", "t pvc", "ips", "torneira", "tubo", "tanque", "autoclismo", "uniao especial", "teflon")),
    ("Ferramentas e Manutenção", ("bomba", "eletrobomba", "hidropess", "motobomba", "maquina", "soprador", "rebite", "canhao", "fechadura", "miolo")),
    ("Pintura", ("tinta 5l", "balde de tinta")),
    ("Jardinagem", ("capim", "relva", "pesticida")),
]


def infer_category(product_name: str) -> str:
    normalized = f" {normalize_text(product_name)} "
    for category, keywords in CATEGORY_RULES:
        if any(keyword in normalized for keyword in keywords):
            return category
    return "Operações e Diversos"
