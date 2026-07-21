from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.core import MovementAction, Product, ProductWarehouseStock, StockMovement, User, Warehouse


class StockError(ValueError):
    pass


DEFAULT_WAREHOUSE_NAME = "Armazém Principal"
DEFAULT_WAREHOUSE_CODE = "ARM-PRINCIPAL"


def default_warehouse(db: Session) -> Warehouse:
    warehouse = db.scalar(select(Warehouse).where(Warehouse.is_default == True))
    if warehouse:
        return warehouse

    warehouse = db.scalar(select(Warehouse).where(Warehouse.name.ilike(DEFAULT_WAREHOUSE_NAME)))
    if warehouse:
        warehouse.is_default = True
        warehouse.is_active = True
        if not warehouse.code:
            warehouse.code = DEFAULT_WAREHOUSE_CODE
        db.flush()
        return warehouse

    warehouse = Warehouse(
        name=DEFAULT_WAREHOUSE_NAME,
        code=DEFAULT_WAREHOUSE_CODE,
        is_default=True,
        is_active=True,
    )
    db.add(warehouse)
    db.flush()
    return warehouse


def active_warehouses(db: Session, include_id: int | None = None) -> list[Warehouse]:
    if include_id:
        stmt = select(Warehouse).where((Warehouse.is_active == True) | (Warehouse.id == include_id))
    else:
        stmt = select(Warehouse).where(Warehouse.is_active == True)
    warehouses = db.scalars(stmt.order_by(Warehouse.is_default.desc(), Warehouse.name)).all()
    if warehouses:
        return warehouses
    return [default_warehouse(db)]


def resolve_warehouse(db: Session, warehouse_id: int | None = None) -> Warehouse:
    if warehouse_id:
        warehouse = db.get(Warehouse, warehouse_id)
        if not warehouse or not warehouse.is_active:
            raise StockError("Escolha um armazém ativo.")
        return warehouse
    return default_warehouse(db)


def ensure_product_warehouse_stock(db: Session, product: Product, warehouse: Warehouse) -> ProductWarehouseStock:
    stock = db.scalar(
        select(ProductWarehouseStock)
        .where(
            ProductWarehouseStock.product_id == product.id,
            ProductWarehouseStock.warehouse_id == warehouse.id,
        )
        .with_for_update()
    )
    if stock:
        return stock

    existing_count = db.scalar(
        select(func.count(ProductWarehouseStock.id)).where(ProductWarehouseStock.product_id == product.id)
    ) or 0
    movement_count = db.scalar(
        select(func.count(StockMovement.id)).where(StockMovement.product_id == product.id)
    ) or 0
    initial_quantity = product.current_stock if warehouse.is_default and existing_count == 0 and movement_count > 0 else 0
    stock = ProductWarehouseStock(
        product_id=product.id,
        warehouse_id=warehouse.id,
        quantity=initial_quantity or 0,
    )
    db.add(stock)
    db.flush()
    return stock


def product_warehouse_quantity(db: Session, product: Product, warehouse_id: int | None = None) -> float:
    if not hasattr(db, "scalar"):
        return float(product.current_stock or 0)
    warehouse = resolve_warehouse(db, warehouse_id)
    stock = ensure_product_warehouse_stock(db, product, warehouse)
    return float(stock.quantity or 0)


def warehouse_stock_map(db: Session, products: list[Product]) -> dict[int, dict[int, float]]:
    product_ids = [product.id for product in products if product.id]
    if not product_ids:
        return {}
    rows = db.execute(
        select(
            ProductWarehouseStock.product_id,
            ProductWarehouseStock.warehouse_id,
            ProductWarehouseStock.quantity,
        ).where(ProductWarehouseStock.product_id.in_(product_ids))
    ).all()
    stock_map: dict[int, dict[int, float]] = {product.id: {} for product in products}
    for product_id, warehouse_id, quantity in rows:
        stock_map.setdefault(product_id, {})[warehouse_id] = float(quantity or 0)
    default = default_warehouse(db)
    for product in products:
        stock_map.setdefault(product.id, {})
        if not stock_map[product.id]:
            stock_map[product.id][default.id] = float(product.current_stock or 0)
    return stock_map


def warehouse_breakdown(db: Session, product: Product) -> str:
    rows = db.execute(
        select(Warehouse.name, ProductWarehouseStock.quantity)
        .join(ProductWarehouseStock, ProductWarehouseStock.warehouse_id == Warehouse.id)
        .where(ProductWarehouseStock.product_id == product.id)
        .order_by(Warehouse.is_default.desc(), Warehouse.name)
    ).all()
    parts = [f"{name}: {float(quantity or 0):g}" for name, quantity in rows if float(quantity or 0) != 0]
    if parts:
        return "; ".join(parts)
    return f"{DEFAULT_WAREHOUSE_NAME}: {float(product.current_stock or 0):g}"


