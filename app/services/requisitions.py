from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.core import Requisition, RequisitionStatus, User
from app.services.inventory import StockError, post_movement


def next_requisition_number(db: Session) -> str:
    year = datetime.now(timezone.utc).year
    count = db.scalar(select(func.count(Requisition.id)).where(Requisition.number.like(f"REQ-{year}-%"))) or 0
    return f"REQ-{year}-{count + 1:05d}"


def assert_can_view_requisition(user: User, req: Requisition) -> None:
    if user.role.name in {"SuperAdmin", "Admin", "Editor", "Gestor de Estoque", "Chefe do Terminal"}:
        return
    if req.requesting_user_id != user.id:
        raise PermissionError("Sem permissão para ver esta requisição.")


def movement_action_for_requisition(req: Requisition) -> str:
    req_type = (req.req_type or "").upper()
    if "DEVOL" in req_type:
        return "DEVOLUÇÃO"
    if "REQU" in req_type:
        return "SAÍDA"
    return "ACERTO"


def issue_requisition(db: Session, req: Requisition, actor: User) -> None:
    if req.status != RequisitionStatus.approved.value:
        raise StockError("Apenas requisições aprovadas podem ser emitidas.")
    action = movement_action_for_requisition(req)
    if action == "SAÍDA":
        for item in req.items:
            if float(item.product.current_stock or 0) < float(item.quantity_requested or 0):
                raise StockError(f"Estoque insuficiente para {item.product.code} - {item.product.name}.")

    for item in req.items:
        post_movement(
            db,
            product=item.product,
            action_type=action,
            quantity=float(item.quantity_requested),
            registered_by=actor,
            destination=item.destination or (req.department.name if req.department else None),
            responsible_person=req.authorization_person,
            requesting_user_id=req.requesting_user_id,
            department_id=req.department_id,
            notes=item.observation or f"Movimento automático da requisição {req.number}",
            reference_number=req.number,
            adjustment_direction="increase" if action == "ACERTO" else None,
        )
    req.status = RequisitionStatus.issued.value
    req.issued_by_id = actor.id
    req.issued_at = datetime.now(timezone.utc)
