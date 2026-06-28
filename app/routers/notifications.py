from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.core import Notification, ProcurementCase, Requisition, User
from app.routers.common import templates
from app.security import current_user
from app.services.transactions import atomic

router = APIRouter(prefix="/notificacoes", tags=["notificacoes"])


@router.get("")
def list_notifications(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    notifications = db.scalars(
        select(Notification).where(Notification.user_id == user.id).order_by(Notification.created_at.desc()).limit(100)
    ).all()
    return templates.TemplateResponse(request, "notifications/index.html", {"request": request, "user": user, "notifications": notifications})


@router.post("/{notification_id}/ler")
def mark_read(notification_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    notification = db.get(Notification, notification_id)
    if notification and notification.user_id == user.id:
        with atomic(db):
            notification.is_read = True
            notification.read_at = datetime.now(timezone.utc)
    return RedirectResponse("/notificacoes", status_code=303)


@router.get("/{notification_id}/abrir")
def open_notification(notification_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    notification = db.get(Notification, notification_id)
    if not notification or notification.user_id != user.id:
        return RedirectResponse("/notificacoes", status_code=303)

    with atomic(db):
        notification.is_read = True
        notification.read_at = datetime.now(timezone.utc)

    if notification.module in {"Requisicoes", "Requisições", "Requisições"} and notification.record_id:
        requisition = db.scalar(select(Requisition).where(Requisition.number == notification.record_id))
        if requisition:
            return RedirectResponse(f"/requisicoes/{requisition.id}", status_code=303)
    if notification.module == "Procurement" and notification.record_id:
        requisition = db.scalar(select(Requisition).where(Requisition.number == notification.record_id))
        if requisition:
            case = db.scalar(select(ProcurementCase).where(ProcurementCase.requisition_id == requisition.id))
            if case:
                return RedirectResponse(f"/procurement/{case.id}", status_code=303)
    return RedirectResponse("/notificacoes", status_code=303)