def merge_product_warehouse_stock(db: Session, *, source: Product, target: Product) -> None:
    for source_stock in db.scalars(
        select(ProductWarehouseStock).where(ProductWarehouseStock.product_id == source.id)
    ).all():
        target_stock = db.scalar(
            select(ProductWarehouseStock).where(
                ProductWarehouseStock.product_id == target.id,
                ProductWarehouseStock.warehouse_id == source_stock.warehouse_id,
            )
        )
        if target_stock:
            target_stock.quantity = Decimal(str(target_stock.quantity or 0)) + Decimal(str(source_stock.quantity or 0))
            db.delete(source_stock)
        else:
            source_stock.product_id = target.id


def signed_quantity(action_type: str, quantity: float, adjustment_direction: str | None = None) -> Decimal:
    qty = Decimal(str(quantity))
    if qty <= 0:
        raise StockError("A quantidade deve ser superior a zero.")
    if action_type == MovementAction.transferencia.value:
        return Decimal("0")
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
        select(func.coalesce(func.sum(ProductWarehouseStock.quantity), 0)).where(
            ProductWarehouseStock.product_id == product.id
        )
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


def adjust_product_stock(
    db: Session,
    *,
    product: Product,
    target_quantity: float,
    reason: str,
    actor: User,
    warehouse_id: int | None = None,
) -> StockMovement:
    target = Decimal(str(target_quantity))
    if target < 0:
        raise StockError("A quantidade existente não pode ser negativa.")
    clean_reason = " ".join((reason or "").strip().split())
    if not clean_reason:
        raise StockError("Indique o motivo obrigatório para ajustar o stock.")
    if len(clean_reason) > 500:
        raise StockError("O motivo do ajuste não pode exceder 500 caracteres.")

    if hasattr(db, "scalar"):
        product = db.scalar(
            select(Product)
            .where(Product.id == product.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if not product:
            raise StockError("O produto selecionado já não existe.")

    current = Decimal(str(product_warehouse_quantity(db, product, warehouse_id)))
    difference = target - current
    if difference == 0:
        raise StockError("A nova quantidade é igual à quantidade existente.")

    return post_movement(
        db,
        product=product,
        action_type=MovementAction.acerto.value,
        quantity=abs(difference),
        registered_by=actor,
        notes=clean_reason,
        reference_number=f"AJUSTE-{product.code}",
        adjustment_direction="increase" if difference > 0 else "decrease",
        warehouse_id=warehouse_id,
    )


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
    warehouse_id: int | None = None,
    destination_warehouse_id: int | None = None,
) -> StockMovement:
    if not hasattr(db, "scalar"):
        signed = signed_quantity(action_type, quantity, adjustment_direction)
        available_after = Decimal(str(product.current_stock or 0)) + signed
        if signed < 0 and available_after < 0:
            raise StockError("Stock insuficiente para a saída solicitada.")
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
        return movement

    product = db.scalar(
        select(Product)
        .where(Product.id == product.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if not product:
        raise StockError("O produto selecionado já não existe.")
    if action_type == MovementAction.acerto.value and not notes:
        raise StockError("Acertos manuais exigem justificação.")

    signed = signed_quantity(action_type, quantity, adjustment_direction)
    warehouse = resolve_warehouse(db, warehouse_id)
    destination_warehouse = None

    if action_type == MovementAction.transferencia.value:
        destination_warehouse = resolve_warehouse(db, destination_warehouse_id)
        if destination_warehouse.id == warehouse.id:
            raise StockError("Escolha armazéns diferentes para a transferência.")
        source_stock = ensure_product_warehouse_stock(db, product, warehouse)
        target_stock = ensure_product_warehouse_stock(db, product, destination_warehouse)
        qty = Decimal(str(quantity))
        current_source = Decimal(str(source_stock.quantity or 0))
        if current_source < qty:
            raise StockError("Stock insuficiente no armazém de origem.")
        source_stock.quantity = current_source - qty
        target_stock.quantity = Decimal(str(target_stock.quantity or 0)) + qty
        destination = destination or destination_warehouse.name
    else:
        stock = ensure_product_warehouse_stock(db, product, warehouse)
        available_after = Decimal(str(stock.quantity or 0)) + signed
        if signed < 0 and available_after < 0:
            raise StockError("Stock insuficiente para a saída solicitada.")
        stock.quantity = available_after

    movement = StockMovement(
        action_type=action_type,
        product_id=product.id,
        warehouse_id=warehouse.id,
        destination_warehouse_id=destination_warehouse.id if destination_warehouse else None,
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
    db.flush()
    return movement
