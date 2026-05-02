import json
from typing import Any

from fastapi import Request
from sqlalchemy.orm import Session

from app.models.core import AuditLog, User


def audit_log(
    db: Session,
    user: User | None,
    action: str,
    module: str,
    record_id: str | int | None = None,
    old_value: Any = None,
    new_value: Any = None,
    request: Request | None = None,
) -> None:
    ip_device = None
    if request:
        client = request.client.host if request.client else "unknown"
        agent = request.headers.get("user-agent", "")
        ip_device = f"{client} | {agent[:160]}"
    db.add(
        AuditLog(
            user_id=user.id if user else None,
            action=action,
            module=module,
            record_id=str(record_id) if record_id is not None else None,
            old_value=json.dumps(old_value, ensure_ascii=False, default=str) if old_value is not None else None,
            new_value=json.dumps(new_value, ensure_ascii=False, default=str) if new_value is not None else None,
            ip_device=ip_device,
        )
    )
