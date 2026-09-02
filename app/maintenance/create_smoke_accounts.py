from __future__ import annotations

import json
import os

from sqlalchemy import select

from app.database import SessionLocal
from app.models.core import Department, Role, User
from app.security import DEFAULT_ROLE_PERMISSIONS, hash_password


SMOKE_USERS = [
    ("smoke.ns.requester", "Smoke NS Requisitante", "User"),
    ("smoke.ns.hod", "Smoke NS HOD", "Gestor Operacional"),
    ("smoke.ns.terminal", "Smoke NS Director Terminal", "Director do Terminal"),
    ("smoke.ns.finance", "Smoke NS Director Financeiro", "Director Financeiro"),
    ("smoke.ns.procurement", "Smoke NS Procurement Officer", "Procurement Officer"),
]


def _enabled() -> bool:
    return os.getenv("GTIMS_ENABLE_SMOKE_ACCOUNTS", "").strip().lower() in {"1", "true", "yes", "on"}


def _role_permissions(role_name: str) -> str | None:
    permissions = DEFAULT_ROLE_PERMISSIONS.get(role_name)
    if role_name == "SuperAdmin" or permissions is None:
        return None
    return json.dumps(sorted(permissions))


def ensure_smoke_accounts() -> list[dict[str, str]]:
    if not _enabled():
        raise RuntimeError("Defina GTIMS_ENABLE_SMOKE_ACCOUNTS=true para criar/atualizar contas smoke.")
    password = os.getenv("GTIMS_SMOKE_PASSWORD", "").strip()
    if len(password) < 12:
        raise RuntimeError("Defina GTIMS_SMOKE_PASSWORD com pelo menos 12 caracteres.")

    with SessionLocal() as db:
        department = db.scalar(select(Department).where(Department.name == "Smoke Tests"))
        if not department:
            department = Department(name="Smoke Tests", is_active=True)
            db.add(department)
            db.flush()

        roles_by_name: dict[str, Role] = {}
        for _, _, role_name in SMOKE_USERS:
            role = db.scalar(select(Role).where(Role.name == role_name))
            if not role:
                role = Role(name=role_name, permissions=_role_permissions(role_name), is_system=True)
                db.add(role)
                db.flush()
            roles_by_name[role_name] = role

        created: list[dict[str, str]] = []
        for username, full_name, role_name in SMOKE_USERS:
            account = db.scalar(select(User).where(User.username == username))
            if not account:
                account = User(
                    username=username,
                    full_name=full_name,
                    password_hash=hash_password(password),
                    role_id=roles_by_name[role_name].id,
                    department_id=department.id,
                    is_active=True,
                    must_reset_password=True,
                    notify_email=False,
                    notify_whatsapp=False,
                    preferred_language="pt",
                )
                db.add(account)
                action = "created"
            else:
                account.full_name = full_name
                account.role_id = roles_by_name[role_name].id
                account.department_id = department.id
                account.is_active = True
                account.notify_email = False
                account.notify_whatsapp = False
                action = "updated"
            created.append({"username": username, "role": role_name, "action": action})
        db.commit()
        return created


if __name__ == "__main__":
    for row in ensure_smoke_accounts():
        print(f"{row['action']}: {row['username']} ({row['role']})")
