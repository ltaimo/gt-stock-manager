from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.core import Notification, User
from app.routers.common import templates
from app.security import current_user
from app.services.transactions import atomic

router = APIRouter(prefix="/notificacoes", tags=["notificacoes"])


@router.get("")
def list_notifications(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    notifications = db.scalars(
        select(Notification).where(Notification.user_id == user.id).order_by(Notification.created_at.desc()).limit(100)
    ).all()
    return templates.TemplateResponse("notifications/index.html", {"request": request, "user": user, "notifications": notifications})


@router.post("/{notification_id}/ler")
def mark_read(notification_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    notification = db.get(Notification, notification_id)
    if notification and notification.user_id == user.id:
        with atomic(db):
            notification.is_read = True
            notification.read_at = datetime.now(timezone.utc)
    return RedirectResponse("/notificacoes", status_code=303)
