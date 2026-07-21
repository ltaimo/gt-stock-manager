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

APPROVAL_ROLE_ALIASES = {
    "Supervisor": "Supervisor",
    "Chefe do Terminal": "Chefe do Terminal",
    "Chefe do terminal": "Chefe do Terminal",
    "Diretor + Financeiro": "Director Financeiro",
    "Director + Financeiro": "Director Financeiro",
    "Direção Geral": "Administrador Delegado",
    "Direcao Geral": "Administrador Delegado",
    "Direccao Geral": "Administrador Delegado",
    "Administração / Conselho": "PCA",
    "Administracao / Conselho": "PCA",
}


def _role_permissions(role_name: str, stored_permissions: str | None) -> set[str]:
    try:
        if stored_permissions:
            configured = set(json.loads(stored_permissions))
            if configured or role_name not in DEFAULT_ROLE_PERMISSIONS:
                return configured
    except (TypeError, ValueError):
        pass
    return set(DEFAULT_ROLE_PERMISSIONS.get(role_name, set()))


def _matrix_role_name(label: str | None) -> str | None:
    if not label:
        return None
    clean_label = label.strip()
    for source, target in APPROVAL_ROLE_ALIASES.items():
        if clean_label.casefold() == source.casefold():
            return target
    return clean_label


def _rule_matches_role(rule, role_id: int | None, role_name: str | None) -> bool:
    expected = (role_name or "").strip().casefold()
    if role_id and rule["approver_role_id"] == role_id:
        return True
    return bool(expected and (rule["final_approval"] or "").strip().casefold() == expected)


def _rule_rank_for_assignment(rules: list[dict], approver_role_id: int | None, approver_label: str | None, amount) -> int | None:
    if amount is not None:
        try:
            numeric_amount = float(amount or 0)
        except (TypeError, ValueError):
            numeric_amount = 0
        for index, rule in enumerate(rules):
            min_value = float(rule["min_value"] or 0)
            max_value = rule["max_value"]
            if numeric_amount >= min_value and (max_value is None or numeric_amount <= float(max_value)):
                return index
    mapped_label = _matrix_role_name(approver_label)
    for index, rule in enumerate(rules):
        if _rule_matches_role(rule, approver_role_id, mapped_label):
            return index
    return None


