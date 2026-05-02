from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.core import MovementAction, Product, StockMovement, User


class StockError(ValueError):
    pass


def signed_quantity(action_type: str, quantity: float, adjustment_direction: str | None = None) -> Decimal:
    qty = Decimal(str(quantity))
    if qty <= 0:
        raise StockError("A quantidade deve ser superior a zero.")
    if action_type in (MovementAction.entrada.value, MovementAction.devolucao.value):
        return qty
    if action_type == MovementAction.saida.value:
        return -qty
    if action_type == MovementAction.acerto.value:
        if adjustment_direction == "increase":
            return qty
        if adjustment_direction == "decrease":
            return -qty
        raise StockError("Acertos exigem direção positiva ou negativa.")
    raise StockError("Tipo de movimento inválido.")


def recalculate_product_stock(db: Session, product: Product) -> None:
    total = db.scalar(
        select(func.coalesce(func.sum(StockMovement.signed_quantity), 0)).where(StockMovement.product_id == product.id)
    )
    entries = db.scalar(
        select(func.coalesce(func.sum(StockMovement.quantity), 0)).where(
            StockMovement.product_id == product.id,
            StockMovement.action_type.in_([MovementAction.entrada.value, MovementAction.devolucao.value]),
        )
    )
    exits = db.scalar(
        select(func.coalesce(func.sum(StockMovement.quantity), 0)).where(
            StockMovement.product_id == product.id,
            StockMovement.action_type == MovementAction.saida.value,
        )
    )
    product.current_stock = total or 0
    product.total_entries = entries or 0
    product.total_exits = exits or 0


def post_movement(
    db: Session,
    *,
    product: Product,
    action_type: str,
    quantity: float,
    registered_by: User,
    destination: str | None = None,
    responsible_person: str | None = None,
    requesting_user_id: int | None = None,
    department_id: int | None = None,
    notes: str | None = None,
    reference_number: str | None = None,
    adjustment_direction: str | None = None,
    override_authorized_by_id: int | None = None,
) -> StockMovement:
    if action_type == MovementAction.acerto.value and not notes:
        raise StockError("Acertos manuais exigem justificação.")

    signed = signed_quantity(action_type, quantity, adjustment_direction)
    available_after = Decimal(str(product.current_stock or 0)) + signed
    if signed < 0 and available_after < 0 and registered_by.role.name != "SuperAdmin":
        raise StockError("Estoque insuficiente para a saída solicitada.")

    movement = StockMovement(
        action_type=action_type,
        product_id=product.id,
        quantity=quantity,
        signed_quantity=signed,
        destination=destination,
        responsible_person=responsible_person,
        requesting_user_id=requesting_user_id,
        registered_by_id=registered_by.id,
        department_id=department_id,
        notes=notes,
        reference_number=reference_number,
        override_authorized_by_id=override_authorized_by_id,
    )
    db.add(movement)
    db.flush()
    recalculate_product_stock(db, product)
    return movement
