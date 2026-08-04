from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import case, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.core import AccessRequest, Department, Role, User
from app.routers.common import templates
from app.security import can_manage_user, hash_password, require_permission
from app.i18n import normalize_language, translate_message
from app.services.audit import audit_log
from app.services.forms import optional_email, optional_int, required_int, required_text
from app.services.notifications import send_email
from app.services.transactions import atomic

router = APIRouter(prefix="/utilizadores", tags=["utilizadores"])


def raise_form_error_for_language(exc: HTTPException, language: str) -> None:
    if normalize_language(language) == "en" and isinstance(exc.detail, str):
        raise HTTPException(exc.status_code, translate_message(exc.detail, "en")) from exc
    raise exc


@router.get("")
def list_users(request: Request, db: Session = Depends(get_db), user: User = Depends(require_permission("users_manage"))):
    users = db.scalars(select(User).order_by(User.full_name)).all()
    access_requests = db.scalars(
        select(AccessRequest)
        .order_by(
            case((AccessRequest.status == "Pending", 0), else_=1),
            AccessRequest.created_at.desc(),
        )
        .limit(50)
    ).all()
    pending_access_count = sum(1 for item in access_requests if item.status == "Pending")
    return templates.TemplateResponse(
        request,
        "users/index.html",
        {
            "request": request,
            "user": user,
            "users": users,
            "access_requests": access_requests,
            "pending_access_count": pending_access_count,
        },
    )


@router.get("/novo")
def new_user(
    request: Request,
    access_request_id: int | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("users_manage")),
):
    access_request = db.get(AccessRequest, access_request_id) if access_request_id else None
    if access_request and access_request.status != "Pending":
        access_request = None
    return templates.TemplateResponse(
        request,
        "users/form.html",
        {
            "request": request,
            "user": user,
            "target": None,
            "access_request": access_request,
            "roles": db.scalars(select(Role).order_by(Role.name)).all(),
            "departments": db.scalars(select(Department).where(Department.is_active == True).order_by(Department.name)).all(),
        },
    )


@router.post("/novo")
def create_user(
    request: Request,
    full_name: str | None = Form(None),
    username: str | None = Form(None),
    email: str | None = Form(None),
    phone: str | None = Form(None),
    password: str | None = Form(None),
    role_id: str | None = Form(None),
    department_id: str | None = Form(None),
    notify_email: str | None = Form(None),
    notify_whatsapp: str | None = Form(None),
    preferred_language: str = Form("pt"),
    access_request_id: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("users_manage")),
):
    try:
        clean_name = required_text(full_name, "Nome completo", 160)
        clean_username = required_text(username, "Utilizador", 80)
        clean_password = required_text(password, "Senha inicial")
        if len(clean_password) < 8:
            raise HTTPException(400, "A senha inicial deve ter pelo menos 8 caracteres.")
        parsed_role_id = required_int(role_id, "Perfil")
        parsed_department_id = optional_int(department_id, "Departamento")
        parsed_access_request_id = optional_int(access_request_id, "Pedido de acesso")
    except HTTPException as exc:
        raise_form_error_for_language(exc, preferred_language)
    if preferred_language not in {"pt", "en"}:
        raise HTTPException(400, "Idioma inválido.")
    role = db.get(Role, parsed_role_id)
    if not role or not can_manage_user(user, None, role.name):
        raise HTTPException(403)
    if db.scalar(select(User).where(User.username == clean_username)):
        raise HTTPException(400, "Já existe um utilizador com este nome.")
    clean_email = optional_email(email)
    if clean_email and db.scalar(select(User).where(User.email == clean_email)):
        raise HTTPException(400, "Já existe um utilizador com este email.")
    access_request = db.get(AccessRequest, parsed_access_request_id) if parsed_access_request_id else None
    if access_request and access_request.status != "Pending":
        raise HTTPException(400, "Este pedido de acesso já foi tratado.")
    with atomic(db):
        target = User(
            full_name=clean_name,
            username=clean_username,
            email=clean_email,
            phone=(phone or "").strip() or None,
            password_hash=hash_password(clean_password),
            role_id=parsed_role_id,
            department_id=parsed_department_id,
            notify_email=notify_email == "1",
            notify_whatsapp=notify_whatsapp == "1",
            preferred_language=preferred_language,
            must_reset_password=True,
        )
        db.add(target)
        db.flush()
        if access_request:
            access_request.status = "Approved"
            access_request.user_id = target.id
            access_request.reviewed_by_id = user.id
            access_request.reviewed_at = datetime.now(timezone.utc)
        audit_log(
            db,
            user,
            "Criou utilizador",
            "Utilizadores",
            target.id,
            new_value={
                "username": clean_username,
                "role": role.name,
                "access_request_id": access_request.id if access_request else None,
            },
            request=request,
        )
    if access_request and clean_email:
        try:
            send_email(
                clean_email,
                "Acesso GTIMS criado",
                (
                    "O seu acesso ao GTIMS foi criado.\n\n"
                    f"Utilizador: {clean_username}\n"
                    "Contacte o IT para receber a senha inicial e concluir o primeiro login."
                ),
            )
        except Exception:
            pass
    return RedirectResponse("/utilizadores", status_code=303)


