import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.core import ApprovalMatrixRule, Department, ProcurementCase, Requisition, RequisitionStatus, Role, User
from app.routers.procurement import update_tracker, verify_budget
from app.security import has_permission, hash_password
from app.services.procurement import classify_procurement


class ProcurementMatrixTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, expire_on_commit=False)()
        self.db.add_all(
            [
                ApprovalMatrixRule(min_value=0, max_value=5000, modality="RFQ", final_approval="Supervisor", sort_order=0),
                ApprovalMatrixRule(min_value=5001, max_value=10000, modality="RFQ", final_approval="Chefe do terminal", sort_order=1),
                ApprovalMatrixRule(min_value=1000000.01, max_value=None, modality="Tender formal", final_approval="Administracao / Conselho", sort_order=2),
            ]
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_classifies_procurement_value_by_active_matrix(self):
        low = classify_procurement(self.db, 5000)
        middle = classify_procurement(self.db, 7500)
        high = classify_procurement(self.db, 1500000)

        self.assertEqual(low.final_approval, "Supervisor")
        self.assertEqual(middle.final_approval, "Chefe do terminal")
        self.assertEqual(high.modality, "Tender formal")


class ProcurementPermissionTests(unittest.TestCase):
    def test_user_can_create_stock_and_non_stock_requests_by_default(self):
        role = Role(name="User", permissions=None)
        user = type("UserObj", (), {"role": role})()

        self.assertTrue(has_permission(user, "stock_requisitions_create"))
        self.assertTrue(has_permission(user, "non_stock_requisitions_create"))
        self.assertFalse(has_permission(user, "procurement_manage"))

    def test_operational_manager_can_approve_tdr_as_hod_by_default(self):
        role = Role(name="Gestor Operacional", permissions=None)
        user = type("UserObj", (), {"role": role})()

        self.assertTrue(has_permission(user, "procurement_tor_approve_hod"))


class ProcurementWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, expire_on_commit=False)()
        role = Role(name="SuperAdmin")
        department = Department(name="Geral")
        self.db.add_all([role, department])
        self.db.flush()
        self.user = User(
            full_name="Admin",
            username="admin",
            password_hash=hash_password("Admin@12345"),
            role_id=role.id,
            department_id=department.id,
        )
        self.db.add(self.user)
        self.db.flush()
        self.req = Requisition(
            number="NS-2026-00001",
            requesting_user_id=self.user.id,
            department_id=department.id,
            req_type="NS",
            status=RequisitionStatus.submitted.value,
        )
        self.db.add(self.req)
        self.db.flush()
        self.case = ProcurementCase(
            requisition_id=self.req.id,
            description="Comprar serviço técnico",
            estimated_budget=1000,
            status="Pending HOD TdR Approval",
            tor_status="Pending HOD Approval",
        )
        self.db.add(self.case)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_budget_is_blocked_before_tdr_final_approval(self):
        with self.assertRaises(HTTPException) as caught:
            verify_budget(
                self.case.id,
                request=None,
                decision="confirm",
                comments=None,
                db=self.db,
                user=self.user,
            )

        self.assertEqual(caught.exception.status_code, 400)
        self.assertIn("TdR", caught.exception.detail)

    def test_financial_approval_with_less_than_three_quotes_requires_justification(self):
        self.case.tor_status = "Approved"
        self.case.status = "Financial Evaluation"
        self.db.commit()

        with self.assertRaises(HTTPException) as caught:
            update_tracker(
                self.case.id,
                request=None,
                status="Financial Evaluation",
                approval_status="Approved",
                rfq_rfp_tender_number="RFQ-1",
                suppliers_invited="2",
                quotations_received="2",
                technical_evaluation_status="Approved",
                financial_evaluation_status="Approved",
                bid_analysis_status="Completed",
                selected_supplier="Fornecedor A",
                po_number=None,
                po_date=None,
                po_value=None,
                receipt_status="Pending",
                hse_documents_status="Not Required",
                technical_report_status="Approved",
                execution_status="Not Started",
                receipt_note=None,
                archive_status="Pending",
                closure_date=None,
                comments=None,
                db=self.db,
                user=self.user,
            )

        self.assertEqual(caught.exception.status_code, 400)
        self.assertIn("menos de 3", caught.exception.detail)


if __name__ == "__main__":
    unittest.main()
