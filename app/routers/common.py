from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.services.notifications import unread_count
from app.security import has_permission, role_permissions

templates = Jinja2Templates(directory="app/templates")
settings = get_settings()

TRANSLATIONS = {
    "pt": {
        "dashboard": "Dashboard",
        "products": "Economato / Produtos",
        "movements": "Movimentos",
        "documents": "Documentos",
        "new_sr": "Nova Requisicao SR",
        "sr_requests": "Requisicoes SR",
        "procurement": "Procurement / NS",
        "reports": "Relatorios",
        "users": "Utilizadores",
        "profiles": "Perfis de acesso",
        "imports": "Importar",
        "audit": "Auditoria",
        "settings": "Configuracoes",
        "about": "Sobre",
        "notifications": "Notificacoes",
        "dashboard_intro": "Visão operacional de stock, movimentos, alertas, procurement e projeções do mês.",
        "total_products": "Total de produtos",
        "open_procurement": "Procurement aberto",
        "pending_requests": "Requisições Pendentes",
    },
    "en": {
        "dashboard": "Dashboard",
        "products": "Store / Products",
        "movements": "Movements",
        "documents": "Documents",
        "new_sr": "New SR Request",
        "sr_requests": "SR Requests",
        "procurement": "Procurement / NS",
        "reports": "Reports",
        "users": "Users",
        "profiles": "Access Profiles",
        "imports": "Import",
        "audit": "Audit",
        "settings": "Settings",
        "about": "About",
        "notifications": "Notifications",
        "dashboard_intro": "Operational view of stock, movements, alerts, procurement, and monthly projections.",
        "total_products": "Total products",
        "open_procurement": "Open procurement",
        "pending_requests": "Pending Requests",
    },
}


def role_in(user, *roles: str) -> bool:
    return user and user.role.name in roles


def current_language(user=None) -> str:
    language = getattr(user, "preferred_language", None) or settings.default_language
    return language if language in TRANSLATIONS else "pt"


def translate(key: str, user=None) -> str:
    language = current_language(user)
    return TRANSLATIONS[language].get(key, TRANSLATIONS["pt"].get(key, key))


templates.env.globals["role_in"] = role_in
templates.env.globals["can"] = has_permission
templates.env.globals["role_permissions"] = role_permissions
templates.env.globals["current_language"] = current_language
templates.env.globals["t"] = translate
templates.env.globals["app_name"] = settings.app_name
templates.env.globals["app_subtitle"] = settings.app_subtitle
templates.env.globals["app_short_name"] = settings.app_short_name
templates.env.globals["logo_available"] = settings.logo_path.exists
templates.env.globals["unread_notifications"] = unread_count
