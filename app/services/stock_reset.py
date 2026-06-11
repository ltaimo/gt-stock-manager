from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.core import Product, User
from app.services.inventory import post_movement


def reset_all_stock(db: Session, actor: User) -> dict:
    affected = 0
    total_removed = 0.0
    total_corrected = 0.0

    products = db.scalars(select(Product).order_by(Product.id)).all()
    for product in products:
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

    return {
        "products_affected": affected,
        "quantity_removed": total_removed,
        "negative_quantity_corrected": total_corrected,
    }
