import json

from sqlalchemy import inspect, text

from app.database import engine
from app.security import DEFAULT_ROLE_PERMISSIONS
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
        if "estimated_unit_price" not in columns:
            additions.append("ALTER TABLE requisition_items ADD COLUMN estimated_unit_price NUMERIC(14, 2) DEFAULT 0")
        if "quantity_received" not in columns:
            additions.append("ALTER TABLE requisition_items ADD COLUMN quantity_received NUMERIC(12, 2) DEFAULT 0")
        if "quantity_rejected" not in columns:
            additions.append("ALTER TABLE requisition_items ADD COLUMN quantity_rejected NUMERIC(12, 2) DEFAULT 0")
        if "review_status" not in columns:
            additions.append("ALTER TABLE requisition_items ADD COLUMN review_status VARCHAR(30) DEFAULT 'Pendente'")
        if "review_observation" not in columns:
            additions.append("ALTER TABLE requisition_items ADD COLUMN review_observation TEXT")
    if "products" in tables:
        columns = {column["name"] for column in inspector.get_columns("products")}
        if "name_en" not in columns:
            additions.append("ALTER TABLE products ADD COLUMN name_en VARCHAR(220)")
        if "unit_price" not in columns:
            additions.append("ALTER TABLE products ADD COLUMN unit_price NUMERIC(14, 2) DEFAULT 0")
        if "requires_stock_control" not in columns:
            additions.append("ALTER TABLE products ADD COLUMN requires_stock_control BOOLEAN DEFAULT true")
    if "categories" in tables:
        columns = {column["name"] for column in inspector.get_columns("categories")}
        if "name_en" not in columns:
            additions.append("ALTER TABLE categories ADD COLUMN name_en VARCHAR(120)")
    if "requisitions" in tables:
        columns = {column["name"] for column in inspector.get_columns("requisitions")}
        if "estimated_value" not in columns:
            additions.append("ALTER TABLE requisitions ADD COLUMN estimated_value NUMERIC(14, 2) DEFAULT 0")
        if "approver_role_id" not in columns:
            additions.append("ALTER TABLE requisitions ADD COLUMN approver_role_id INTEGER REFERENCES roles(id)")
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
    if "internal_operation_records" in tables:
        columns = {column["name"] for column in inspector.get_columns("internal_operation_records")}
        if "fuel_type" not in columns:
            additions.append("ALTER TABLE internal_operation_records ADD COLUMN fuel_type VARCHAR(120)")
        if "asset_name" not in columns:
            additions.append("ALTER TABLE internal_operation_records ADD COLUMN asset_name VARCHAR(160)")

    with engine.begin() as connection:
        for statement in additions:
            connection.execute(text(statement))
        if "internal_operation_options" not in tables:
            connection.execute(
                text(
                    """
                    CREATE TABLE internal_operation_options (
                        id INTEGER PRIMARY KEY,
                        option_type VARCHAR(40) NOT NULL,
                        name VARCHAR(160) NOT NULL,
                        kind VARCHAR(30),
                        is_active BOOLEAN DEFAULT true,
                        created_at TIMESTAMP,
                        UNIQUE(option_type, name)
                    )
                    """
                )
            )
            connection.execute(text("CREATE INDEX ix_internal_operation_options_option_type ON internal_operation_options (option_type)"))
            connection.execute(text("CREATE INDEX ix_internal_operation_options_kind ON internal_operation_options (kind)"))
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
        if "procurement_cases" in tables:
            connection.execute(
                text(
                    """
                    UPDATE procurement_cases
                    SET status = 'Pending HOD TdR Approval'
                    WHERE tor_status = 'Pending HOD Approval'
                      AND status = 'Pending Budget Verification'
                    """
                )
            )
            connection.execute(
                text(
                    """
                    UPDATE procurement_cases
                    SET status = 'Pending Terminal Manager TdR Approval'
                    WHERE tor_status = 'Pending Terminal Manager Approval'
                      AND status = 'Pending Budget Verification'
                    """
                )
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
            connection.execute(
                text(
                    """
                    UPDATE requisitions
                    SET approver_role_id = (
                        SELECT roles.id FROM roles
                        WHERE lower(roles.name) = lower(requisitions.authorization_person)
                        LIMIT 1
                    )
                    WHERE approver_role_id IS NULL
                      AND authorization_person IS NOT NULL
                    """
                )
            )
            matrix_roles = connection.execute(
                text(
                    """
                    SELECT DISTINCT roles.id, roles.name, roles.permissions
                    FROM roles
                    JOIN approval_matrix_rules ON approval_matrix_rules.approver_role_id = roles.id
                    WHERE approval_matrix_rules.is_active = true
                    """
                )
            ).all()
            required = {"requisitions_all", "requisitions_review", "procurement_value_approve"}
            for role_id, role_name, stored_permissions in matrix_roles:
                try:
                    permissions = set(json.loads(stored_permissions)) if stored_permissions else set(
                        DEFAULT_ROLE_PERMISSIONS.get(role_name, set())
                    )
                except (TypeError, ValueError):
                    permissions = set(DEFAULT_ROLE_PERMISSIONS.get(role_name, set()))
                updated = permissions | required
                if updated != permissions:
                    connection.execute(
                        text("UPDATE roles SET permissions = :permissions WHERE id = :role_id"),
                        {"permissions": json.dumps(sorted(updated)), "role_id": role_id},
                    )
            if {"notifications", "users", "requisitions", "roles"}.issubset(set(tables)):
                stale_notifications = connection.execute(
                    text(
                        """
                        SELECT notifications.id, roles.name, users.role_id,
                               requisitions.authorization_person, requisitions.approver_role_id
                        FROM notifications
                        JOIN users ON users.id = notifications.user_id
                        JOIN roles ON roles.id = users.role_id
                        JOIN requisitions ON requisitions.number = notifications.record_id
                        WHERE notifications.is_read = false
                          AND notifications.module IN ('Requisicoes', 'Requisições')
                          AND requisitions.status = 'Submitted'
                          AND (
                              lower(notifications.title) LIKE '%pendente%'
                              OR lower(notifications.title) LIKE '%pending%'
                          )
                        """
                    )
                ).all()
                for notification_id, role_name, user_role_id, approver_label, approver_role_id in stale_notifications:
                    assigned = (
                        role_name == "SuperAdmin"
                        or (approver_role_id and user_role_id == approver_role_id)
                        or (
                            not approver_role_id
                            and (not approver_label or role_name.strip().casefold() == approver_label.strip().casefold())
                        )
                    )
                    if not assigned:
                        connection.execute(
                            text(
                                """
                                UPDATE notifications
                                SET is_read = true, read_at = CURRENT_TIMESTAMP
                                WHERE id = :notification_id
                                """
                            ),
                            {"notification_id": notification_id},
                        )


if __name__ == "__main__":
    ensure_schema()
