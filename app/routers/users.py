from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.core import Department, Role, User
from app.routers.common import templates
from app.security import can_manage_user, current_user, hash_password, require_roles
from app.services.audit import audit_log
from app.services.forms import optional_int
from app.services.transactions import atomic

router = APIRouter(prefix="/utilizadores", tags=["utilizadores"])


@router.get("")
def list_users(request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles("SuperAdmin", "Admin"))):
    users = db.scalars(select(User).order_by(User.full_name)).all()
    return templates.TemplateResponse("users/index.html", {"request": request, "user": user, "users": users})


@router.get("/novo")
def new_user(request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles("SuperAdmin", "Admin"))):
    return templates.TemplateResponse("users/form.html", {"request": request, "user": user, "target": None, "roles": db.scalars(select(Role)).all(), "departments": db.scalars(select(Department)).all()})


@router.post("/novo")
def create_user(
    request: Request,
    full_name: str = Form(...),
    username: str = Form(...),
    email: str | None = Form(None),
    password: str = Form(...),
    role_id: int = Form(...),
    department_id: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("SuperAdmin", "Admin")),
):
    parsed_department_id = optional_int(department_id, "Departamento")
    role = db.get(Role, role_id)
    if not role or not can_manage_user(user, None, role.name):
        raise HTTPException(403)
    if db.scalar(select(User).where(User.username == username.strip())):
        raise HTTPException(400, "Utilizador duplicado.")
    with atomic(db):
        target = User(
            full_name=full_name,
            username=username.strip(),
            email=email or None,
            password_hash=hash_password(password),
            role_id=role_id,
            department_id=parsed_department_id,
        )
        db.add(target)
        db.flush()
        audit_log(db, user, "Criou utilizador", "Utilizadores", target.id, new_value={"username": username, "role": role.name}, request=request)
    return RedirectResponse("/utilizadores", status_code=303)


@router.get("/{target_id}/editar")
def edit_user(target_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles("SuperAdmin", "Admin"))):
    target = db.get(User, target_id)
    if not target or not can_manage_user(user, target):
        raise HTTPException(403)
    return templates.TemplateResponse("users/form.html", {"request": request, "user": user, "target": target, "roles": db.scalars(select(Role)).all(), "departments": db.scalars(select(Department)).all()})


@router.post("/{target_id}/editar")
def update_user(target_id: int, request: Request, full_name: str = Form(...), email: str | None = Form(None), role_id: int = Form(...), department_id: str | None = Form(None), is_active: bool = Form(False), db: Session = Depends(get_db), user: User = Depends(require_roles("SuperAdmin", "Admin"))):
    parsed_department_id = optional_int(department_id, "Departamento")
    target = db.get(User, target_id)
    role = db.get(Role, role_id)
    if not target or not role or not can_manage_user(user, target, role.name):
        raise HTTPException(403)
    old = {"role": target.role.name, "active": target.is_active}
    with atomic(db):
        target.full_name = full_name
        target.email = email or None
        target.role_id = role_id
        target.department_id = parsed_department_id
        target.is_active = is_active
        audit_log(db, user, "Atualizou utilizador", "Utilizadores", target.id, old_value=old, new_value={"role": role.name, "active": is_active}, request=request)
    return RedirectResponse("/utilizadores", status_code=303)
