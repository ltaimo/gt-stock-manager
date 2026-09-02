import json
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.core import Department, DepartmentDailyReport, HseRecord, InternalOperationOption, InternalOperationRecord, Notification, Product, Role, User
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
        self.ops_reports_role = Role(name="Ops Reports Only", permissions=json.dumps(["internal_ops_reports"]))
        self.replenishment_role = Role(name="Reposicao Manager", permissions=json.dumps(["stock_replenishment_create"]))
        self.limited_hse_role = Role(name="Limited HSE Creator", permissions=json.dumps(["hse_view", "hse_records_create"]))
        self.limited_hse_workflow_role = Role(name="Limited HSE Workflow", permissions=json.dumps(["hse_view", "hse_workflow_manage"]))
        self.db.add_all([self.department, self.role, self.viewer_role, self.ops_reports_role, self.replenishment_role, self.limited_hse_role, self.limited_hse_workflow_role])
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
        self.replenishment_user = User(
            full_name="Stock Replenishment",
            username="replenisher",
            password_hash=hash_password("Test@12345"),
            role_id=self.replenishment_role.id,
            department_id=self.department.id,
            notify_email=False,
        )
        self.ops_reports_user = User(
            full_name="Ops Reports",
            username="opsreports",
            password_hash=hash_password("Test@12345"),
            role_id=self.ops_reports_role.id,
            department_id=self.department.id,
            notify_email=False,
        )
        self.limited_hse_user = User(
            full_name="Limited HSE Creator",
            username="limitedhse",
            password_hash=hash_password("Test@12345"),
            role_id=self.limited_hse_role.id,
            department_id=self.department.id,
            notify_email=False,
        )
        self.limited_hse_workflow_user = User(
            full_name="Limited HSE Workflow",
            username="limitedworkflow",
            password_hash=hash_password("Test@12345"),
            role_id=self.limited_hse_workflow_role.id,
            department_id=self.department.id,
            notify_email=False,
        )
        self.db.add_all([self.user, self.viewer, self.ops_reports_user, self.replenishment_user, self.limited_hse_user, self.limited_hse_workflow_user])
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

    def test_hse_module_specific_permission_is_enforced(self):
        self.login("limitedhse")
        page = self.client.get("/hse?module=permits")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Sem permissão", page.text)
        self.assertNotIn('name="title" maxlength="220" required', page.text)

        response = self.client.post(
            "/hse/registos",
            data={"module": "permits", "title": "Permissao sem perfil", "priority": "Normal"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 403)

    def test_hse_workflow_respects_module_specific_permission(self):
        record = HseRecord(
            number="HSE-PTW-2026-0001",
            module="permits",
            title="Permissao de trabalho",
            priority="Normal",
            created_by_id=self.user.id,
        )
        self.db.add(record)
        self.db.commit()

        self.login("limitedworkflow")
        page = self.client.get("/hse?module=permits")
        self.assertEqual(page.status_code, 200)
        self.assertNotIn(f'action="/hse/registos/{record.id}/estado"', page.text)

        response = self.client.post(
            f"/hse/registos/{record.id}/estado",
            data={"status": "In Progress", "progress": "10", "update_note": "Tentativa sem permissao"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 403)

    def test_v3_module_hubs_render_on_entry_pages_and_dashboard(self):
        self.login()
        dashboard = self.client.get("/dashboard")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn("/conta", dashboard.text)
        self.assertIn("/reset-password", dashboard.text)
        self.assertIn("user-menu", dashboard.text)

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
        self.assertIn("/operacoes-internas?kind=equipment#internal-ops-form", operations.text)
        self.assertIn("action-hub ops-hub", operations.text)
        self.assertIn("Escolha uma", operations.text)
        self.assertNotIn('name="description" maxlength="220" required', operations.text)
        operations_selected = self.client.get("/operacoes-internas?kind=fuel")
        self.assertIn('name="description" maxlength="220" required', operations_selected.text)
        self.assertIn('type="hidden" name="kind" value="fuel"', operations_selected.text)
        self.assertNotIn('select name="kind"', operations_selected.text)
        self.assertIn('name="operation_type"', operations_selected.text)
        self.assertIn('value="fuel_purchase_storage"', operations_selected.text)
        self.assertIn('value="fuel_refuel"', operations_selected.text)
        self.assertIn('name="odometer_reading"', operations_selected.text)
        self.assertIn('type="hidden" name="unit" value="L"', operations_selected.text)
        equipment_selected = self.client.get("/operacoes-internas?kind=equipment")
        self.assertIn('type="hidden" name="kind" value="equipment"', equipment_selected.text)
        self.assertIn('value="equipment_purchase"', equipment_selected.text)
        self.assertIn('list="internal-equipment-type-options"', equipment_selected.text)

        self.assertIn("module-switchboard", dashboard.text)
        self.assertIn("/hse", dashboard.text)
        self.assertIn("/operacoes-internas", dashboard.text)

        account = self.client.get("/conta")
        self.assertEqual(account.status_code, 200)
        self.assertIn("V3 Manager", account.text)
        self.assertIn("v3manager", account.text)

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
        created = self.client.post(
            "/configuracoes/operacoes-internas/opcoes",
            data={"option_type": "equipment_type", "name": "Ar condicionado", "kind": "equipment"},
            follow_redirects=False,
        )
        self.assertEqual(created.status_code, 303)
        created = self.client.post(
            "/configuracoes/operacoes-internas/opcoes",
            data={"option_type": "location", "name": "Contador Bypass", "kind": "energy"},
            follow_redirects=False,
        )
        self.assertEqual(created.status_code, 303)
        created = self.client.post(
            "/configuracoes/operacoes-internas/opcoes",
            data={"option_type": "payment_method", "name": "Transferencia Bancaria", "kind": ""},
            follow_redirects=False,
        )
        self.assertEqual(created.status_code, 303)
        self.db.expire_all()
        payment_option = self.db.scalar(select(InternalOperationOption).where(InternalOperationOption.name == "Transferencia Bancaria"))
        self.assertIsNotNone(self.db.scalar(select(InternalOperationOption).where(InternalOperationOption.name == "Diesel 50ppm")))
        self.assertIsNotNone(self.db.scalar(select(InternalOperationOption).where(InternalOperationOption.name == "Ar condicionado")))
        self.assertIsNotNone(payment_option)

        settings = self.client.get("/configuracoes")
        self.assertEqual(settings.status_code, 200)
        self.assertIn("settings-hub", settings.text)
        self.assertIn("/configuracoes?section=internal_ops", settings.text)
        self.assertNotIn("ops-setting-form", settings.text)

        internal_settings = self.client.get("/configuracoes?section=internal_ops")
        self.assertEqual(internal_settings.status_code, 200)
        self.assertIn("settings-subhub", internal_settings.text)
        self.assertIn("Tipos de combust", internal_settings.text)
        self.assertIn("Tipos de equipamento", internal_settings.text)
        self.assertIn("M", internal_settings.text)
        self.assertNotIn("ops-setting-form", internal_settings.text)

        fuel_type_settings = self.client.get("/configuracoes?section=internal_ops&internal_group=fuel_type")
        self.assertEqual(fuel_type_settings.status_code, 200)
        self.assertIn("ops-setting-card single", fuel_type_settings.text)
        self.assertIn("ops-setting-form", fuel_type_settings.text)
        self.assertIn("Diesel 50ppm", fuel_type_settings.text)

        form = self.client.get("/operacoes-internas?kind=fuel")
        self.assertEqual(form.status_code, 200)
        self.assertIn("Diesel 50ppm", form.text)
        self.assertIn("Empilhadeira 01", form.text)
        self.assertIn("Transferencia Bancaria", form.text)
        self.assertIn('list="internal-company-options"', form.text)

        energy_form = self.client.get("/operacoes-internas?kind=energy")
        self.assertEqual(energy_form.status_code, 200)
        self.assertIn("Contador Bypass", energy_form.text)
        equipment_form = self.client.get("/operacoes-internas?kind=equipment")
        self.assertEqual(equipment_form.status_code, 200)
        self.assertIn("Ar condicionado", equipment_form.text)

        removed = self.client.post(
            f"/configuracoes/operacoes-internas/opcoes/{payment_option.id}/remover",
            follow_redirects=False,
        )
        self.assertEqual(removed.status_code, 303)
        self.db.expire_all()
        self.assertFalse(self.db.get(InternalOperationOption, payment_option.id).is_active)
        reactivated = self.client.post(
            f"/configuracoes/operacoes-internas/opcoes/{payment_option.id}/ativar",
            follow_redirects=False,
        )
        self.assertEqual(reactivated.status_code, 303)
        self.db.expire_all()
        self.assertTrue(self.db.get(InternalOperationOption, payment_option.id).is_active)

    def test_internal_operation_create_validate_and_report(self):
        self.login()
        missing_odometer = self.client.post(
            "/operacoes-internas/registos",
            data={
                "kind": "fuel",
                "operation_type": "fuel_refuel",
                "description": "Abastecimento sem odometro",
                "fuel_type": "Diesel 50ppm",
                "asset_name": "Empilhadeira 01",
                "quantity": "10",
                "amount": "900",
            },
        )
        self.assertEqual(missing_odometer.status_code, 400)
        self.assertIn("odómetro", missing_odometer.text)

        created = self.client.post(
            "/operacoes-internas/registos",
            data={
                "kind": "fuel",
                "operation_type": "fuel_refuel",
                "record_date": "2026-07-15",
                "description": "Abastecimento viatura operacional",
                "supplier": "Fornecedor A",
                "fuel_type": "Diesel 50ppm",
                "asset_name": "Empilhadeira 01",
                "odometer_reading": "125000",
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
        self.assertEqual(record.operation_type, "fuel_refuel")
        self.assertEqual(record.fuel_type, "Diesel 50ppm")
        self.assertEqual(record.asset_name, "Empilhadeira 01")
        self.assertEqual(float(record.odometer_reading), 125000)
        self.assertEqual(record.unit, "L")

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
        self.assertIn("125000", report.text)

    def test_department_daily_report_create_validate_and_exports(self):
        self.login()
        home = self.client.get("/operacoes-internas")
        self.assertEqual(home.status_code, 200)
        self.assertIn("/operacoes-internas/relatorios-departamentais?department=maintenance", home.text)
        self.assertIn("/operacoes-internas/relatorios-departamentais?department=security", home.text)
        self.assertIn("/operacoes-internas/relatorios-departamentais?department=it", home.text)

        form = self.client.get("/operacoes-internas/relatorios-departamentais?department=maintenance")
        self.assertEqual(form.status_code, 200)
        self.assertIn("Tarefas executadas", form.text)
        self.assertIn("Equipamentos e utilidades", form.text)

        created = self.client.post(
            "/operacoes-internas/relatorios-departamentais",
            data={
                "department_key": "maintenance",
                "report_date": "2026-08-31",
                "shift": "07h00-17h00",
                "prepared_by": "Joao Manuel",
                "supervisor": "Chefe de Manutencao",
                "team": "Angelo Macandza; Pedro Nharo",
                "activities": "Controle de fluxo de agua e reparacao de torneiras.",
                "incidents": "Bomba de incendio em curto circuito.",
                "equipment_status": "Gerador New Way verificado.",
                "readings": "Furo 1 operacional.",
                "pending_actions": "Maquina de soldar urgente.",
                "status": "Submitted",
            },
            follow_redirects=False,
        )
        self.assertEqual(created.status_code, 303)
        self.db.expire_all()
        record = self.db.scalar(select(DepartmentDailyReport).where(DepartmentDailyReport.department_key == "maintenance"))
        self.assertIsNotNone(record)
        self.assertTrue(record.number.startswith("MAN-DR-"))
        self.assertEqual(record.status, "Submitted")

        validated = self.client.post(
            f"/operacoes-internas/relatorios-departamentais/{record.id}/validar",
            data={"status": "Validated"},
            follow_redirects=False,
        )
        self.assertEqual(validated.status_code, 303)
        self.db.expire_all()
        record = self.db.get(DepartmentDailyReport, record.id)
        self.assertEqual(record.status, "Validated")
        self.assertEqual(record.approved_by_id, self.user.id)

        report = self.client.get("/relatorios/operacoes-internas/departamentos?department=maintenance&date_from=2026-08-31&date_to=2026-08-31")
        self.assertEqual(report.status_code, 200)
        self.assertIn("Controle de fluxo", report.text)
        self.assertIn("Maquina de soldar", report.text)

        pdf = self.client.get("/relatorios/operacoes-internas/departamentos?department=maintenance&date_from=2026-08-31&date_to=2026-08-31&export=pdf")
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf.headers["content-type"], "application/pdf")
        self.assertTrue(pdf.content.startswith(b"%PDF"))

        docx = self.client.get("/relatorios/operacoes-internas/departamentos?department=maintenance&date_from=2026-08-31&date_to=2026-08-31&export=docx")
        self.assertEqual(docx.status_code, 200)
        self.assertEqual(docx.headers["content-type"], "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        self.assertTrue(docx.content.startswith(b"PK"))

    def test_report_only_profile_enters_internal_operations_reports_area(self):
        self.login("opsreports")
        lobby = self.client.get("/operacoes-internas")
        self.assertEqual(lobby.status_code, 200)
        self.assertIn("Este perfil tem acesso apenas aos relatórios.", lobby.text)
        self.assertIn("/operacoes-internas/relatorios-departamentais", lobby.text)

        report_area = self.client.get("/operacoes-internas/relatorios-departamentais?department=security")
        self.assertEqual(report_area.status_code, 200)
        self.assertNotIn('name="report_date"', report_area.text)

        consolidated = self.client.get("/relatorios/operacoes-internas/departamentos?department=security")
        self.assertEqual(consolidated.status_code, 200)

    def test_energy_reading_requires_meter_reading_and_uses_kwh(self):
        self.login()
        missing_meter = self.client.post(
            "/operacoes-internas/registos",
            data={
                "kind": "energy",
                "operation_type": "energy_reading",
                "description": "Leitura mensal",
                "asset_name": "Contador Bypass",
                "quantity": "0",
                "amount": "0",
            },
        )
        self.assertEqual(missing_meter.status_code, 400)
        self.assertIn("contador", missing_meter.text)

        created = self.client.post(
            "/operacoes-internas/registos",
            data={
                "kind": "energy",
                "operation_type": "energy_reading",
                "description": "Leitura mensal",
                "asset_name": "Contador Bypass",
                "meter_reading": "3456",
                "quantity": "0",
                "amount": "0",
            },
            follow_redirects=False,
        )
        self.assertEqual(created.status_code, 303)
        self.db.expire_all()
        record = self.db.scalar(select(InternalOperationRecord).where(InternalOperationRecord.kind == "energy"))
        self.assertEqual(record.operation_type, "energy_reading")
        self.assertEqual(float(record.meter_reading), 3456)
        self.assertEqual(record.unit, "kWh")

    def test_equipment_operations_have_specific_validation_and_default_department(self):
        self.login()
        missing_type = self.client.post(
            "/operacoes-internas/registos",
            data={
                "kind": "equipment",
                "operation_type": "equipment_purchase",
                "description": "Compra de equipamento sem tipo",
                "quantity": "1",
                "amount": "12000",
                "payment_method": "Transferencia Bancaria",
            },
        )
        self.assertEqual(missing_type.status_code, 400)
        self.assertIn("tipo/categoria", missing_type.text)

        missing_asset = self.client.post(
            "/operacoes-internas/registos",
            data={
                "kind": "equipment",
                "operation_type": "equipment_maintenance",
                "description": "Manutencao sem ativo",
                "fuel_type": "Ar condicionado",
                "amount": "1500",
                "payment_method": "Transferencia Bancaria",
            },
        )
        self.assertEqual(missing_asset.status_code, 400)
        self.assertIn("ativo", missing_asset.text.lower())

        created = self.client.post(
            "/operacoes-internas/registos",
            data={
                "kind": "equipment",
                "operation_type": "equipment_purchase",
                "description": "Compra de ar condicionado",
                "fuel_type": "Ar condicionado",
                "quantity": "2",
                "amount": "54000",
                "payment_method": "Transferencia Bancaria",
                "responsible_person": "Operacoes",
            },
            follow_redirects=False,
        )
        self.assertEqual(created.status_code, 303)
        self.db.expire_all()
        record = self.db.scalar(select(InternalOperationRecord).where(InternalOperationRecord.kind == "equipment"))
        self.assertIsNotNone(record)
        self.assertTrue(record.number.startswith("EQUIP-"))
        self.assertEqual(record.operation_type, "equipment_purchase")
        self.assertEqual(record.fuel_type, "Ar condicionado")
        self.assertEqual(record.unit, "un")
        self.assertEqual(record.department_id, self.department.id)

    def test_internal_operation_purchase_and_refuel_require_real_values(self):
        self.login()
        invalid_purchase = self.client.post(
            "/operacoes-internas/registos",
            data={
                "kind": "fuel",
                "operation_type": "fuel_purchase_storage",
                "description": "Compra vazia",
                "quantity": "0",
                "amount": "0",
            },
        )
        self.assertEqual(invalid_purchase.status_code, 400)
        self.assertTrue("quantidade" in invalid_purchase.text.lower() or "quantity" in invalid_purchase.text.lower())

        invalid_energy_purchase = self.client.post(
            "/operacoes-internas/registos",
            data={
                "kind": "energy",
                "operation_type": "energy_purchase",
                "description": "Pagamento sem valor",
                "quantity": "0",
                "amount": "0",
            },
        )
        self.assertEqual(invalid_energy_purchase.status_code, 400)
        self.assertTrue("valor" in invalid_energy_purchase.text.lower() or "amount" in invalid_energy_purchase.text.lower())

    def test_internal_operation_missing_subtype_uses_safe_default(self):
        self.login()
        created = self.client.post(
            "/operacoes-internas/registos",
            data={
                "kind": "fuel",
                "description": "Compra sem subtipo explicito",
                "fuel_type": "Diesel 50ppm",
                "quantity": "100",
                "amount": "9000",
                "payment_method": "Cheque",
            },
            follow_redirects=False,
        )
        self.assertEqual(created.status_code, 303)
        self.db.expire_all()
        record = self.db.scalar(
            select(InternalOperationRecord).where(InternalOperationRecord.description == "Compra sem subtipo explicito")
        )
        self.assertEqual(record.operation_type, "fuel_purchase_storage")

    def test_normal_user_can_signal_replenishment_need_and_recipient_opens_prefilled_form(self):
        product = Product(
            code="ZERO-001",
            name="Produto sem stock",
            unit="un",
            current_stock=0,
            minimum_stock=2,
            requires_stock_control=True,
            created_by_id=self.user.id,
        )
        self.db.add(product)
        self.db.commit()

        self.login("v3viewer")
        response = self.client.post(
            f"/produtos/{product.id}/solicitar-reposicao",
            data={"return_to": "/requisicoes/nova"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertIn("/requisicoes/nova?replenishment_signal=", response.headers["location"])
        self.db.expire_all()
        notification = self.db.scalar(
            select(Notification).where(
                Notification.user_id == self.replenishment_user.id,
                Notification.record_id == f"REPLENISH_PRODUCT:{product.id}",
            )
        )
        self.assertIsNotNone(notification)
        self.assertEqual(notification.module, "Procurement")

        self.client.post("/logout", follow_redirects=False)
        self.login("replenisher")
        opened = self.client.get(f"/notificacoes/{notification.id}/abrir", follow_redirects=False)
        self.assertEqual(opened.status_code, 303)
        self.assertEqual(opened.headers["location"], f"/procurement/reposicao/nova?product_id={product.id}")


if __name__ == "__main__":
    unittest.main()
