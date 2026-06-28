import logging

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import joinedload

from app.database import SessionLocal
from app.i18n import language_for, translate_message
from app.models.core import User
from app.routers.common import templates
from app.services.forms import field_label


logger = logging.getLogger(__name__)


def request_user(request: Request) -> User | None:
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    db = SessionLocal()
    try:
        return db.get(User, int(user_id), options=[joinedload(User.role), joinedload(User.department)])
    finally:
        db.close()


def error_response(request: Request, message: str, status_code: int):
    user = request_user(request)
    return templates.TemplateResponse(
        request,
        "error.html",
        {
            "request": request,
            "user": user,
            "message": translate_message(message, language_for(user, request)),
            "status_code": status_code,
            "back_url": request.headers.get("referer") or "/dashboard",
        },
        status_code=status_code,
    )


async def validation_error_handler(request: Request, exc: RequestValidationError):
    messages = []
    for item in exc.errors():
        field = field_label(str(item.get("loc", ["campo"])[-1]))
        error_type = item.get("type", "")
        if error_type == "missing":
            message = f"{field} é obrigatório."
        elif "parsing" in error_type:
            message = f"{field} contém um valor inválido."
        else:
            message = f"Verifique o campo {field}."
        if message not in messages:
            messages.append(message)
    return error_response(request, " ".join(messages) or "Verifique os dados informados.", 400)


async def http_error_handler(request: Request, exc: HTTPException):
    if exc.status_code in (301, 302, 303, 307, 308) and exc.headers and exc.headers.get("Location"):
        return RedirectResponse(exc.headers["Location"], status_code=exc.status_code)
    detail = exc.detail if isinstance(exc.detail, str) else "Não foi possível concluir a operação."
    friendly = {
        403: "Não tem permissão para executar esta ação.",
        404: "O registo ou página solicitada não foi encontrado.",
    }.get(exc.status_code, detail)
    return error_response(request, friendly, exc.status_code)


async def unexpected_error_handler(request: Request, exc: Exception):
    logger.exception("Erro inesperado em %s %s", request.method, request.url.path, exc_info=exc)
    return error_response(
        request,
        "Ocorreu um erro inesperado. Nenhum dado incompleto foi gravado. Tente novamente.",
        500,
    )
