from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.core import User
from app.routers.common import templates
from app.security import current_user, hash_password, touch_last_login, verify_password
from app.services.audit import audit_log
from app.services.forms import required_text
from app.services.transactions import atomic

router = APIRouter()


@router.get("/login")
def login_form(request: Request):
    return templates.TemplateResponse(request, "auth/login.html", {"request": request, "error": None})


@router.post("/login")
def login(request: Request, username: str | None = Form(None), password: str | None = Form(None), db: Session = Depends(get_db)):
    clean_username = required_text(username, "Utilizador")
    clean_password = required_text(password, "Senha")
    user = db.scalar(select(User).where(User.username == clean_username))
    if not user or not user.is_active or not verify_password(clean_password, user.password_hash):
        with atomic(db):
            audit_log(db, None, "Login falhou", "Auth", clean_username, request=request)
        return templates.TemplateResponse(request, "auth/login.html", {"request": request, "error": "Credenciais inválidas."}, status_code=400)
    request.session["user_id"] = user.id
    request.session["language"] = user.preferred_language or "pt"
    with atomic(db):
        touch_last_login(user)
        audit_log(db, user, "Login", "Auth", user.id, request=request)
    if user.must_reset_password:
        return RedirectResponse("/reset-password", status_code=303)
    return RedirectResponse("/dashboard", status_code=303)


@router.get("/reset-password")
def reset_form(request: Request, user: User = Depends(current_user)):
    return templates.TemplateResponse(request, "auth/reset_password.html", {"request": request, "user": user, "error": None})


@router.post("/reset-password")
def reset_password(
    request: Request,
    password: str = Form(...),
    confirm_password: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    if len(password) < 8 or password != confirm_password:
        return templates.TemplateResponse(request, "auth/reset_password.html",
            {"request": request, "user": user, "error": "Confirme uma senha com pelo menos 8 caracteres."},
            status_code=400,
        )
    with atomic(db):
        user.password_hash = hash_password(password)
        user.must_reset_password = False
        audit_log(db, user, "Redefiniu senha", "Utilizadores", user.id, request=request)
    return RedirectResponse("/dashboard", status_code=303)


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    with atomic(db):
        audit_log(db, user, "Logout", "Auth", user.id, request=request)
    language = user.preferred_language or request.session.get("language") or "pt"
    request.session.clear()
    request.session["language"] = language
    return RedirectResponse("/login", status_code=303)
