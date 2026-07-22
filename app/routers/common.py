from fastapi.templating import Jinja2Templates
from jinja2 import pass_context

from app.config import get_settings
from app.i18n import KEY_TRANSLATIONS, language_for, localize_audit_value, localized_name, tm, translate_key, tv, tx
from app.security import has_permission, role_permissions
from app.services.notifications import unread_count

templates = Jinja2Templates(directory="app/templates")
settings = get_settings()

TRANSLATIONS = KEY_TRANSLATIONS


def role_in(user, *roles: str) -> bool:
    return user and user.role.name in roles


def current_language(user=None, request=None) -> str:
    return language_for(user, request)


def translate(key: str, user=None) -> str:
    return translate_key(key, current_language(user))


@pass_context
def jinja_tx(context, text, user=None, request=None):
    return tx(text, user, request or context.get("request"))


@pass_context
def jinja_tm(context, text, user=None, request=None):
    return tm(text, user, request or context.get("request"))


@pass_context
def jinja_tv(context, value, user=None, request=None):
    return tv(value, user, request or context.get("request"))


@pass_context
def jinja_localized_name(context, entity, user=None, request=None):
    return localized_name(entity, user, request or context.get("request"))


@pass_context
def jinja_audit_value(context, value, user=None, request=None):
    return localize_audit_value(value, user, request or context.get("request"))


templates.env.globals["role_in"] = role_in
templates.env.globals["can"] = has_permission
templates.env.globals["role_permissions"] = role_permissions
templates.env.globals["current_language"] = current_language
templates.env.globals["t"] = translate
templates.env.globals["tx"] = jinja_tx
templates.env.globals["tv"] = jinja_tv
templates.env.globals["tm"] = jinja_tm
templates.env.globals["lname"] = jinja_localized_name
templates.env.globals["audit_value"] = jinja_audit_value
templates.env.globals["app_name"] = settings.app_name
templates.env.globals["app_version"] = settings.app_version
templates.env.globals["app_subtitle"] = settings.app_subtitle
templates.env.globals["app_short_name"] = settings.app_short_name
templates.env.globals["session_timeout_seconds"] = settings.session_timeout_seconds
templates.env.globals["logo_available"] = settings.logo_path.exists
templates.env.globals["unread_notifications"] = unread_count
