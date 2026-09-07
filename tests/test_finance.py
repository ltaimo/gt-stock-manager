import io
import unittest
import zipfile
from datetime import datetime, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.core import (
    Department,
    FinancialDailyImport,
    InternalOperationRecord,
    ProcurementCase,
    Requisition,
    Role,
    User,
)
from app.security import hash_password
from app.services.finance import extract_financial_metrics, monthly_finance_summary


def docx_bytes(text: str) -> bytes:
    xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", xml)
    return buffer.getvalue()


class FinanceModuleTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.db = self.SessionLocal()
        self.department = Department(name="Financeiro")
        self.finance_role = Role(name="Financeiro", permissions='["finance_view", "finance_import"]')
        self.user_role = Role(name="User", permissions="[]")
        self.db.add_all([self.department, self.finance_role, self.user_role])
        self.db.flush()
        self.finance_user = User(
            full_name="Finance User",
            username="finance",
            password_hash=hash_password("Test@12345"),
            role_id=self.finance_role.id,
            department_id=self.department.id,
            notify_email=False,
        )
        self.blocked_user = User(
            full_name="Blocked User",
            username="blocked",
            password_hash=hash_password("Test@12345"),
            role_id=self.user_role.id,
            department_id=self.department.id,
            notify_email=False,
        )
        self.db.add_all([self.finance_user, self.blocked_user])
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

    def login(self, username="finance"):
        response = self.client.post(
            "/login",
            data={"username": username, "password": "Test@12345"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

    def seed_monthly_finance(self):
        stock_req = Requisition(
            number="SR-2026-09-0001",
            request_date=datetime(2026, 9, 3, tzinfo=timezone.utc),
            requesting_user_id=self.finance_user.id,
            department_id=self.department.id,
            estimated_value=200,
            req_type="REQUISIÇÃO",
            status="Approved",
        )
        ns_req = Requisition(
            number="NS-2026-09-0001",
            request_date=datetime(2026, 9, 3, tzinfo=timezone.utc),
            requesting_user_id=self.finance_user.id,
            department_id=self.department.id,
            estimated_value=450,
            req_type="NS",
            status="Approved",
        )
        self.db.add_all([stock_req, ns_req])
        self.db.flush()
        self.db.add(
            ProcurementCase(
                requisition_id=ns_req.id,
                description="Serviço aprovado",
                estimated_budget=450,
                status="PO Issued",
                po_number="PO-2026-1",
                po_value=500,
            )
        )
        self.db.add(
            InternalOperationRecord(
                number="OPS-2026-0001",
                kind="general",
                operation_type="general_purchase",
                record_date=datetime(2026, 9, 3, tzinfo=timezone.utc),
                description="Despesa operacional",
                amount=100,
                created_by_id=self.finance_user.id,
            )
        )
        self.db.add(
            FinancialDailyImport(
                report_date=datetime(2026, 9, 3, tzinfo=timezone.utc),
                period_month="2026-09",
                original_filename="financeiro.docx",
                content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                content=b"docx",
                trucks_in=12,
                trucks_out=10,
                revenue_amount=1000,
                uploaded_by_id=self.finance_user.id,
            )
        )
        self.db.commit()

    def test_finance_module_requires_permission(self):
        self.login("blocked")
        self.assertEqual(self.client.get("/financeiro").status_code, 403)

    def test_finance_dashboard_consolidates_monthly_sources(self):
        self.seed_monthly_finance()
        summary = monthly_finance_summary(self.db, "2026-09")
        self.assertEqual(summary["current"]["stock_requisitions"], 200)
        self.assertEqual(summary["current"]["procurement"], 500)
        self.assertEqual(summary["current"]["internal_ops"], 100)
        self.assertEqual(summary["current"]["total_spend"], 800)
        self.assertEqual(summary["current"]["trucks_in"], 12)
        self.assertEqual(summary["usage_ratio"], 80)

        self.login()
        page = self.client.get("/financeiro?month=2026-09")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Módulo financeiro", page.text)
        self.assertIn("800.00", page.text)
        self.assertIn("Uso sobre receita", page.text)
        self.assertIn("finance-data", page.text)
        self.assertIn("financeDailyTrendChart", page.text)

    def test_financial_daily_docx_upload_extracts_metrics(self):
        self.login()
        response = self.client.post(
            "/financeiro/importacoes",
            data={"report_date": "2026-09-03", "notes": "Relatório diário real."},
            files={
                "document": (
                    "relatorio-financeiro.docx",
                    docx_bytes("Caminhões entraram: 21. Caminhões saíram: 18. Receita: 12345,50 MZN."),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.db.expire_all()
        imported = self.db.scalar(select(FinancialDailyImport))
        self.assertIsNotNone(imported)
        self.assertEqual(imported.period_month, "2026-09")
        self.assertEqual(imported.trucks_in, 21)
        self.assertEqual(imported.trucks_out, 18)
        self.assertEqual(float(imported.revenue_amount), 12345.5)

    def test_financial_metrics_extract_operational_daily_report_values(self):
        metrics = extract_financial_metrics(
            "TOTAL VEICULOS 1163 IMPORTAÇÕES 134 EXPORTAÇÕES / REEXPORTAÇÕES 68 "
            "TRÂNSITO MINERAIS 763 VIATURAS APREENDIDAS:27 Viaturas "
            "LEITURA CONTADOR TERMINAL:13310,12kw SISTEMA IT: Operacional"
        )
        self.assertEqual(metrics["total_vehicles"], 1163)
        self.assertEqual(metrics["imports"], 134)
        self.assertEqual(metrics["exports_reexports"], 68)
        self.assertEqual(metrics["transit_minerals"], 763)
        self.assertEqual(metrics["seized_vehicles"], 27)
        self.assertEqual(metrics["terminal_meter_kwh"], 13310.12)
        self.assertEqual(metrics["it_operational"], 1)

    def test_finance_final_report_exports(self):
        self.seed_monthly_finance()
        self.login()
        pdf = self.client.get("/financeiro/relatorio?month=2026-09&export=pdf")
        self.assertEqual(pdf.status_code, 200)
        self.assertEqual(pdf.headers["content-type"], "application/pdf")
        self.assertTrue(pdf.content.startswith(b"%PDF"))

        docx = self.client.get("/financeiro/relatorio?month=2026-09&export=docx")
        self.assertEqual(docx.status_code, 200)
        self.assertEqual(docx.headers["content-type"], "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        self.assertTrue(docx.content.startswith(b"PK"))

        xlsx = self.client.get("/financeiro/relatorio?month=2026-09&export=xlsx")
        self.assertEqual(xlsx.status_code, 200)
        self.assertEqual(xlsx.headers["content-type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.assertTrue(xlsx.content.startswith(b"PK"))

    def test_dashboard_and_menu_show_finance_for_allowed_profile(self):
        self.login()
        dashboard = self.client.get("/dashboard")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn("/financeiro", dashboard.text)
        self.assertIn("Financeiro do mês", dashboard.text)
