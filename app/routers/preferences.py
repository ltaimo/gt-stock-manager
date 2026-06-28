from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.core import User
from app.security import current_user
from app.services.transactions import atomic

router = APIRouter(prefix="/preferencias", tags=["preferencias"])


@router.post("/idioma")
def set_language(
    request: Request,
    language: str = Form("pt"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    if language not in {"pt", "en"}:
        language = "pt"
    with atomic(db):
        user.preferred_language = language
        request.session["language"] = language
    return RedirectResponse(request.headers.get("referer") or "/dashboard", status_code=303)