@router.get("/{target_id}/editar")
def edit_user(target_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_permission("users_manage"))):
    target = db.get(User, target_id)
    if not target or not can_manage_user(user, target):
        raise HTTPException(403)
    return templates.TemplateResponse(
        request,
        "users/form.html",
        {
            "request": request,
            "user": user,
            "target": target,
            "access_request": None,
            "roles": db.scalars(select(Role).order_by(Role.name)).all(),
            "departments": db.scalars(select(Department).where(Department.is_active == True).order_by(Department.name)).all(),
        },
    )


@router.post("/{target_id}/editar")
def update_user(
    target_id: int,
    request: Request,
    full_name: str | None = Form(None),
    email: str | None = Form(None),
    phone: str | None = Form(None),
    role_id: str | None = Form(None),
    department_id: str | None = Form(None),
    is_active: bool = Form(False),
    notify_email: str | None = Form(None),
    notify_whatsapp: str | None = Form(None),
    password: str | None = Form(None),
    confirm_password: str | None = Form(None),
    force_password_reset: str | None = Form(None),
    preferred_language: str = Form("pt"),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("users_manage")),
):
    try:
        clean_name = required_text(full_name, "Nome completo", 160)
        parsed_role_id = required_int(role_id, "Perfil")
        parsed_department_id = optional_int(department_id, "Departamento")
        clean_password = (password or "").strip()
        clean_confirm_password = (confirm_password or "").strip()
        if clean_password or clean_confirm_password:
            if len(clean_password) < 8 or clean_password != clean_confirm_password:
                raise HTTPException(400, "Confirme uma senha com pelo menos 8 caracteres.")
    except HTTPException as exc:
        raise_form_error_for_language(exc, preferred_language)
    if preferred_language not in {"pt", "en"}:
        raise HTTPException(400, "Idioma inválido.")
    target = db.get(User, target_id)
    role = db.get(Role, parsed_role_id)
    if not target or not role or not can_manage_user(user, target, role.name):
        raise HTTPException(403)
    old = {"role": target.role.name, "active": target.is_active, "must_reset_password": target.must_reset_password}
    clean_email = optional_email(email)
    duplicate_email = clean_email and db.scalar(select(User).where(User.email == clean_email, User.id != target.id))
    if duplicate_email:
        raise HTTPException(400, "Já existe um utilizador com este email.")
    with atomic(db):
        target.full_name = clean_name
        target.email = clean_email
        target.phone = (phone or "").strip() or None
        target.role_id = parsed_role_id
        target.department_id = parsed_department_id
        target.is_active = is_active
        target.notify_email = notify_email == "1"
        target.notify_whatsapp = notify_whatsapp == "1"
        target.preferred_language = preferred_language
        password_was_reset = bool(clean_password)
        if password_was_reset:
            target.password_hash = hash_password(clean_password)
            target.must_reset_password = force_password_reset == "1"
        audit_log(
            db,
            user,
            "Atualizou utilizador",
            "Utilizadores",
            target.id,
            old_value=old,
            new_value={"role": role.name, "active": is_active, "password_reset": password_was_reset},
            request=request,
        )
    return RedirectResponse("/utilizadores", status_code=303)


@router.post("/pedidos-acesso/{request_id}/rejeitar")
def reject_access_request(
    request_id: int,
    request: Request,
    decision_note: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("users_manage")),
):
    access_request = db.get(AccessRequest, request_id)
    if not access_request or access_request.status != "Pending":
        raise HTTPException(404)
    clean_note = (decision_note or "").strip() or None
    with atomic(db):
        access_request.status = "Rejected"
        access_request.reviewed_by_id = user.id
        access_request.reviewed_at = datetime.now(timezone.utc)
        access_request.decision_note = clean_note
        audit_log(
            db,
            user,
            "Rejeitou pedido de acesso",
            "Utilizadores",
            access_request.id,
            new_value={"email": access_request.email, "reason": clean_note},
            request=request,
        )
    try:
        body = "O seu pedido de acesso ao GTIMS foi analisado e não foi aprovado."
        if clean_note:
            body += f"\n\nObservação: {clean_note}"
        send_email(access_request.email, "Pedido de acesso GTIMS", body)
    except Exception:
        pass
    return RedirectResponse("/utilizadores#pedidos-acesso", status_code=303)


@router.post("/{target_id}/remover")
def remove_user_access(
    target_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("users_manage")),
):
    target = db.get(User, target_id)
    if not target or not can_manage_user(user, target):
        raise HTTPException(403)
    if target.id == user.id:
        raise HTTPException(400, "Não pode remover o seu próprio acesso.")
    if target.role.name == "SuperAdmin":
        raise HTTPException(400, "O acesso do SuperAdmin não pode ser removido.")
    with atomic(db):
        target.is_active = False
        audit_log(db, user, "Removeu acesso do utilizador", "Utilizadores", target.id, old_value={"active": True}, new_value={"active": False}, request=request)
    return RedirectResponse("/utilizadores", status_code=303)
