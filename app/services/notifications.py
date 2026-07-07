import json
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage
from urllib import request as urlrequest

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import SessionLocal
from app.i18n import language_for, translate_value
from app.models.core import Notification, ProcurementCase, Requisition, User
from app.security import has_permission
from app.services.approval_policy import users_for_approval_assignment


def unread_count(user_id: int) -> int:
    with SessionLocal() as db:
        return db.scalar(select(func.count(Notification.id)).where(Notification.user_id == user_id, Notification.is_read == False)) or 0


def recipients_with_permission(db: Session, permission: str) -> list[User]:
    users = db.scalars(select(User).where(User.is_active == True)).all()
    return [user for user in users if has_permission(user, permission)]


def recipients_for_requisition_approval(db: Session, req: Requisition) -> list[User]:
    return users_for_approval_assignment(
        db,
        "requisitions_review",
        req.approver_role_id,
        req.authorization_person,
        amount=float(req.estimated_value or 0),
    )


def send_email(to_email: str, subject: str, body: str, attachments: list[tuple[str, bytes, str]] | None = None) -> None:
    settings = get_settings()
    if not to_email:
        return
    attachments = attachments or []
    if settings.smtp_host:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = settings.smtp_from
        msg["To"] = to_email
        msg.set_content(body)
        for filename, content, mime_type in attachments:
            maintype, subtype = mime_type.split("/", 1)
            msg.add_attachment(content, maintype=maintype, subtype=subtype, filename=filename)
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
    for attachment_name, content, _mime_type in attachments:
        safe_attachment = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in attachment_name)
        attachment_path = settings.email_outbox_dir / f"{path.stem}_{safe_attachment}"
        attachment_path.write_bytes(content)


