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


def mark_notification_group_read(db: Session, notification: Notification) -> None:
    now = datetime.now(timezone.utc)
    stmt = select(Notification).where(
        Notification.user_id == notification.user_id,
        Notification.is_read == False,
    )
    if notification.record_id:
        stmt = stmt.where(Notification.module == notification.module, Notification.record_id == notification.record_id)
    else:
        stmt = stmt.where(Notification.id == notification.id)
    for item in db.scalars(stmt).all():
        item.is_read = True
        item.read_at = now


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
            mark_notification_group_read(db, notification)
    return RedirectResponse("/notificacoes", status_code=303)


@router.get("/{notification_id}/abrir")
def open_notification(notification_id: int, db: Session = Depends(get_db), user: User = Depends(current_user)):
    notification = db.get(Notification, notification_id)
    if not notification or notification.user_id != user.id:
        return RedirectResponse("/notificacoes", status_code=303)

    with atomic(db):
        mark_notification_group_read(db, notification)

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
