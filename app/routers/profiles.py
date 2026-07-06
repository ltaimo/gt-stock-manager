import json

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.core import ApprovalMatrixRule, Role, User
from app.routers.common import templates
from app.security import PERMISSIONS, grant_permissions, require_permission, role_permissions
from app.services.audit import audit_log
from app.services.forms import required_text
from app.services.transactions import atomic

router = APIRouter(prefix="/perfis", tags=["perfis"])


def profile_context(request: Request, db: Session, user: User, target: Role | None = None) -> dict:
    return {
        "request": request,
        "user": user,
        "target": target,
        "roles": db.scalars(select(Role).order_by(Role.name)).all(),
        "permission_options": PERMISSIONS,
        "selected_permissions": role_permissions(target) if target else set(),
    }


@router.get("")
def profiles(request: Request, db: Session = Depends(get_db), user: User = Depends(require_permission("profiles_manage"))):
    return templates.TemplateResponse(request, "profiles/index.html", profile_context(request, db, user))


@router.get("/novo")
def new_profile(request: Request, db: Session = Depends(get_db), user: User = Depends(require_permission("profiles_manage"))):
    return templates.TemplateResponse(request, "profiles/form.html", profile_context(request, db, user))


@router.post("/novo")
def create_profile(
    request: Request,
    name: str | None = Form(None),
    permissions: list[str] = Form([]),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("profiles_manage")),
):
    clean_name = required_text(name, "Nome do perfil", 30)
    if db.scalar(select(Role).where(Role.name.ilike(clean_name))):
        raise HTTPException(400, "Já existe um perfil com este nome.")
    invalid = set(permissions) - set(PERMISSIONS)
    if invalid:
        raise HTTPException(400, "Uma ou mais permissões são inválidas.")
    with atomic(db):
        role = Role(name=clean_name, permissions=json.dumps(sorted(set(permissions))), is_system=False)
        db.add(role)
        db.flush()
        audit_log(db, user, "Criou perfil", "Perfis", role.id, new_value={"name": role.name, "permissions": permissions}, request=request)
    return RedirectResponse("/perfis", status_code=303)


@router.get("/{role_id}/editar")
def edit_profile(role_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_permission("profiles_manage"))):
    role = db.get(Role, role_id)
    if not role:
        raise HTTPException(404)
    return templates.TemplateResponse(request, "profiles/form.html", profile_context(request, db, user, role))


@router.post("/{role_id}/editar")
def update_profile(
    role_id: int,
    request: Request,
    name: str | None = Form(None),
    permissions: list[str] = Form([]),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("profiles_manage")),
):
    role = db.get(Role, role_id)
    if not role:
        raise HTTPException(404)
    clean_name = required_text(name, "Nome do perfil", 30)
    if role.name == "SuperAdmin" and clean_name != "SuperAdmin":
        raise HTTPException(400, "O perfil SuperAdmin não pode ser renomeado.")
    duplicate = db.scalar(select(Role).where(Role.name.ilike(clean_name), Role.id != role.id))
    if duplicate:
        raise HTTPException(400, "Já existe um perfil com este nome.")
    invalid = set(permissions) - set(PERMISSIONS)
    if invalid:
        raise HTTPException(400, "Uma ou mais permissões são inválidas.")
    old = {"name": role.name, "permissions": sorted(role_permissions(role))}
    configured_permissions = set(permissions)
    is_matrix_approver = db.scalar(
        select(ApprovalMatrixRule.id).where(
            ApprovalMatrixRule.approver_role_id == role.id,
            ApprovalMatrixRule.is_active == True,
        ).limit(1)
    )
    with atomic(db):
        role.name = clean_name
        role.permissions = json.dumps(sorted(set(PERMISSIONS if role.name == "SuperAdmin" else configured_permissions)))
        if is_matrix_approver:
            grant_permissions(
                role,
                {"requisitions_all", "requisitions_review", "procurement_value_approve"},
            )
        audit_log(
            db,
            user,
            "Atualizou perfil",
            "Perfis",
            role.id,
            old_value=old,
            new_value={"name": role.name, "permissions": sorted(role_permissions(role))},
            request=request,
        )
    return RedirectResponse("/perfis", status_code=303)


@router.post("/{role_id}/remover")
def delete_profile(role_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_permission("profiles_manage"))):
    role = db.get(Role, role_id)
    if not role:
        raise HTTPException(404)
    if role.name == "SuperAdmin":
        raise HTTPException(400, "O perfil SuperAdmin não pode ser removido.")
    if db.scalar(select(User.id).where(User.role_id == role.id).limit(1)):
        raise HTTPException(400, "Não é possível remover um perfil associado a utilizadores.")
    if db.scalar(select(ApprovalMatrixRule.id).where(ApprovalMatrixRule.approver_role_id == role.id).limit(1)):
        raise HTTPException(400, "Não é possível remover um perfil associado à matriz de aprovações.")
    with atomic(db):
        audit_log(db, user, "Removeu perfil", "Perfis", role.id, old_value={"name": role.name}, request=request)
        db.delete(role)
    return RedirectResponse("/perfis", status_code=303)