def _highest_role_rank(rules: list[dict], role_id: int | None, role_name: str | None) -> int | None:
    ranks = [index for index, rule in enumerate(rules) if _rule_matches_role(rule, role_id, role_name)]
    return max(ranks) if ranks else None


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
    if "stock_movements" in tables:
        columns = {column["name"] for column in inspector.get_columns("stock_movements")}
        if "warehouse_id" not in columns:
            additions.append("ALTER TABLE stock_movements ADD COLUMN warehouse_id INTEGER")
        if "destination_warehouse_id" not in columns:
            additions.append("ALTER TABLE stock_movements ADD COLUMN destination_warehouse_id INTEGER")
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
        if "warehouse_id" not in columns:
            additions.append("ALTER TABLE requisitions ADD COLUMN warehouse_id INTEGER")
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
        if "operation_type" not in columns:
            additions.append("ALTER TABLE internal_operation_records ADD COLUMN operation_type VARCHAR(40)")
        if "fuel_type" not in columns:
            additions.append("ALTER TABLE internal_operation_records ADD COLUMN fuel_type VARCHAR(120)")
        if "asset_name" not in columns:
            additions.append("ALTER TABLE internal_operation_records ADD COLUMN asset_name VARCHAR(160)")
        if "odometer_reading" not in columns:
            additions.append("ALTER TABLE internal_operation_records ADD COLUMN odometer_reading NUMERIC(14, 2)")
        if "meter_reading" not in columns:
            additions.append("ALTER TABLE internal_operation_records ADD COLUMN meter_reading NUMERIC(14, 2)")
        if "payment_method" not in columns:
            additions.append("ALTER TABLE internal_operation_records ADD COLUMN payment_method VARCHAR(80)")

    with engine.begin() as connection:
        if "warehouses" not in tables:
            connection.execute(
                text(
                    """
                    CREATE TABLE warehouses (
                        id INTEGER PRIMARY KEY,
                        name VARCHAR(120) UNIQUE NOT NULL,
                        code VARCHAR(40) UNIQUE,
                        location VARCHAR(160),
                        is_default BOOLEAN DEFAULT false,
                        is_active BOOLEAN DEFAULT true,
                        created_at TIMESTAMP
                    )
                    """
                )
            )
        if "product_warehouse_stocks" not in tables:
            connection.execute(
                text(
                    """
                    CREATE TABLE product_warehouse_stocks (
                        id INTEGER PRIMARY KEY,
                        product_id INTEGER NOT NULL REFERENCES products(id),
                        warehouse_id INTEGER NOT NULL REFERENCES warehouses(id),
                        quantity NUMERIC(12, 2) DEFAULT 0,
                        updated_at TIMESTAMP,
                        UNIQUE(product_id, warehouse_id)
                    )
                    """
                )
            )
            connection.execute(text("CREATE INDEX ix_product_warehouse_stocks_product_id ON product_warehouse_stocks (product_id)"))
            connection.execute(text("CREATE INDEX ix_product_warehouse_stocks_warehouse_id ON product_warehouse_stocks (warehouse_id)"))
        for statement in additions:
            connection.execute(text(statement))
        current_tables = set(inspect(connection).get_table_names())
        if "warehouses" in current_tables:
            default_warehouse = connection.execute(
                text("SELECT id FROM warehouses WHERE is_default = true LIMIT 1")
            ).first()
            if not default_warehouse:
                default_warehouse = connection.execute(
                    text("SELECT id FROM warehouses WHERE lower(name) = lower(:name) LIMIT 1"),
                    {"name": "Armazém Principal"},
                ).first()
            if default_warehouse:
                default_warehouse_id = default_warehouse[0]
                connection.execute(
                    text(
                        """
                        UPDATE warehouses
                        SET is_default = true, is_active = true
                        WHERE id = :warehouse_id
                        """
                    ),
                    {"warehouse_id": default_warehouse_id},
                )
            else:
                connection.execute(
                    text(
                        """
                        INSERT INTO warehouses (name, code, is_default, is_active, created_at)
                        VALUES (:name, :code, true, true, CURRENT_TIMESTAMP)
                        """
                    ),
                    {"name": "Armazém Principal", "code": "ARM-PRINCIPAL"},
                )
                default_warehouse_id = connection.execute(
                    text("SELECT id FROM warehouses WHERE is_default = true LIMIT 1")
                ).scalar_one()

            if "stock_movements" in current_tables:
                movement_columns = {column["name"] for column in inspect(connection).get_columns("stock_movements")}
                if "warehouse_id" in movement_columns:
                    connection.execute(
                        text(
                            """
                            UPDATE stock_movements
                            SET warehouse_id = :warehouse_id
                            WHERE warehouse_id IS NULL
                            """
                        ),
                        {"warehouse_id": default_warehouse_id},
                    )
            if "requisitions" in current_tables:
                requisition_columns = {column["name"] for column in inspect(connection).get_columns("requisitions")}
                if "warehouse_id" in requisition_columns:
                    if "req_type" in requisition_columns:
                        connection.execute(
                            text(
                                """
                                UPDATE requisitions
                                SET warehouse_id = :warehouse_id
                                WHERE warehouse_id IS NULL
                                  AND (req_type IS NULL OR req_type <> 'NS')
                                """
                            ),
                            {"warehouse_id": default_warehouse_id},
                        )
                    else:
                        connection.execute(
                            text(
                                """
                                UPDATE requisitions
                                SET warehouse_id = :warehouse_id
                                WHERE warehouse_id IS NULL
                                """
                            ),
                            {"warehouse_id": default_warehouse_id},
                        )
            if {"products", "product_warehouse_stocks"}.issubset(current_tables):
                connection.execute(
                    text(
                        """
                        INSERT INTO product_warehouse_stocks (product_id, warehouse_id, quantity, updated_at)
                        SELECT products.id, :warehouse_id, coalesce(products.current_stock, 0), CURRENT_TIMESTAMP
                        FROM products
                        WHERE NOT EXISTS (
                            SELECT 1
                            FROM product_warehouse_stocks
                            WHERE product_warehouse_stocks.product_id = products.id
                              AND product_warehouse_stocks.warehouse_id = :warehouse_id
                        )
                        """
                    ),
                    {"warehouse_id": default_warehouse_id},
                )
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
        if "internal_operation_records" in tables:
            connection.execute(
                text(
                    """
                    UPDATE internal_operation_records
                    SET operation_type = CASE lower(kind)
                        WHEN 'fuel' THEN 'fuel_purchase_storage'
                        WHEN 'water' THEN 'water_purchase'
                        WHEN 'energy' THEN 'energy_purchase'
                        ELSE operation_type
                    END
                    WHERE operation_type IS NULL OR trim(operation_type) = ''
                    """
                )
            )
            current_internal_columns = {column["name"] for column in inspect(connection).get_columns("internal_operation_records")}
            if "unit" in current_internal_columns:
                connection.execute(
                    text(
                        """
                        UPDATE internal_operation_records
                        SET unit = CASE lower(kind)
                            WHEN 'fuel' THEN 'L'
                            WHEN 'water' THEN 'L'
                            WHEN 'energy' THEN 'kWh'
                            ELSE unit
                        END
                        WHERE unit IS NULL
                           OR trim(unit) = ''
                           OR (lower(kind) IN ('fuel', 'water', 'energy') AND lower(unit) = 'un')
                        """
                    )
                )
        if "roles" in tables:
            role_columns = {column["name"] for column in inspect(connection).get_columns("roles")}
            for role_name, permissions in DEFAULT_ROLE_PERMISSIONS.items():
                existing = connection.execute(
                    text("SELECT id, permissions FROM roles WHERE lower(name) = lower(:name)"),
                    {"name": role_name},
                ).first()
                if existing:
                    existing_role = existing._mapping
                    current_permissions = _role_permissions(role_name, existing_role["permissions"])
                    updated_permissions = current_permissions | set(permissions)
                    if role_name != "SuperAdmin" and updated_permissions:
                        connection.execute(
                            text("UPDATE roles SET permissions = :permissions WHERE id = :role_id"),
                            {"permissions": json.dumps(sorted(updated_permissions)), "role_id": existing_role["id"]},
                        )
                    continue
                params = {
                    "name": role_name,
                    "permissions": json.dumps(sorted(permissions)) if role_name != "SuperAdmin" else None,
                }
                if "permissions" in role_columns and "is_system" in role_columns:
                    connection.execute(
                        text("INSERT INTO roles (name, permissions, is_system) VALUES (:name, :permissions, true)"),
                        params,
                    )
                elif "permissions" in role_columns:
                    connection.execute(
                        text("INSERT INTO roles (name, permissions) VALUES (:name, :permissions)"),
                        params,
                    )
                else:
                    connection.execute(text("INSERT INTO roles (name) VALUES (:name)"), {"name": role_name})
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
            for source_label, target_role in APPROVAL_ROLE_ALIASES.items():
                connection.execute(
                    text(
                        """
                        UPDATE approval_matrix_rules
                        SET approver_role_id = (
                            SELECT roles.id FROM roles
                            WHERE lower(roles.name) = lower(:target_role)
                            LIMIT 1
                        )
                        WHERE approver_role_id IS NULL
                          AND lower(final_approval) = lower(:source_label)
                        """
                    ),
                    {"source_label": source_label, "target_role": target_role},
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
            for source_label, target_role in APPROVAL_ROLE_ALIASES.items():
                connection.execute(
                    text(
                        """
                        UPDATE requisitions
                        SET approver_role_id = (
                            SELECT roles.id FROM roles
                            WHERE lower(roles.name) = lower(:target_role)
                            LIMIT 1
                        )
                        WHERE approver_role_id IS NULL
                          AND authorization_person IS NOT NULL
                          AND lower(authorization_person) = lower(:source_label)
                        """
                    ),
                    {"source_label": source_label, "target_role": target_role},
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
                permissions = _role_permissions(role_name, stored_permissions)
                updated = permissions | required
                if updated != permissions:
                    connection.execute(
                        text("UPDATE roles SET permissions = :permissions WHERE id = :role_id"),
                        {"permissions": json.dumps(sorted(updated)), "role_id": role_id},
                    )
            if "notifications" in tables:
                connection.execute(
                    text(
                        """
                        UPDATE notifications
                        SET module = 'Requisicoes'
                        WHERE lower(module) LIKE 'requisi%'
                        """
                    )
                )
                connection.execute(
                    text(
                        """
                        UPDATE notifications
                        SET is_read = true, read_at = CURRENT_TIMESTAMP
                        WHERE is_read = false
                          AND record_id IS NOT NULL
                          AND id NOT IN (
                              SELECT keep_id FROM (
                                  SELECT max(id) AS keep_id
                                  FROM notifications
                                  WHERE is_read = false
                                    AND record_id IS NOT NULL
                                  GROUP BY user_id, module, record_id
                              )
                          )
                        """
                    )
                )
            if {"notifications", "users", "requisitions", "roles"}.issubset(set(tables)):
                matrix_rows = [
                    dict(row._mapping)
                    for row in connection.execute(
                        text(
                            """
                            SELECT id, min_value, max_value, sort_order,
                                   final_approval, approver_role_id
                            FROM approval_matrix_rules
                            WHERE is_active = true
                            ORDER BY sort_order, min_value, id
                            """
                        )
                    ).all()
                ]
                stale_notifications = connection.execute(
                    text(
                        """
                        SELECT notifications.id, roles.name, roles.permissions, users.role_id,
                               requisitions.authorization_person, requisitions.approver_role_id,
                               requisitions.estimated_value
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
                for (
                    notification_id,
                    role_name,
                    stored_permissions,
                    user_role_id,
                    approver_label,
                    approver_role_id,
                    estimated_value,
                ) in stale_notifications:
                    permissions = _role_permissions(role_name, stored_permissions)
                    required_rank = _rule_rank_for_assignment(matrix_rows, approver_role_id, approver_label, estimated_value)
                    user_rank = _highest_role_rank(matrix_rows, user_role_id, role_name)
                    can_approve = (
                        role_name == "SuperAdmin"
                        or (
                            "requisitions_review" in permissions
                            and required_rank is not None
                            and user_rank is not None
                            and user_rank >= required_rank
                        )
                    )
                    if not can_approve:
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
