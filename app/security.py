from datetime import datetime, timezone
import json

from fastapi import Depends, HTTPException, Request, status
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.core import User


pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")

PERMISSIONS = {
    "products_manage": "Criar e editar produtos",
    "movements": "Consultar e registar movimentos",
    "documents": "Consultar documentos de stock",
    "requisitions_all": "Consultar todas as requisições",
    "stock_requisitions_create": "Criar requisições de stock",
    "non_stock_requisitions_create": "Criar requisições non-stock",
    "stock_replenishment_create": "Criar pedidos de reposição de stock",
    "requisitions_review": "Aprovar ou rejeitar requisições",
    "requisitions_issue": "Emitir itens aprovados",
    "budget_verify": "Verificar disponibilidade orçamental",
    "procurement_tor_approve_hod": "Aprovar TdR/requisitos técnicos como HOD",
    "procurement_tor_approve_terminal": "Aprovar TdR/requisitos técnicos como Director do Terminal",
    "procurement_value_approve": "Aprovar processos pela matriz de valor",
    "procurement_manage": "Gerir processos de procurement",
    "procurement_settings": "Gerir matriz de aprovação de Procurement",
    "procurement_technical_evaluate": "Registar avaliação técnica",
    "procurement_financial_evaluate": "Registar avaliação financeira",
    "procurement_hse_validate": "Validar documentos e requisitos HSE",
    "procurement_receive": "Registar nota de recebimento",
    "procurement_archive": "Arquivar processos de procurement",
    "reports": "Consultar relatórios",
    "users_manage": "Gerir utilizadores",
    "profiles_manage": "Gerir perfis e permissões",
    "settings_manage": "Gerir categorias e departamentos",
    "stock_adjust": "Ajustar quantidade existente com justificação",
    "stock_reset": "Resetar todo o stock",
    "imports": "Importar dados",
    "audit": "Consultar auditoria",
}

DEFAULT_ROLE_PERMISSIONS = {
    "SuperAdmin": set(PERMISSIONS),
    "Admin": set(PERMISSIONS) - {"profiles_manage", "stock_adjust", "stock_reset"},
    "Editor": {
        "movements",
        "documents",
        "requisitions_all",
        "stock_requisitions_create",
        "non_stock_requisitions_create",
        "stock_replenishment_create",
        "requisitions_review",
        "requisitions_issue",
        "reports",
    },
    "Gestor de Estoque": {
        "movements",
        "documents",
        "requisitions_all",
        "stock_requisitions_create",
        "stock_replenishment_create",
        "requisitions_issue",
        "procurement_receive",
        "reports",
        "stock_adjust",
    },
    "Chefe do Terminal": {
        "documents",
        "requisitions_all",
        "stock_requisitions_create",
        "non_stock_requisitions_create",
        "requisitions_review",
        "procurement_tor_approve_terminal",
        "procurement_value_approve",
    },
    "Director Financeiro": {
        "budget_verify",
        "documents",
        "procurement_financial_evaluate",
        "procurement_value_approve",
        "reports",
        "requisitions_all",
        "requisitions_review",
    },
    "Administrador Delegado": {
        "documents",
        "procurement_value_approve",
        "reports",
        "requisitions_all",
        "requisitions_review",
    },
    "PCA": {
        "documents",
        "procurement_value_approve",
        "reports",
        "requisitions_all",
        "requisitions_review",
    },
    "Gestor Operacional": {"stock_requisitions_create", "non_stock_requisitions_create", "stock_replenishment_create", "procurement_tor_approve_hod"},
    "User": {"stock_requisitions_create", "non_stock_requisitions_create"},
}


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login"})
    user = db.get(User, int(user_id))
    if not user or not user.is_active:
        request.session.clear()
        raise HTTPException(status_code=status.HTTP_303_SEE_OTHER, headers={"Location": "/login"})
    return user


def optional_user(request: Request, db: Session = Depends(get_db)) -> User | None:
    user_id = request.session.get("user_id")
    return db.get(User, int(user_id)) if user_id else None


def require_roles(*roles: str):
    allowed = set(roles)

    def dependency(user: User = Depends(current_user)) -> User:
        if user.role.name not in allowed:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sem permissao")
        return user

    return dependency


def role_permissions(role) -> set[str]:
    if role.name == "SuperAdmin":
        return set(PERMISSIONS)
    if role.permissions:
        try:
            return set(json.loads(role.permissions))
        except (TypeError, ValueError):
            pass
    return set(DEFAULT_ROLE_PERMISSIONS.get(role.name, set()))


def has_permission(user: User | None, permission: str) -> bool:
    return bool(user and permission in role_permissions(user.role))


def matches_approval_assignment(
    user: User | None,
    permission: str,
    approver_role_id: int | None,
    approver_label: str | None,
) -> bool:
    if not user or not has_permission(user, permission):
        return False
    if user.role.name == "SuperAdmin":
        return True
    if approver_role_id:
        return user.role_id == approver_role_id
    expected = (approver_label or "").strip().casefold()
    return not expected or user.role.name.strip().casefold() == expected


def grant_permissions(role, permissions: set[str]) -> set[str]:
    if role.name == "SuperAdmin":
        return set()
    current = role_permissions(role)
    added = set(permissions) - current
    if added:
        role.permissions = json.dumps(sorted(current | added))
    return added


def require_permission(permission: str):
    def dependency(user: User = Depends(current_user)) -> User:
        if not has_permission(user, permission):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sem permissao")
        return user

    return dependency


def operational_roles() -> tuple[str, ...]:
    return ("SuperAdmin", "Admin", "Editor", "Gestor Operacional", "Gestor de Estoque", "Chefe do Terminal")


def can_manage_user(actor: User, target: User | None, requested_role: str | None = None) -> bool:
    if actor.role.name == "SuperAdmin":
        return True
    if not has_permission(actor, "users_manage"):
        return False
    if target and target.role.name == "SuperAdmin":
        return False
    return requested_role != "SuperAdmin"


def touch_last_login(user: User) -> None:
    user.last_login_at = datetime.now(timezone.utc)
