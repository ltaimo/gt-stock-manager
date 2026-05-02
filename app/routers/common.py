from fastapi.templating import Jinja2Templates

from app.config import get_settings
from app.services.notifications import unread_count

templates = Jinja2Templates(directory="app/templates")
settings = get_settings()


def role_in(user, *roles: str) -> bool:
    return user and user.role.name in roles


templates.env.globals["role_in"] = role_in
templates.env.globals["app_name"] = settings.app_name
templates.env.globals["app_subtitle"] = settings.app_subtitle
templates.env.globals["app_short_name"] = settings.app_short_name
templates.env.globals["logo_available"] = settings.logo_path.exists
templates.env.globals["unread_notifications"] = unread_count
