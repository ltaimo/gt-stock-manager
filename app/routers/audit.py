from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.core import AuditLog, User
from app.routers.common import templates
from app.security import require_roles

router = APIRouter(prefix="/auditoria", tags=["auditoria"])


@router.get("")
def audit_index(
    request: Request,
    module: str = "",
    action: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("SuperAdmin", "Admin")),
):
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(500)
    if module:
        stmt = stmt.where(AuditLog.module.ilike(f"%{module}%"))
    if action:
        stmt = stmt.where(AuditLog.action.ilike(f"%{action}%"))
    logs = db.scalars(stmt).all()
    return templates.TemplateResponse(
        "audit/index.html",
        {"request": request, "user": user, "logs": logs, "module": module, "action": action},
    )
