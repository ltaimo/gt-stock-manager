from sqlalchemy import inspect, text

from app.database import engine


DEFAULT_DEPARTMENTS = [
    "Geral",
    "Operações",
    "Administração",
    "Manutenção",
    "Economato",
    "Faturação",
    "Armazém",
    "NEMCHEN",
]


def ensure_schema() -> None:
    inspector = inspect(engine)
    additions = []
    tables = inspector.get_table_names()
    if "requisition_items" in tables:
        columns = {column["name"] for column in inspector.get_columns("requisition_items")}
        if "quantity_issued" not in columns:
            additions.append("ALTER TABLE requisition_items ADD COLUMN quantity_issued NUMERIC(12, 2) DEFAULT 0")
        if "quantity_rejected" not in columns:
            additions.append("ALTER TABLE requisition_items ADD COLUMN quantity_rejected NUMERIC(12, 2) DEFAULT 0")
        if "review_status" not in columns:
            additions.append("ALTER TABLE requisition_items ADD COLUMN review_status VARCHAR(30) DEFAULT 'Pendente'")
        if "review_observation" not in columns:
            additions.append("ALTER TABLE requisition_items ADD COLUMN review_observation TEXT")

    with engine.begin() as connection:
        for statement in additions:
            connection.execute(text(statement))
        if "departments" in tables:
            for name in DEFAULT_DEPARTMENTS:
                existing = connection.execute(
                    text("SELECT id FROM departments WHERE lower(name) = lower(:name)"),
                    {"name": name},
                ).first()
                if not existing:
                    connection.execute(
                        text("INSERT INTO departments (name, is_active, created_at) VALUES (:name, true, CURRENT_TIMESTAMP)"),
                        {"name": name},
                    )


if __name__ == "__main__":
    ensure_schema()
