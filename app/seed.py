import json
import os
from pathlib import Path

from sqlalchemy import or_, select

from app.database import Base, SessionLocal, engine
from app.maintenance.migrate_schema import ensure_schema
from app.models.core import (
    Category,
    Department,
    MovementAction,
    Product,
    RequisitionItem,
    Role,
    Setting,
    StockDocumentProduct,
    StockMovement,
    User,
)
from app.security import hash_password
from app.services.categorization import normalize_text
from app.services.inventory import post_movement, recalculate_product_stock


FIXTURE_DIR = Path(__file__).parent / "fixtures"
AC_TOOLS_FIXTURE = FIXTURE_DIR / "ac_tools_products.json"


def repair_portuguese_labels(db) -> None:
    def legacy_mojibake(value: str) -> str:
        return value.encode("utf-8").decode("latin-1")

    replacements = {
        Department: {
            legacy_mojibake(value): value
            for value in ["Operações", "Administração", "Manutenção", "Faturação", "Armazém"]
        },
        Category: {
            legacy_mojibake(value): value
            for value in [
                "Material de Escritório",
                "Consumíveis",
                "Climatização",
                "Informática e Equipamentos",
                "Consumíveis de Impressão",
                "Equipamentos de Proteção",
                "Material Elétrico e Iluminação",
                "Canalização",
                "Ferramentas e Manutenção",
                "Operações e Diversos",
            ]
        },
    }
    for model, mapping in replacements.items():
        for old_name, new_name in mapping.items():
            current = db.scalar(select(model).where(model.name == old_name))
            conflict = db.scalar(select(model).where(model.name == new_name))
            if current and not conflict:
                current.name = new_name
                if isinstance(current, Category):
                    current.normalized_name = normalize_text(new_name)


def seed_ac_tools_products(db, actor: User) -> int:
    flag_key = "seed_ac_tools_products_20260618"
    if db.scalar(select(Setting).where(Setting.key == flag_key)):
        return 0
    if not AC_TOOLS_FIXTURE.exists():
        return 0

    items = json.loads(AC_TOOLS_FIXTURE.read_text(encoding="utf-8"))
    existing_codes = {code for (code,) in db.execute(select(Product.code)).all()}
    created = 0
    for item in items:
        code = item["code"].strip()
        if code in existing_codes:
            continue

        category_name = item.get("category") or item.get("type") or "Equipamento"
        normalized_category = normalize_text(category_name)
        category = db.scalar(select(Category).where(Category.normalized_name == normalized_category))
        if not category:
            category = Category(name=category_name, normalized_name=normalized_category)
            db.add(category)
            db.flush()

        product = Product(
            code=code,
            name=item["name"].strip(),
            category_id=category.id,
            unit=item.get("unit") or "un",
            unit_price=float(item.get("unit_price") or 0),
            minimum_stock=float(item.get("minimum_stock") or 0),
            created_by_id=actor.id,
        )
        db.add(product)
        db.flush()
        existing_codes.add(code)

        quantity = float(item.get("quantity") or 0)
        if quantity > 0:
            notes = "Stock inicial importado da lista única de ferramentas e ar-condicionados."
            if item.get("location"):
                notes = f"{notes} Localização: {item['location']}."
            post_movement(
                db,
                product=product,
                action_type=MovementAction.entrada.value,
                quantity=quantity,
                registered_by=actor,
                destination=item.get("location") or None,
                notes=notes,
                reference_number=f"LISTA-AC-{code}",
            )
        created += 1

    db.add(Setting(key=flag_key, value=str(created)))
    return created


