from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.core import Product, ProductWarehouseStock, User
from app.services.inventory import default_warehouse, post_movement


def reset_all_stock(db: Session, actor: User) -> dict:
    affected = 0
    total_removed = 0.0
    total_corrected = 0.0

    products = db.scalars(select(Product).order_by(Product.id)).all()
    supports_warehouse_stock = all(hasattr(db, attr) for attr in ("scalar", "add_all", "flush"))
    default = default_warehouse(db) if supports_warehouse_stock else None
    for product in products:
        if not supports_warehouse_stock:
            current = float(product.current_stock or 0)
            if current == 0:
                continue
            direction = "decrease" if current > 0 else "increase"
            post_movement(
                db,
                product=product,
                action_type="ACERTO",
                quantity=abs(current),
                registered_by=actor,
                notes="Reset total de stock autorizado por SuperAdmin.",
                reference_number="RESET-STOCK",
                adjustment_direction=direction,
            )
            affected += 1
            if current > 0:
                total_removed += current
            else:
                total_corrected += abs(current)
            continue

        stocks = db.scalars(
            select(ProductWarehouseStock)
            .where(ProductWarehouseStock.product_id == product.id)
            .order_by(ProductWarehouseStock.warehouse_id)
        ).all()
        if not stocks and float(product.current_stock or 0) != 0:
            stocks = [
                ProductWarehouseStock(
                    product_id=product.id,
                    warehouse_id=default.id,
                    quantity=product.current_stock,
                )
            ]
            db.add_all(stocks)
            db.flush()

        product_affected = False
        for stock in stocks:
            current = float(stock.quantity or 0)
            if current == 0:
                continue

            direction = "decrease" if current > 0 else "increase"
            post_movement(
                db,
                product=product,
                action_type="ACERTO",
                quantity=abs(current),
                registered_by=actor,
                notes="Reset total de stock autorizado por SuperAdmin.",
                reference_number="RESET-STOCK",
                adjustment_direction=direction,
                warehouse_id=stock.warehouse_id,
            )
            product_affected = True
            if current > 0:
                total_removed += current
            else:
                total_corrected += abs(current)
        if product_affected:
            affected += 1

    return {
        "products_affected": affected,
        "quantity_removed": total_removed,
        "negative_quantity_corrected": total_corrected,
    }
