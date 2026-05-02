import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.models.core import Notification, Requisition, Role, User


NOTIFICATION_ROLES = {"Gestor de Estoque", "Chefe do Terminal", "SuperAdmin"}


def unread_count(user_id: int) -> int:
    with SessionLocal() as db:
        return db.scalar(select(func.count(Notification.id)).where(Notification.user_id == user_id, Notification.is_read == False)) or 0


def recipients_for_requisitions(db: Session) -> list[User]:
    return db.scalars(
        select(User).where(User.is_active == True, User.role.has(Role.name.in_(NOTIFICATION_ROLES)))
    ).all()


def send_email(to_email: str, subject: str, body: str) -> None:
    settings = get_settings()
    if not to_email:
        return
    if settings.smtp_host:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = settings.smtp_from
        msg["To"] = to_email
        msg.set_content(body)
        with smtplib.SMTP(settings.smtp_host, settings.smtp_port) as smtp:
            smtp.starttls()
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(msg)
        return

    safe_name = "".join(ch if ch.isalnum() else "_" for ch in to_email)
    filename = f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{safe_name}.txt"
    path = settings.email_outbox_dir / filename
    path.write_text(f"To: {to_email}\nSubject: {subject}\n\n{body}", encoding="utf-8")


def notify_user(db: Session, user: User, title: str, message: str, module: str, record_id: str | None = None, email: bool = True) -> None:
    db.add(Notification(user_id=user.id, title=title, message=message, module=module, record_id=record_id))
    if email and user.email:
        send_email(user.email, title, message)


def notify_requisition_pending(db: Session, req: Requisition) -> None:
    title = f"Requisição pendente: {req.number}"
    message = (
        f"Existe uma requisição pendente para análise.\n"
        f"Nº: {req.number}\n"
        f"Requisitante: {req.requesting_user.full_name}\n"
        f"Departamento: {req.department.name if req.department else ''}\n"
        f"Tipo: {req.req_type}"
    )
    for user in recipients_for_requisitions(db):
        notify_user(db, user, title, message, "Requisições", req.number)


def notify_requisition_decision(db: Session, req: Requisition, actor: User, decision: str) -> None:
    title = f"Requisição {decision}: {req.number}"
    message = f"A requisição {req.number} foi {decision.lower()} por {actor.full_name}."
    targets = recipients_for_requisitions(db)
    if req.requesting_user not in targets:
        targets.append(req.requesting_user)
    for user in targets:
        notify_user(db, user, title, message, "Requisições", req.number)
