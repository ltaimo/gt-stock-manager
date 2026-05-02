import json
from pathlib import Path

from sqlalchemy import select

from app.database import SessionLocal
from app.models.core import Category, Product, User
from app.services.inventory import post_movement
from app.services.transactions import atomic


FIXTURE = Path(__file__).resolve().parent.parent / "fixtures" / "demo_products.json"


def seed_demo_products() -> None:
    if not FIXTURE.exists():
        print("Fixture de demonstração não encontrada.")
        return
    products = json.loads(FIXTURE.read_text(encoding="utf-8"))
    with SessionLocal() as db:
        actor = db.scalar(select(User).where(User.username == "superadmin")) or db.scalar(select(User).where(User.username == "admin"))
        if not actor:
            print("Utilizador admin não encontrado. Execute app.seed primeiro.")
            return
        created = 0
        with atomic(db):
            for item in products:
                if db.scalar(select(Product).where(Product.code == item["code"])):
                    continue
                category_id = None
                if item.get("category"):
                    normalized = item["category"].strip().lower()
                    category = db.scalar(select(Category).where(Category.normalized_name == normalized))
                    if not category:
                        category = Category(name=item["category"].strip(), normalized_name=normalized)
                        db.add(category)
                        db.flush()
                    category_id = category.id
                product = Product(
                    code=item["code"],
                    name=item["name"],
                    category_id=category_id,
                    unit=item.get("unit") or "un",
                    current_stock=0,
                    minimum_stock=item.get("minimum_stock") or 0,
                    status=item.get("status") or "active",
                    created_by_id=actor.id,
                )
                db.add(product)
                db.flush()
                stock = float(item.get("current_stock") or 0)
                if stock > 0:
                    post_movement(
                        db,
                        product=product,
                        action_type="ENTRADA",
                        quantity=stock,
                        registered_by=actor,
                        notes="Stock inicial de demonstração para Render",
                        reference_number="DEMO-RENDER",
                    )
                created += 1
        print(f"Produtos de demonstração criados: {created}")


if __name__ == "__main__":
    seed_demo_products()