def send_whatsapp(phone: str, subject: str, body: str) -> None:
    settings = get_settings()
    if not phone:
        return
    payload = {"from": settings.whatsapp_sender, "to": phone, "subject": subject, "message": body}
    if settings.whatsapp_webhook_url:
        data = json.dumps(payload).encode("utf-8")
        req = urlrequest.Request(
            settings.whatsapp_webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlrequest.urlopen(req, timeout=10):
            return

    safe_phone = "".join(ch if ch.isalnum() else "_" for ch in phone)
    filename = f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{safe_phone}.json"
    path = settings.whatsapp_outbox_dir / filename
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def localize_notification(text: str, user: User) -> str:
    if language_for(user) != "en":
        return text
    replacements = (
        ("Requisicao pendente:", "Pending requisition:"),
        ("Requisição pendente:", "Pending requisition:"),
        ("Requisicao Aprovada parcialmente:", "Requisition partially approved:"),
        ("Requisicao Aprovada:", "Requisition approved:"),
        ("Requisicao Rejeitada:", "Requisition rejected:"),
        ("Budget pendente:", "Pending budget:"),
        ("Procurement para classificar:", "Procurement pending classification:"),
        ("TdR para aprovação HOD:", "ToR pending HOD approval:"),
        ("TdR para aprovação Terminal Manager:", "ToR pending Terminal Manager approval:"),
        ("Reposição de stock para aprovação:", "Stock replenishment pending approval:"),
        ("TdR devolvido para correção:", "ToR returned for correction:"),
        ("TdR devolvido pelo Terminal Manager:", "ToR returned by the Terminal Manager:"),
        ("Decisão de aprovação:", "Approval decision:"),
        ("Reposição recebida:", "Replenishment received:"),
        ("Existe uma requisicao pendente para analise.", "There is a requisition pending review."),
        ("Existe uma requisição pendente para análise.", "There is a requisition pending review."),
        ("Existe uma requisicao non-stock pendente de verificacao de budget.", "There is a non-stock requisition pending budget verification."),
        ("O budget da requisicao non-stock foi confirmado e o processo esta pronto para classificacao.", "The non-stock requisition budget was confirmed and the process is ready for classification."),
        ("aguarda aprovação do HOD/Chefe do Departamento.", "is pending HOD/Head of Department approval."),
        ("aguarda aprovação do HOD.", "is pending HOD approval."),
        ("O HOD aprovou o TdR do processo", "The HOD approved the ToR for process"),
        ("O HOD devolveu o TdR do processo", "The HOD returned the ToR for process"),
        ("O Terminal Manager devolveu o TdR do processo", "The Terminal Manager returned the ToR for process"),
        ("para correção.", "for correction."),
        ("foi aprovado por", "was approved by"),
        ("foi devolvido por", "was returned by"),
        ("Os produtos do pedido", "The products for request"),
        ("foram recebidos no stock.", "were received into stock."),
        ("Foi registada uma receção parcial do pedido", "A partial receipt was recorded for request"),
        ("A requisicao", "Requisition"),
        ("A requisição", "Requisition"),
        ("foi aprovada parcialmente por", "was partially approved by"),
        ("foi aprovada por", "was approved by"),
        ("foi rejeitada por", "was rejected by"),
        ("Requisitante:", "Requester:"),
        ("Departamento:", "Department:"),
        ("Tipo:", "Type:"),
        ("N.:", "No.:"),
        ("no valor estimado de", "with an estimated value of"),
    )
    localized = text
    for source, target in replacements:
        localized = localized.replace(source, target)
    return localized


def notify_user(db: Session, user: User, title: str, message: str, module: str, record_id: str | None = None, email: bool = True) -> None:
    title = localize_notification(title, user)
    message = localize_notification(message, user)
    db.add(Notification(user_id=user.id, title=title, message=message, module=module, record_id=record_id))
    if email and user.email and user.notify_email:
        send_email(user.email, title, message)
    if user.phone and user.notify_whatsapp:
        send_whatsapp(user.phone, title, message)


def notify_requisition_pending(db: Session, req: Requisition) -> None:
    title = f"Requisicao pendente: {req.number}"
    message = (
        f"Existe uma requisicao pendente para analise.\n"
        f"N.: {req.number}\n"
        f"Requisitante: {req.requesting_user.full_name}\n"
        f"Departamento: {req.department.name if req.department else ''}\n"
        f"Tipo: {req.req_type}"
    )
    for user in recipients_for_requisition_approval(db, req):
        notify_user(db, user, title, message, "Requisicoes", req.number)


def notify_requisition_decision(db: Session, req: Requisition, actor: User, decision: str) -> None:
    targets = recipients_with_permission(db, "requisitions_issue")
    if all(target.id != req.requesting_user_id for target in targets):
        targets.append(req.requesting_user)
    for user in targets:
        translated_decision = translate_value(decision, language_for(user))
        title = (
            f"Requisition {translated_decision.lower()}: {req.number}"
            if language_for(user) == "en"
            else f"Requisição {translated_decision.lower()}: {req.number}"
        )
        message = (
            f"Requisition {req.number} was {translated_decision.lower()} by {actor.full_name}."
            if language_for(user) == "en"
            else f"A requisição {req.number} foi {translated_decision.lower()} por {actor.full_name}."
        )
        notify_user(db, user, title, message, "Requisicoes", req.number)


def notify_procurement_budget_pending(db: Session, req: Requisition) -> None:
    title = f"Budget pendente: {req.number}"
    message = (
        f"Existe uma requisicao non-stock pendente de verificacao de budget.\n"
        f"N.: {req.number}\n"
        f"Requisitante: {req.requesting_user.full_name}\n"
        f"Departamento: {req.department.name if req.department else ''}"
    )
    for user in recipients_with_permission(db, "budget_verify"):
        notify_user(db, user, title, message, "Procurement", req.number)


def notify_procurement_permission(db: Session, case: ProcurementCase, permission: str, title: str, message: str) -> None:
    for user in recipients_with_permission(db, permission):
        notify_user(db, user, title, message, "Procurement", case.requisition.number)


def notify_procurement_requester(db: Session, case: ProcurementCase, title: str, message: str) -> None:
    notify_user(db, case.requisition.requesting_user, title, message, "Procurement", case.requisition.number)


def notify_procurement_classification_pending(db: Session, req: Requisition) -> None:
    title = f"Procurement para classificar: {req.number}"
    message = (
        f"O budget da requisicao non-stock foi confirmado e o processo esta pronto para classificacao.\n"
        f"N.: {req.number}\n"
        f"Requisitante: {req.requesting_user.full_name}"
    )
    for user in recipients_with_permission(db, "procurement_manage"):
        notify_user(db, user, title, message, "Procurement", req.number)
