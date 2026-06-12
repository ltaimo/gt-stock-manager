from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.core import Department, Role, User
from app.routers.common import templates
from app.security import can_manage_user, hash_password, require_permission
from app.services.audit import audit_log
from app.services.forms import optional_email, optional_int, required_int, required_text
from app.services.transactions import atomic

router = APIRouter(prefix="/utilizadores", tags=["utilizadores"])


@router.get("")
def list_users(request: Request, db: Session = Depends(get_db), user: User = Depends(require_permission("users_manage"))):
    users = db.scalars(select(User).order_by(User.full_name)).all()
    return templates.TemplateResponse("users/index.html", {"request": request, "user": user, "users": users})


@router.get("/novo")
def new_user(request: Request, db: Session = Depends(get_db), user: User = Depends(require_permission("users_manage"))):
    return templates.TemplateResponse("users/form.html", {"request": request, "user": user, "target": None, "roles": db.scalars(select(Role)).all(), "departments": db.scalars(select(Department)).all()})


@router.post("/novo")
def create_user(
    request: Request,
    full_name: str | None = Form(None),
    username: str | None = Form(None),
    email: str | None = Form(None),
    password: str | None = Form(None),
    role_id: str | None = Form(None),
    department_id: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("users_manage")),
):
    clean_name = required_text(full_name, "Nome completo", 160)
    clean_username = required_text(username, "Utilizador", 80)
    clean_password = required_text(password, "Senha inicial")
    if len(clean_password) < 8:
        raise HTTPException(400, "A senha inicial deve ter pelo menos 8 caracteres.")
    parsed_role_id = required_int(role_id, "Perfil")
    parsed_department_id = optional_int(department_id, "Departamento")
    role = db.get(Role, parsed_role_id)
    if not role or not can_manage_user(user, None, role.name):
        raise HTTPException(403)
    if db.scalar(select(User).where(User.username == clean_username)):
        raise HTTPException(400, "Já existe um utilizador com este nome.")
    clean_email = optional_email(email)
    if clean_email and db.scalar(select(User).where(User.email == clean_email)):
        raise HTTPException(400, "Já existe um utilizador com este email.")
    with atomic(db):
        target = User(
            full_name=clean_name,
            username=clean_username,
            email=clean_email,
            password_hash=hash_password(clean_password),
            role_id=parsed_role_id,
            department_id=parsed_department_id,
        )
        db.add(target)
        db.flush()
        audit_log(db, user, "Criou utilizador", "Utilizadores", target.id, new_value={"username": clean_username, "role": role.name}, request=request)
    return RedirectResponse("/utilizadores", status_code=303)


@router.get("/{target_id}/editar")
def edit_user(target_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_permission("users_manage"))):
    target = db.get(User, target_id)
    if not target or not can_manage_user(user, target):
        raise HTTPException(403)
    return templates.TemplateResponse("users/form.html", {"request": request, "user": user, "target": target, "roles": db.scalars(select(Role)).all(), "departments": db.scalars(select(Department)).all()})


@router.post("/{target_id}/editar")
def update_user(target_id: int, request: Request, full_name: str | None = Form(None), email: str | None = Form(None), role_id: str | None = Form(None), department_id: str | None = Form(None), is_active: bool = Form(False), db: Session = Depends(get_db), user: User = Depends(require_permission("users_manage"))):
    clean_name = required_text(full_name, "Nome completo", 160)
    parsed_role_id = required_int(role_id, "Perfil")
    parsed_department_id = optional_int(department_id, "Departamento")
    target = db.get(User, target_id)
    role = db.get(Role, parsed_role_id)
    if not target or not role or not can_manage_user(user, target, role.name):
        raise HTTPException(403)
    old = {"role": target.role.name, "active": target.is_active}
    clean_email = optional_email(email)
    duplicate_email = clean_email and db.scalar(select(User).where(User.email == clean_email, User.id != target.id))
    if duplicate_email:
        raise HTTPException(400, "Já existe um utilizador com este email.")
    with atomic(db):
        target.full_name = clean_name
        target.email = clean_email
        target.role_id = parsed_role_id
        target.department_id = parsed_department_id
        target.is_active = is_active
        audit_log(db, user, "Atualizou utilizador", "Utilizadores", target.id, old_value=old, new_value={"role": role.name, "active": is_active}, request=request)
    return RedirectResponse("/utilizadores", status_code=303)


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
