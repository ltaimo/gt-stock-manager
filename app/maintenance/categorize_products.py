import json
import os
from pathlib import Path

from sqlalchemy import select

from app.database import SessionLocal
from app.models.core import Category, Product
from app.services.categorization import infer_category, normalize_text


FIXTURE_PATH = Path(__file__).resolve().parents[1] / "fixtures" / "demo_products.json"


def get_or_create_category(db, name: str) -> Category:
    normalized = normalize_text(name)
    category = db.scalar(select(Category).where(Category.normalized_name == normalized))
    if not category:
        category = db.scalar(select(Category).where(Category.name == name))
    if category:
        if category.normalized_name != normalized:
            category.normalized_name = normalized
        return category
    category = Category(name=name, normalized_name=normalized)
    db.add(category)
    db.flush()
    return category


def categorize_database() -> int:
    updated = 0
    with SessionLocal() as db:
        products = db.scalars(select(Product).order_by(Product.name)).all()
        for product in products:
            inferred = infer_category(product.name)
            category = get_or_create_category(db, inferred)
            if product.category_id != category.id:
                product.category_id = category.id
                updated += 1
        db.commit()
    return updated


def categorize_fixture() -> int:
    if not FIXTURE_PATH.exists():
        return 0
    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    updated = 0
    for item in data:
        inferred = infer_category(item.get("name", ""))
        if item.get("category") != inferred:
            item["category"] = inferred
            updated += 1
    FIXTURE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return updated


if __name__ == "__main__":
    db_count = categorize_database()
    fixture_count = 0 if os.getenv("ENVIRONMENT") == "production" else categorize_fixture()
    print(f"Produtos categorizados na base: {db_count}")
    print(f"Produtos atualizados no fixture: {fixture_count}")
