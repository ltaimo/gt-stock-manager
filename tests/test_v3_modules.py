import json
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.core import Department, HseRecord, InternalOperationOption, InternalOperationRecord, Role, User
from app.security import hash_password


class V3ModuleFlowTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.db = self.SessionLocal()
        self.department = Department(name="Operacoes")
        self.role = Role(
            name="V3 Manager",
            permissions=json.dumps(
                [
                    "hse_view",
                    "hse_records_create",
                    "hse_records_edit",
                    "hse_workflow_manage",
                    "hse_records_close",
                    "hse_reports",
                    "internal_ops_view",
                    "internal_ops_create",
                    "internal_ops_edit",
                    "internal_ops_approve",
                    "internal_ops_reports",
                    "settings_manage",
                ]
            ),
        )
        self.viewer_role = Role(name="V3 Viewer", permissions=json.dumps(["hse_view", "internal_ops_view"]))
        self.db.add_all([self.department, self.role, self.viewer_role])
        self.db.flush()
        self.user = User(
            full_name="V3 Manager",
            username="v3manager",
            password_hash=hash_password("Test@12345"),
            role_id=self.role.id,
            department_id=self.department.id,
            notify_email=False,
        )
        self.viewer = User(
            full_name="V3 Viewer",
            username="v3viewer",
            password_hash=hash_password("Test@12345"),
            role_id=self.viewer_role.id,
            department_id=self.department.id,
            notify_email=False,
        )
        self.db.add_all([self.user, self.viewer])
        self.db.commit()
        app.dependency_overrides[get_db] = self.override_db
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.client.close()
        self.db.close()
        self.engine.dispose()

    def override_db(self):
        db = self.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    def login(self, username="v3manager"):
        response = self.client.post(
            "/login",
            data={"username": username, "password": "Test@12345"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

    def test_hse_record_create_and_workflow_update(self):
        self.login()
        created = self.client.post(
            "/hse/registos",
            data={
                "module": "incidents",
                "title": "Derrame pequeno",
                "description": "Derrame controlado na zona operacional.",
                "priority": "High",
                "owner_id": str(self.user.id),
                "department_id": str(self.department.id),
                "due_date": "2026-07-20",
            },
            follow_redirects=False,
        )
        self.assertEqual(created.status_code, 303)
        self.db.expire_all()
        record = self.db.scalar(select(HseRecord).where(HseRecord.module == "incidents"))
        self.assertIsNotNone(record)
        self.assertTrue(record.number.startswith("HSE-INC-"))

        updated = self.client.post(
            f"/hse/registos/{record.id}/estado",
            data={"status": "Closed", "progress": "100", "update_note": "Ação verificada e encerrada."},
            follow_redirects=False,
        )
        self.assertEqual(updated.status_code, 303)
        self.db.expire_all()
        record = self.db.get(HseRecord, record.id)
        self.assertEqual(record.status, "Closed")
        self.assertEqual(record.progress, 100)
        self.assertEqual(record.closed_by_id, self.user.id)

    def test_hse_viewer_cannot_create_record(self):
        self.login("v3viewer")
        response = self.client.post(
            "/hse/registos",
            data={"module": "incidents", "title": "Sem permissao"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 403)

    def test_v3_module_hubs_render_on_entry_pages_and_dashboard(self):
        self.login()
        hse = self.client.get("/hse")
        self.assertEqual(hse.status_code, 200)
        self.assertIn("/hse?module=incidents#hse-form", hse.text)
        self.assertIn("action-hub hse-hub", hse.text)
        self.assertIn("Escolha uma", hse.text)
        self.assertNotIn('name="title" maxlength="220" required', hse.text)
        hse_selected = self.client.get("/hse?module=incidents")
        self.assertIn('name="title" maxlength="220" required', hse_selected.text)

        operations = self.client.get("/operacoes-internas")
        self.assertEqual(operations.status_code, 200)
        self.assertIn("/operacoes-internas?kind=fuel#internal-ops-form", operations.text)
        self.assertIn("action-hub ops-hub", operations.text)
        self.assertIn("Escolha uma", operations.text)
        self.assertNotIn('name="description" maxlength="220" required', operations.text)
        operations_selected = self.client.get("/operacoes-internas?kind=fuel")
        self.assertIn('name="description" maxlength="220" required', operations_selected.text)
        self.assertIn('type="hidden" name="kind" value="fuel"', operations_selected.text)
        self.assertNotIn('select name="kind"', operations_selected.text)

        dashboard = self.client.get("/dashboard")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn("module-switchboard", dashboard.text)
        self.assertIn("/hse", dashboard.text)
        self.assertIn("/operacoes-internas", dashboard.text)

    def test_internal_operation_options_are_configured_and_used_in_fuel_form(self):
        self.login()
        created = self.client.post(
            "/configuracoes/operacoes-internas/opcoes",
            data={"option_type": "fuel_type", "name": "Diesel 50ppm", "kind": "fuel"},
            follow_redirects=False,
        )
        self.assertEqual(created.status_code, 303)
        created = self.client.post(
            "/configuracoes/operacoes-internas/opcoes",
            data={"option_type": "asset", "name": "Empilhadeira 01", "kind": "fuel"},
            follow_redirects=False,
        )
        self.assertEqual(created.status_code, 303)
        self.db.expire_all()
        self.assertIsNotNone(self.db.scalar(select(InternalOperationOption).where(InternalOperationOption.name == "Diesel 50ppm")))

        form = self.client.get("/operacoes-internas?kind=fuel")
        self.assertEqual(form.status_code, 200)
        self.assertIn("Diesel 50ppm", form.text)
        self.assertIn("Empilhadeira 01", form.text)

    def test_internal_operation_create_validate_and_report(self):
        self.login()
        created = self.client.post(
            "/operacoes-internas/registos",
            data={
                "kind": "fuel",
                "record_date": "2026-07-15",
                "description": "Abastecimento viatura operacional",
                "supplier": "Fornecedor A",
                "fuel_type": "Diesel 50ppm",
                "asset_name": "Empilhadeira 01",
                "quantity": "50",
                "unit": "L",
                "amount": "4500",
                "department_id": str(self.department.id),
                "responsible_person": "Operador",
            },
            follow_redirects=False,
        )
        self.assertEqual(created.status_code, 303)
        self.db.expire_all()
        record = self.db.scalar(select(InternalOperationRecord).where(InternalOperationRecord.kind == "fuel"))
        self.assertIsNotNone(record)
        self.assertTrue(record.number.startswith("FUEL-"))
        self.assertEqual(record.fuel_type, "Diesel 50ppm")
        self.assertEqual(record.asset_name, "Empilhadeira 01")

        validated = self.client.post(
            f"/operacoes-internas/registos/{record.id}/validar",
            data={"status": "Validated"},
            follow_redirects=False,
        )
        self.assertEqual(validated.status_code, 303)
        self.db.expire_all()
        record = self.db.get(InternalOperationRecord, record.id)
        self.assertEqual(record.status, "Validated")
        self.assertEqual(record.approved_by_id, self.user.id)

        report = self.client.get("/relatorios/operacoes-internas")
        self.assertEqual(report.status_code, 200)
        self.assertIn("Abastecimento viatura operacional", report.text)


if __name__ == "__main__":
    unittest.main()