def consolidate_fixture_duplicate_products(db) -> int:
    if not AC_TOOLS_FIXTURE.exists():
        return 0

    items = json.loads(AC_TOOLS_FIXTURE.read_text(encoding="utf-8"))
    consolidated = 0
    for item in items:
        source_codes = [code for code in item.get("source_codes", []) if code]
        if len(source_codes) <= 1:
            continue

        products = db.scalars(select(Product).where(Product.code.in_(source_codes))).all()
        if len(products) <= 1:
            continue

        canonical = next((product for product in products if product.code == item["code"]), None)
        if canonical is None:
            canonical = sorted(products, key=lambda product: product.code)[0]
        duplicates = [product for product in products if product.id != canonical.id]

        for duplicate in duplicates:
            for movement in db.scalars(select(StockMovement).where(StockMovement.product_id == duplicate.id)).all():
                movement.product_id = canonical.id

            for requisition_item in db.scalars(select(RequisitionItem).where(RequisitionItem.product_id == duplicate.id)).all():
                requisition_item.product_id = canonical.id

            for document_link in db.scalars(select(StockDocumentProduct).where(StockDocumentProduct.product_id == duplicate.id)).all():
                existing_link = db.scalar(
                    select(StockDocumentProduct).where(
                        StockDocumentProduct.document_id == document_link.document_id,
                        StockDocumentProduct.product_id == canonical.id,
                    )
                )
                if existing_link:
                    db.delete(document_link)
                else:
                    document_link.product_id = canonical.id

            db.flush()
            db.delete(duplicate)
            consolidated += 1

        db.flush()
        recalculate_product_stock(db, canonical)

    return consolidated


def seed() -> None:
    Base.metadata.create_all(bind=engine)
    ensure_schema()
    db = SessionLocal()
    try:
        for name in ["SuperAdmin", "Admin", "Editor", "User", "Gestor Operacional", "Gestor de Estoque", "Chefe do Terminal"]:
            if not db.scalar(select(Role).where(Role.name == name)):
                db.add(Role(name=name))
        db.flush()

        departments = [
            "Geral",
            "Operações",
            "Administração",
            "Manutenção",
            "Economato",
            "Faturação",
            "Armazém",
            "NEMCHEN",
        ]
        for name in departments:
            if not db.scalar(select(Department).where(Department.name == name)):
                db.add(Department(name=name))
        db.flush()

        categories = ["Material de Escritório", "Limpeza", "Consumíveis", "Equipamento"]
        for name in categories:
            normalized = normalize_text(name)
            existing = db.scalar(
                select(Category).where(
                    or_(
                        Category.normalized_name == normalized,
                        Category.name == name,
                    )
                )
            )
            if not existing:
                db.add(Category(name=name, normalized_name=normalized))
            elif existing.normalized_name != normalized:
                conflict = db.scalar(
                    select(Category).where(
                        Category.normalized_name == normalized,
                        Category.id != existing.id,
                    )
                )
                if not conflict:
                    existing.normalized_name = normalized
        db.flush()

        super_role = db.scalar(select(Role).where(Role.name == "SuperAdmin"))
        geral = db.scalar(select(Department).where(Department.name == "Geral"))
        superadmin = db.scalar(select(User).where(User.username == "superadmin"))
        if not superadmin:
            initial_password = os.getenv("INITIAL_SUPERADMIN_PASSWORD", "").strip()
            if len(initial_password) < 12:
                raise RuntimeError(
                    "Defina INITIAL_SUPERADMIN_PASSWORD com pelo menos 12 caracteres "
                    "antes de criar o primeiro SuperAdmin."
                )
            superadmin = User(
                full_name="Administrador Principal",
                username="superadmin",
                email="superadmin@gt.co.mz",
                password_hash=hash_password(initial_password),
                role_id=super_role.id,
                department_id=geral.id,
            )
            db.add(superadmin)
            db.flush()

        repair_portuguese_labels(db)
        created_tools = seed_ac_tools_products(db, superadmin)
        consolidated_tools = consolidate_fixture_duplicate_products(db)
        db.commit()
        print(
            "Configuração base concluída. "
            f"Novos produtos da lista AC/ferramentas: {created_tools}. "
            f"Duplicados consolidados: {consolidated_tools}."
        )
    finally:
        db.close()


if __name__ == "__main__":
    seed()
