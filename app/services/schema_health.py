from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.database import Base, engine
from app.models.core import Role


CRITICAL_PROCUREMENT_COLUMNS = {
    "procurement_cases": {
        "tor_status",
        "hod_approved_by_id",
        "hod_approved_at",
        "terminal_manager_approved_by_id",
        "terminal_manager_approved_at",
        "budget_confirmed",
        "budget_verified_by_id",
        "procurement_officer_id",
        "approval_route",
        "approval_status",
        "procurement_recommendation",
        "bid_selected_supplier",
        "bid_selected_amount",
        "terminal_bid_status",
        "terminal_bid_approved_by_id",
        "terminal_bid_approved_at",
        "terminal_bid_comments",
        "po_value",
        "receipt_status",
        "archive_status",
    },
    "requisition_items": {
        "quantity_received",
        "quantity_rejected",
        "review_status",
        "review_observation",
    },
    "approval_matrix_rules": {"approver_role_id"},
    "requisitions": {"estimated_value", "approver_role_id", "warehouse_id"},
    "roles": {"permissions", "is_system"},
    "users": {"notify_email", "notify_whatsapp", "preferred_language"},
}


@dataclass(frozen=True)
class SchemaHealth:
    status: str
    missing_tables: list[str]
    missing_columns: list[dict[str, str]]
    critical_missing_columns: list[dict[str, str]]
    active_matrix_rules: int
    open_procurement_cases: int
    matrix_rules_without_role: int
    matrix_roles_without_active_users: list[str]


def collect_schema_health(db: Session) -> SchemaHealth:
    inspector = inspect(engine)
    actual_tables = set(inspector.get_table_names())
    expected_tables = set(Base.metadata.tables)
    missing_tables = sorted(expected_tables - actual_tables)

    missing_columns: list[dict[str, str]] = []
    for table_name, table in sorted(Base.metadata.tables.items()):
        if table_name not in actual_tables:
            continue
        actual_columns = {column["name"] for column in inspector.get_columns(table_name)}
        for column in sorted(set(table.columns.keys()) - actual_columns):
            missing_columns.append({"table": table_name, "column": column})

    critical_missing_columns: list[dict[str, str]] = []
    for table_name, columns in CRITICAL_PROCUREMENT_COLUMNS.items():
        if table_name not in actual_tables:
            critical_missing_columns.extend({"table": table_name, "column": column} for column in sorted(columns))
            continue
        actual_columns = {column["name"] for column in inspector.get_columns(table_name)}
        critical_missing_columns.extend(
            {"table": table_name, "column": column}
            for column in sorted(columns - actual_columns)
        )

    active_rules = []
    if "approval_matrix_rules" in actual_tables:
        matrix_columns = {column["name"] for column in inspector.get_columns("approval_matrix_rules")}
        if {"id", "is_active", "approver_role_id"}.issubset(matrix_columns):
            sort_column = "sort_order" if "sort_order" in matrix_columns else "id"
            active_rules = [
                dict(row._mapping)
                for row in db.execute(
                    text(
                        f"""
                        SELECT id, approver_role_id
                        FROM approval_matrix_rules
                        WHERE is_active = true
                        ORDER BY {sort_column}, id
                        """
                    )
                ).all()
            ]
    active_matrix_rules = len(active_rules)
    matrix_rules_without_role = len([rule for rule in active_rules if not rule["approver_role_id"]])

    active_users_by_role = set()
    if "users" in actual_tables:
        user_columns = {column["name"] for column in inspector.get_columns("users")}
        if {"role_id", "is_active"}.issubset(user_columns):
            active_users_by_role = {
                role_id
                for (role_id,) in db.execute(
                    text("SELECT DISTINCT role_id FROM users WHERE is_active = true AND role_id IS NOT NULL")
                ).all()
            }
    matrix_roles_without_active_users: list[str] = []
    seen_roles: set[int] = set()
    for rule in active_rules:
        approver_role_id = rule["approver_role_id"]
        if not approver_role_id or approver_role_id in seen_roles:
            continue
        seen_roles.add(approver_role_id)
        if approver_role_id not in active_users_by_role:
            role = db.get(Role, approver_role_id) if "roles" in actual_tables else None
            matrix_roles_without_active_users.append(role.name if role else f"role_id={approver_role_id}")

    open_count = 0
    if "procurement_cases" in actual_tables:
        procurement_columns = {column["name"] for column in inspector.get_columns("procurement_cases")}
        if "status" in procurement_columns:
            open_count = db.execute(
                text("SELECT count(*) FROM procurement_cases WHERE status NOT IN ('Closed', 'Cancelled')")
            ).scalar_one()

    status = "ok"
    if missing_tables or critical_missing_columns or active_matrix_rules == 0:
        status = "critical"
    elif missing_columns or matrix_rules_without_role or matrix_roles_without_active_users:
        status = "warning"

    return SchemaHealth(
        status=status,
        missing_tables=missing_tables,
        missing_columns=missing_columns,
        critical_missing_columns=critical_missing_columns,
        active_matrix_rules=active_matrix_rules,
        open_procurement_cases=open_count,
        matrix_rules_without_role=matrix_rules_without_role,
        matrix_roles_without_active_users=matrix_roles_without_active_users,
    )
