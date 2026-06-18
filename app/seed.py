import json
from pathlib import Path

from sqlalchemy import or_, select

from app.database import Base, SessionLocal, engine
from app.maintenance.migrate_schema import ensure_schema
from app.models.core import Category, Department, MovementAction, Product, Role, Setting, User
from app.security import hash_password
from app.services.categorization import normalize_text
from app.services.inventory import post_movement


FIXTURE_DIR = Path(__file__).parent / "fixtures"
AC_TOOLS_FIXTURE = FIXTURE_DIR / "ac_tools_products.json"


def repair_portuguese_labels(db) -> None:
    replacements = {
        Department: {
            "OperaÃ§Ãµes": "Operações",
            "AdministraÃ§Ã£o": "Administração",
            "ManutenÃ§Ã£o": "Manutenção",
            "FaturaÃ§Ã£o": "Faturação",
            "ArmazÃ©m": "Armazém",
        },
        Category: {
            "Material de EscritÃ³rio": "Material de Escritório",
            "ConsumÃ­veis": "Consumíveis",
            "ClimatizaÃ§Ã£o": "Climatização",
            "InformÃ¡tica e Equipamentos": "Informática e Equipamentos",
            "ConsumÃ­veis de ImpressÃ£o": "Consumíveis de Impressão",
            "Equipamentos de ProteÃ§Ã£o": "Equipamentos de Proteção",
            "Material ElÃ©trico e IluminaÃ§Ã£o": "Material Elétrico e Iluminação",
            "CanalizaÃ§Ã£o": "Canalização",
            "Ferramentas e ManutenÃ§Ã£o": "Ferramentas e Manutenção",
            "OperaÃ§Ãµes e Diversos": "Operações e Diversos",
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
            superadmin = User(
                full_name="Administrador Principal",
                username="superadmin",
                email="superadmin@gt.co.mz",
                password_hash=hash_password("Admin@12345"),
                role_id=super_role.id,
                department_id=geral.id,
            )
            db.add(superadmin)
            db.flush()

        repair_portuguese_labels(db)
        created_tools = seed_ac_tools_products(db, superadmin)
        db.commit()
        print(f"Configuração base concluída. Novos produtos da lista AC/ferramentas: {created_tools}.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
