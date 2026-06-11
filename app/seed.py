from sqlalchemy import or_, select

from app.database import Base, SessionLocal, engine
from app.models.core import Category, Department, Role, User
from app.security import hash_password
from app.services.categorization import normalize_text


def seed() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        for name in ["SuperAdmin", "Admin", "Editor", "User", "Gestor de Estoque", "Chefe do Terminal"]:
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
        if not db.scalar(select(User).where(User.username == "superadmin")):
            db.add(
                User(
                    full_name="Administrador Principal",
                    username="superadmin",
                    email="superadmin@gt.co.mz",
                    password_hash=hash_password("Admin@12345"),
                    role_id=super_role.id,
                    department_id=geral.id,
                )
            )
        db.commit()
        print("Configuração base concluída. Apenas o superadmin é criado automaticamente.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
