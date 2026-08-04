from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.core import AccessRequest, User
from app.routers.common import templates
from app.security import current_user, hash_password, touch_last_login, verify_password
from app.services.audit import audit_log
from app.services.forms import optional_email, required_text
from app.services.notifications import notify_user, recipients_with_permission
from app.services.transactions import atomic
from app.services.users import unique_username_from_full_name

router = APIRouter()


@router.get("/login")
def login_form(request: Request):
    error = "Sessão expirada por inatividade. Inicie sessão novamente." if request.query_params.get("timeout") == "1" else None
    return templates.TemplateResponse(request, "auth/login.html", {"request": request, "error": error})


@router.get("/pedido-acesso")
def access_request_form(request: Request):
    return templates.TemplateResponse(
        request,
        "auth/access_request.html",
        {"request": request, "values": {}, "error": None, "success": None},
    )


@router.post("/pedido-acesso")
def create_access_request(
    request: Request,
    full_name: str | None = Form(None),
    email: str | None = Form(None),
    phone: str | None = Form(None),
    note: str | None = Form(None),
    db: Session = Depends(get_db),
):
    values = {
        "full_name": full_name or "",
        "email": email or "",
        "phone": phone or "",
        "note": note or "",
    }
    try:
        clean_name = required_text(full_name, "Nome completo", 160)
        clean_email = optional_email(required_text(email, "Email", 160))
        clean_phone = required_text(phone, "Contacto", 40)
        clean_note = (note or "").strip() or None
        if clean_note and len(clean_note) > 500:
            raise HTTPException(400, "Observações não pode exceder 500 caracteres.")
    except HTTPException as exc:
        return templates.TemplateResponse(
            request,
            "auth/access_request.html",
            {"request": request, "values": values, "error": exc.detail, "success": None},
            status_code=400,
        )

    existing_user = db.scalar(
        select(User).where(
            or_(
                User.email == clean_email,
                User.username == unique_username_from_full_name(db, clean_name),
            )
        )
    )
    if existing_user:
        return templates.TemplateResponse(
            request,
            "auth/access_request.html",
            {
                "request": request,
                "values": values,
                "error": "Já existe um utilizador com estes dados. Contacte o IT se não conseguir entrar.",
                "success": None,
            },
            status_code=400,
        )
    pending_request = db.scalar(
        select(AccessRequest).where(
            AccessRequest.email == clean_email,
            AccessRequest.status == "Pending",
        )
    )
    if pending_request:
        return templates.TemplateResponse(
            request,
            "auth/access_request.html",
            {
                "request": request,
                "values": values,
                "error": None,
                "success": "Já existe um pedido de acesso pendente para este email. O IT será responsável pela validação.",
            },
        )

    username_suggestion = unique_username_from_full_name(db, clean_name)
    with atomic(db):
        access_request = AccessRequest(
            full_name=clean_name,
            username_suggestion=username_suggestion,
            email=clean_email,
            phone=clean_phone,
            note=clean_note,
        )
        db.add(access_request)
        db.flush()
        message = (
            f"Novo pedido de acesso ao GTIMS.\n"
            f"Nome: {clean_name}\n"
            f"Email: {clean_email}\n"
            f"Contacto: {clean_phone}\n"
            f"Username sugerido: {username_suggestion}"
        )
        for recipient in recipients_with_permission(db, "users_manage"):
            notify_user(
                db,
                recipient,
                f"Pedido de acesso: {clean_name}",
                message,
                "Utilizadores",
                f"ACCESS_REQUEST:{access_request.id}",
                email=False,
            )
        audit_log(
            db,
            None,
            "Criou pedido de acesso",
            "Utilizadores",
            access_request.id,
            new_value={"email": clean_email, "username_suggestion": username_suggestion},
            request=request,
        )

    return templates.TemplateResponse(
        request,
        "auth/access_request.html",
        {
            "request": request,
            "values": {},
            "error": None,
            "success": "Pedido enviado com sucesso. O IT irá validar e responder.",
            "username_suggestion": username_suggestion,
        },
    )


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
    request.session["last_activity_at"] = datetime.now(timezone.utc).timestamp()
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
