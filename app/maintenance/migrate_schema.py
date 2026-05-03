from sqlalchemy import inspect, text

from app.database import engine


def ensure_schema() -> None:
    inspector = inspect(engine)
    if "requisition_items" not in inspector.get_table_names():
        return

    columns = {column["name"] for column in inspector.get_columns("requisition_items")}
    additions = []
    if "quantity_issued" not in columns:
        additions.append("ALTER TABLE requisition_items ADD COLUMN quantity_issued NUMERIC(12, 2) DEFAULT 0")
    if "review_status" not in columns:
        additions.append("ALTER TABLE requisition_items ADD COLUMN review_status VARCHAR(30) DEFAULT 'Pendente'")
    if "review_observation" not in columns:
        additions.append("ALTER TABLE requisition_items ADD COLUMN review_observation TEXT")

    if not additions:
        return

    with engine.begin() as connection:
        for statement in additions:
            connection.execute(text(statement))


if __name__ == "__main__":
    ensure_schema()
