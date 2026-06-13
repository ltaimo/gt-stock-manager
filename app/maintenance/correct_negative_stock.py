import json

from sqlalchemy import select

from app.database import SessionLocal
from app.models.core import Product, Role, User
from app.services.audit import audit_log
from app.services.inventory import adjust_product_stock
from app.services.transactions import atomic


CORRECTION_REASON = (
    "Correção controlada de saldo negativo legado. "
    "O sistema passa a impedir qualquer saída ou ajuste que resulte em stock negativo."
)


def correct_negative_stock() -> dict:
    db = SessionLocal()
    try:
        actor = db.scalar(
            select(User)
            .join(Role)
            .where(Role.name == "SuperAdmin", User.is_active == True)
            .order_by(User.id)
        )
        if not actor:
            raise RuntimeError("Não existe um SuperAdmin ativo para registar a correção.")

        stock_manager_role = db.scalar(select(Role).where(Role.name == "Gestor de Estoque"))
        products = db.scalars(
            select(Product)
            .where(Product.current_stock < 0)
            .order_by(Product.id)
            .with_for_update()
        ).all()
        corrected = []
        with atomic(db):
            permission_added = False
            if stock_manager_role and stock_manager_role.permissions:
                permissions = set(json.loads(stock_manager_role.permissions))
                if "stock_adjust" not in permissions:
                    old_permissions = sorted(permissions)
                    permissions.add("stock_adjust")
                    stock_manager_role.permissions = json.dumps(sorted(permissions))
                    permission_added = True
                    audit_log(
                        db,
                        actor,
                        "Concedeu permissão de ajuste de stock",
                        "Perfis",
                        stock_manager_role.id,
                        old_value={"permissions": old_permissions},
                        new_value={"permissions": sorted(permissions)},
                    )
            for product in products:
                old_quantity = float(product.current_stock or 0)
                movement = adjust_product_stock(
                    db,
                    product=product,
                    target_quantity=0,
                    reason=CORRECTION_REASON,
                    actor=actor,
                )
                audit_log(
                    db,
                    actor,
                    "Corrigiu saldo negativo legado",
                    "Stock",
                    product.id,
                    old_value={"quantity": old_quantity},
                    new_value={
                        "quantity": 0,
                        "reason": CORRECTION_REASON,
                        "movement_id": movement.id,
                    },
                )
                corrected.append(
                    {
                        "product_id": product.id,
                        "code": product.code,
                        "old_quantity": old_quantity,
                        "new_quantity": 0,
                    }
                )
        return {
            "corrected": corrected,
            "count": len(corrected),
            "stock_manager_permission_added": permission_added,
        }
    finally:
        db.close()


if __name__ == "__main__":
    result = correct_negative_stock()
    print(f"Produtos corrigidos: {result['count']}")
    print(f"Permissão do Gestor de Estoque atualizada: {result['stock_manager_permission_added']}")
    for item in result["corrected"]:
        print(f"{item['code']}: {item['old_quantity']:g} -> 0")
