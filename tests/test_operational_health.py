import unittest

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.core import Department, ProcurementCase, Requisition, Role, User
from app.routers.reports import procurement_pending_rows
from app.security import hash_password
from app.services import schema_health


class SchemaHealthTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        with self.engine.begin() as connection:
            connection.execute(text("CREATE TABLE roles (id INTEGER PRIMARY KEY, name VARCHAR(80), permissions TEXT, is_system BOOLEAN)"))
            connection.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, role_id INTEGER, is_active BOOLEAN, notify_email BOOLEAN, notify_whatsapp BOOLEAN, preferred_language VARCHAR(5))"))
            connection.execute(text("CREATE TABLE approval_matrix_rules (id INTEGER PRIMARY KEY, min_value NUMERIC, max_value NUMERIC, modality VARCHAR(80), final_approval VARCHAR(160), approver_role_id INTEGER, is_active BOOLEAN, sort_order INTEGER)"))
            connection.execute(text("CREATE TABLE procurement_cases (id INTEGER PRIMARY KEY, status VARCHAR(80), tor_status VARCHAR(60))"))
            connection.execute(text("CREATE TABLE requisition_items (id INTEGER PRIMARY KEY, quantity_received NUMERIC)"))
            connection.execute(text("CREATE TABLE requisitions (id INTEGER PRIMARY KEY, estimated_value NUMERIC, approver_role_id INTEGER, warehouse_id INTEGER)"))
            connection.execute(text("INSERT INTO approval_matrix_rules (id, min_value, modality, final_approval, is_active, sort_order) VALUES (1, 0, 'RFQ', 'Director Financeiro', true, 0)"))
        self.original_engine = schema_health.engine
        schema_health.engine = self.engine
        self.db = sessionmaker(bind=self.engine)()

    def tearDown(self):
        self.db.close()
        schema_health.engine = self.original_engine
        self.engine.dispose()

    def test_schema_health_flags_missing_procurement_approval_columns(self):
        health = schema_health.collect_schema_health(self.db)

        critical = {(item["table"], item["column"]) for item in health.critical_missing_columns}
        self.assertEqual(health.status, "critical")
        self.assertIn(("procurement_cases", "hod_approved_by_id"), critical)
        self.assertIn(("procurement_cases", "terminal_manager_approved_at"), critical)


class ProcurementPendingReportTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, expire_on_commit=False)()
        role = Role(name="User")
        department = Department(name="Operações")
        self.db.add_all([role, department])
        self.db.flush()
        requester = User(
            full_name="Requisitante",
            username="req",
            password_hash=hash_password("Senha@12345"),
            role_id=role.id,
            department_id=department.id,
        )
        self.db.add(requester)
        self.db.flush()
        requisition = Requisition(
            number="NS-TEST-001",
            requesting_user_id=requester.id,
            department_id=department.id,
            req_type="NS",
            status="Submitted",
        )
        self.db.add(requisition)
        self.db.flush()
        self.case = ProcurementCase(
            requisition_id=requisition.id,
            description="Serviço pendente",
            estimated_budget=1000,
            status="Pending Budget Verification",
            tor_status="Approved",
        )
        self.db.add(self.case)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_procurement_pending_rows_include_owner_and_next_step(self):
        rows = procurement_pending_rows(self.db)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "NS-TEST-001")
        self.assertEqual(rows[0][4], "Director Financeiro")
        self.assertIn("Confirmar budget", rows[0][5])


if __name__ == "__main__":
    unittest.main()
