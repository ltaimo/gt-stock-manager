from sqlalchemy import inspect, text

from app.database import engine
from app.services.procurement import DEFAULT_APPROVAL_MATRIX


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
    if "products" in tables:
        columns = {column["name"] for column in inspector.get_columns("products")}
        if "unit_price" not in columns:
            additions.append("ALTER TABLE products ADD COLUMN unit_price NUMERIC(14, 2) DEFAULT 0")
    if "requisitions" in tables:
        columns = {column["name"] for column in inspector.get_columns("requisitions")}
        if "estimated_value" not in columns:
            additions.append("ALTER TABLE requisitions ADD COLUMN estimated_value NUMERIC(14, 2) DEFAULT 0")
    if "roles" in tables:
        columns = {column["name"] for column in inspector.get_columns("roles")}
        if "permissions" not in columns:
            additions.append("ALTER TABLE roles ADD COLUMN permissions TEXT")
        if "is_system" not in columns:
            additions.append("ALTER TABLE roles ADD COLUMN is_system BOOLEAN DEFAULT false")
    if "users" in tables:
        columns = {column["name"] for column in inspector.get_columns("users")}
        if "phone" not in columns:
            additions.append("ALTER TABLE users ADD COLUMN phone VARCHAR(40)")
        if "notify_email" not in columns:
            additions.append("ALTER TABLE users ADD COLUMN notify_email BOOLEAN DEFAULT true")
        if "notify_whatsapp" not in columns:
            additions.append("ALTER TABLE users ADD COLUMN notify_whatsapp BOOLEAN DEFAULT false")
        if "preferred_language" not in columns:
            additions.append("ALTER TABLE users ADD COLUMN preferred_language VARCHAR(5) DEFAULT 'pt'")
    if "approval_matrix_rules" in tables:
        columns = {column["name"] for column in inspector.get_columns("approval_matrix_rules")}
        if "approver_role_id" not in columns:
            additions.append("ALTER TABLE approval_matrix_rules ADD COLUMN approver_role_id INTEGER REFERENCES roles(id)")
    if "procurement_cases" in tables:
        columns = {column["name"] for column in inspector.get_columns("procurement_cases")}
        procurement_additions = {
            "item_type": "ALTER TABLE procurement_cases ADD COLUMN item_type VARCHAR(40) DEFAULT 'Bem'",
            "tdr_number": "ALTER TABLE procurement_cases ADD COLUMN tdr_number VARCHAR(80)",
            "job_title": "ALTER TABLE procurement_cases ADD COLUMN job_title VARCHAR(220)",
            "technical_requirements": "ALTER TABLE procurement_cases ADD COLUMN technical_requirements TEXT",
            "hse_requirements": "ALTER TABLE procurement_cases ADD COLUMN hse_requirements TEXT",
            "tor_status": "ALTER TABLE procurement_cases ADD COLUMN tor_status VARCHAR(60) DEFAULT 'Pending HOD Approval'",
            "hod_approved_by_id": "ALTER TABLE procurement_cases ADD COLUMN hod_approved_by_id INTEGER REFERENCES users(id)",
            "hod_approved_at": "ALTER TABLE procurement_cases ADD COLUMN hod_approved_at TIMESTAMP",
            "terminal_manager_approved_by_id": "ALTER TABLE procurement_cases ADD COLUMN terminal_manager_approved_by_id INTEGER REFERENCES users(id)",
            "terminal_manager_approved_at": "ALTER TABLE procurement_cases ADD COLUMN terminal_manager_approved_at TIMESTAMP",
            "technical_report_status": "ALTER TABLE procurement_cases ADD COLUMN technical_report_status VARCHAR(60) DEFAULT 'Pending'",
            "hse_documents_status": "ALTER TABLE procurement_cases ADD COLUMN hse_documents_status VARCHAR(60) DEFAULT 'Not Required'",
            "execution_status": "ALTER TABLE procurement_cases ADD COLUMN execution_status VARCHAR(60) DEFAULT 'Not Started'",
            "receipt_note": "ALTER TABLE procurement_cases ADD COLUMN receipt_note TEXT",
            "archive_status": "ALTER TABLE procurement_cases ADD COLUMN archive_status VARCHAR(60) DEFAULT 'Pending'",
        }
        for column, statement in procurement_additions.items():
            if column not in columns:
                additions.append(statement)

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
        if "approval_matrix_rules" in inspector.get_table_names():
            count = connection.execute(text("SELECT count(*) FROM approval_matrix_rules")).scalar() or 0
            if count == 0:
                for sort_order, min_value, max_value, modality, final_approval in DEFAULT_APPROVAL_MATRIX:
                    connection.execute(
                        text(
                            """
                            INSERT INTO approval_matrix_rules
                                (sort_order, min_value, max_value, modality, final_approval, is_active, created_at)
                            VALUES
                                (:sort_order, :min_value, :max_value, :modality, :final_approval, true, CURRENT_TIMESTAMP)
                            """
                        ),
                        {
                            "sort_order": sort_order,
                            "min_value": float(min_value),
                            "max_value": float(max_value) if max_value is not None else None,
                            "modality": modality,
                            "final_approval": final_approval,
                        },
                    )
            connection.execute(
                text(
                    """
                    UPDATE approval_matrix_rules
                    SET approver_role_id = (
                        SELECT roles.id FROM roles
                        WHERE lower(roles.name) = lower(approval_matrix_rules.final_approval)
                        LIMIT 1
                    )
                    WHERE approver_role_id IS NULL
                    """
                )
            )


if __name__ == "__main__":
    ensure_schema()
