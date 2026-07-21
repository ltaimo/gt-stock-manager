from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.core import Requisition, RequisitionStatus, User
from app.services.inventory import StockError, post_movement, product_warehouse_quantity


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


def approve_requisition(
    req: Requisition,
    approved_quantities: dict[int, float] | None = None,
    review_notes: dict[int, str] | None = None,
    db: Session | None = None,
) -> None:
    if req.status != RequisitionStatus.submitted.value:
        raise StockError("Apenas requisições submetidas podem ser aprovadas.")
    notes = review_notes or {}
    approved_any = False
    partial = False
    warehouse_id = getattr(req, "warehouse_id", None)
    for item in req.items:
        requested = float(item.quantity_requested or 0)
        approved = requested if approved_quantities is None else float(approved_quantities.get(item.id, 0) or 0)
        if approved < 0 or approved > requested:
            raise StockError(f"A quantidade aprovada para {item.product.code} é inválida.")
        rejected = requested - approved
        observation = (notes.get(item.id) or item.review_observation or "").strip()
        if rejected > 0 and not observation:
            raise StockError(
                f"Indique o motivo da rejeição total ou parcial do item {item.product.code} - {item.product.name}."
            )
        available = product_warehouse_quantity(db, item.product, warehouse_id) if db else float(item.product.current_stock or 0)
        if "REQU" in (req.req_type or "").upper() and approved > available:
            raise StockError(f"Stock insuficiente para {item.product.code} - {item.product.name}.")
        item.quantity_issued = approved
        item.quantity_rejected = rejected
        item.review_observation = observation or None
        item.review_status = "Aprovado" if rejected == 0 else "Parcial" if approved > 0 else "Rejeitado"
        approved_any = approved_any or approved > 0
        partial = partial or rejected > 0
    if not approved_any:
        raise StockError("Nenhum item foi aprovado.")
    req.status = RequisitionStatus.approved.value
    if partial:
        req.notes = getattr(req, "notes", None) or "Aprovação parcial. Aguardando emissão dos itens aprovados."


def issue_requisition(
    db: Session,
    req: Requisition,
    actor: User,
    approved_quantities: dict[int, float] | None = None,
    review_notes: dict[int, str] | None = None,
) -> None:
    if req.status != RequisitionStatus.approved.value:
        raise StockError("Apenas requisições aprovadas podem ser emitidas.")
    action = movement_action_for_requisition(req)
    notes = review_notes or {}
    warehouse_id = getattr(req, "warehouse_id", None)

    quantities: dict[int, float] = {}
    for item in req.items:
        requested = float(item.quantity_requested or 0)
        approved = (
            float(item.quantity_issued or 0)
            if approved_quantities is None
            else float(approved_quantities.get(item.id, 0) or 0)
        )
        if approved < 0:
            raise StockError("A quantidade aprovada não pode ser negativa.")
        if approved > requested:
            raise StockError(f"A quantidade aprovada para {item.product.code} excede a quantidade requisitada.")
        rejected = requested - approved
        observation = (notes.get(item.id) or item.review_observation or "").strip()
        if rejected > 0 and not observation:
            raise StockError(
                f"Indique o motivo da rejeição total ou parcial do item {item.product.code} - {item.product.name}."
            )
        quantities[item.id] = approved

    if action == "SAÍDA":
        for item in req.items:
            approved = quantities[item.id]
            if approved and product_warehouse_quantity(db, item.product, warehouse_id) < approved:
                raise StockError(f"Stock insuficiente para {item.product.code} - {item.product.name}.")

    issued_any = False
    partially_issued = False
    for item in req.items:
        requested = float(item.quantity_requested or 0)
        approved = quantities[item.id]
        rejected = requested - approved
        item.quantity_issued = approved
        item.quantity_rejected = rejected
        item.review_observation = (notes.get(item.id) or item.review_observation or "").strip() or None

        if approved <= 0:
            item.review_status = "Rejeitado"
            partially_issued = True
            continue

        if approved < requested:
            item.review_status = "Parcial"
            partially_issued = True
        else:
            item.review_status = "Aprovado"

        issued_any = True
        post_movement(
            db,
            product=item.product,
            action_type=action,
            quantity=approved,
            registered_by=actor,
            destination=item.destination or (req.department.name if req.department else None),
            responsible_person=req.authorization_person,
            requesting_user_id=req.requesting_user_id,
            department_id=req.department_id,
            notes=item.review_observation or item.observation or f"Movimento automático da requisição {req.number}",
            reference_number=req.number,
            adjustment_direction="increase" if action == "ACERTO" else None,
            warehouse_id=warehouse_id,
        )

    if not issued_any:
        raise StockError("Nenhum item foi aprovado para emissão.")

    req.status = RequisitionStatus.partially_issued.value if partially_issued else RequisitionStatus.issued.value
    req.issued_by_id = actor.id
    req.issued_at = datetime.now(timezone.utc)
