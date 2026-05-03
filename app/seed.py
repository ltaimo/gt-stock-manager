from sqlalchemy import select

from app.database import Base, SessionLocal, engine
from app.models.core import Category, Department, Product, Role, StockMovement, User
from app.security import hash_password
from app.services.categorization import normalize_text
from app.services.inventory import post_movement


def seed() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        for name in ["SuperAdmin", "Admin", "Editor", "User", "Gestor de Estoque", "Chefe do Terminal"]:
            if not db.scalar(select(Role).where(Role.name == name)):
                db.add(Role(name=name))
        db.flush()

        departments = ["Geral", "Operações", "Administração", "Manutenção", "Economato"]
        for name in departments:
            if not db.scalar(select(Department).where(Department.name == name)):
                db.add(Department(name=name))
        db.flush()

        categories = ["Material de Escritório", "Limpeza", "Consumíveis", "Equipamento"]
        for name in categories:
            normalized = normalize_text(name)
            if not db.scalar(select(Category).where(Category.normalized_name == normalized)):
                db.add(Category(name=name, normalized_name=normalized))
        db.flush()

        super_role = db.scalar(select(Role).where(Role.name == "SuperAdmin"))
        geral = db.scalar(select(Department).where(Department.name == "Geral"))
        if not db.scalar(select(User).where(User.username == "superadmin")):
            db.add(
                User(
                    full_name="Administrador Principal",
                    username="superadmin",
                    email="superadmin@example.local",
                    password_hash=hash_password("Admin@12345"),
                    role_id=super_role.id,
                    department_id=geral.id,
                )
            )
        it = db.scalar(select(Department).where(Department.name == "IT")) or geral
        if not db.scalar(select(User).where(User.username == "admin")):
            db.add(
                User(
                    full_name="Layton Taimo",
                    username="admin",
                    email="layton.taimo@example.local",
                    password_hash=hash_password("admin123"),
                    role_id=super_role.id,
                    department_id=it.id,
                    must_reset_password=True,
                )
            )
        gestor_role = db.scalar(select(Role).where(Role.name == "Gestor de Estoque"))
        chefe_role = db.scalar(select(Role).where(Role.name == "Chefe do Terminal"))
        economato = db.scalar(select(Department).where(Department.name == "Economato")) or geral
        operacoes = db.scalar(select(Department).where(Department.name == "Operações")) or geral
        if gestor_role and not db.scalar(select(User).where(User.username == "gestor.stock")):
            db.add(
                User(
                    full_name="Gestor de Estoque",
                    username="gestor.stock",
                    email="gestor.stock@example.local",
                    password_hash=hash_password("gestor123"),
                    role_id=gestor_role.id,
                    department_id=economato.id,
                    must_reset_password=True,
                )
            )
        if chefe_role and not db.scalar(select(User).where(User.username == "chefe.terminal")):
            db.add(
                User(
                    full_name="Chefe do Terminal",
                    username="chefe.terminal",
                    email="chefe.terminal@example.local",
                    password_hash=hash_password("chefe123"),
                    role_id=chefe_role.id,
                    department_id=operacoes.id,
                    must_reset_password=True,
                )
            )
        db.flush()

        creator = db.scalar(select(User).where(User.username == "superadmin"))
        samples = [
            ("PAP-A4", "Papel A4 80g", "Material de Escritório", "resma", 25, 10),
            ("CAN-AZ", "Caneta Azul", "Material de Escritório", "un", 120, 30),
            ("DET-01", "Detergente Multiuso", "Limpeza", "lt", 8, 10),
            ("TON-HP", "Toner HP 85A", "Consumíveis", "un", 3, 4),
        ]
        for code, name, category_name, unit, stock, minimum in samples:
            if db.scalar(select(Product).where(Product.code == code)):
                continue
            category = db.scalar(select(Category).where(Category.name == category_name))
            product = Product(
                code=code,
                name=name,
                category_id=category.id,
                unit=unit,
                current_stock=0,
                minimum_stock=minimum,
                total_entries=0,
                total_exits=0,
                created_by_id=creator.id,
            )
            db.add(product)
            db.flush()
            post_movement(
                db,
                product=product,
                action_type="ENTRADA",
                quantity=stock,
                registered_by=creator,
                notes="Stock inicial de demonstração",
                reference_number="SEED",
            )
        for product in db.scalars(select(Product)).all():
            has_movement = db.scalar(select(StockMovement).where(StockMovement.product_id == product.id).limit(1))
            if not has_movement and float(product.current_stock or 0) > 0:
                stock = float(product.current_stock)
                product.current_stock = 0
                product.total_entries = 0
                product.total_exits = 0
                post_movement(
                    db,
                    product=product,
                    action_type="ENTRADA",
                    quantity=stock,
                    registered_by=creator,
                    notes="Stock inicial reconciliado para movimentos",
                    reference_number="RECONCILIAÇÃO",
                )
        db.commit()
        print("Seed concluído. Login: superadmin / Admin@12345")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
