from datetime import datetime, timezone
from typing import Iterable

from fastapi import Depends, HTTPException, Request, status
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.core import User


pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")


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
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sem permissão")
        return user

    return dependency


def operational_roles() -> tuple[str, ...]:
    return ("SuperAdmin", "Admin", "Editor", "Gestor de Estoque", "Chefe do Terminal")


def can_manage_user(actor: User, target: User | None, requested_role: str | None = None) -> bool:
    if actor.role.name == "SuperAdmin":
        return True
    if actor.role.name != "Admin":
        return False
    if target and target.role.name == "SuperAdmin":
        return False
    return requested_role != "SuperAdmin"


def touch_last_login(user: User) -> None:
    user.last_login_at = datetime.now(timezone.utc)
