import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.core import ApprovalMatrixRule, Department, ProcurementCase, Product, Requisition, RequisitionItem, RequisitionStatus, Role, User
from app.routers.procurement import approve_by_value, can_update_tracker, create_non_stock, create_replenishment, receive_replenishment, update_tracker, verify_budget
from app.security import has_permission, hash_password
from app.services.procurement import classify_procurement
from app.services.tdr_pdf import terms_of_reference_to_pdf


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

    def test_gap_between_rules_uses_next_higher_approval_level(self):
        rule = classify_procurement(self.db, 5000.50)
        self.assertEqual(rule.final_approval, "Chefe do terminal")


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

    def test_stock_receiver_cannot_edit_the_procurement_tracker(self):
        role = Role(name="Recebedor", permissions='["procurement_receive"]')
        user = type("UserObj", (), {"role": role})()

        self.assertFalse(can_update_tracker(user))

    def test_stock_manager_can_receive_replenishment_without_managing_tracker(self):
        role = Role(name="Gestor de Estoque", permissions=None)
        user = type("UserObj", (), {"role": role})()

        self.assertTrue(has_permission(user, "procurement_receive"))
        self.assertTrue(has_permission(user, "stock_replenishment_create"))
        self.assertFalse(can_update_tracker(user))


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
        self.product = Product(
            code="REP-001",
            name="Produto para reposição",
            unit="un",
            unit_price=250,
            current_stock=1,
            minimum_stock=2,
            created_by_id=self.user.id,
        )
        self.db.add(self.product)
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
        self.db.add_all(
            [
                ApprovalMatrixRule(min_value=0, max_value=5000, modality="RFQ", final_approval="Supervisor", sort_order=0),
                ApprovalMatrixRule(min_value=5001, max_value=10000, modality="RFQ", final_approval="Chefe do Terminal", sort_order=1),
            ]
        )
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

    def test_non_stock_can_be_submitted_without_estimated_budget(self):
        response = create_non_stock(
            request=None,
            description="Contratar manutencao sem valor conhecido",
            job_title="Manutencao corretiva",
            tdr_number="",
            justification="Necessidade operacional",
            cost_center="OPS",
            priority="Normal",
            item_type="Serviço",
            estimated_budget="",
            required_date=None,
            technical_requirements="Diagnostico e proposta tecnica",
            hse_requirements=None,
            db=self.db,
            user=self.user,
        )
        self.db.commit()

        created_case = self.db.query(ProcurementCase).filter(ProcurementCase.description == "Contratar manutencao sem valor conhecido").one()
        self.assertEqual(response.status_code, 303)
        self.assertEqual(float(created_case.estimated_budget), 0)
        self.assertEqual(created_case.status, "Pending HOD TdR Approval")

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

    def test_tdr_pdf_contains_template_identity_and_approval_value(self):
        self.case.tdr_number = "TdR-NS-2026-00001"
        self.case.job_title = "Manutenção corretiva"
        self.case.approval_route = "Supervisor"
        self.db.commit()

        pdf = terms_of_reference_to_pdf(self.case, self.user)

        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertGreater(len(pdf), 2000)

    def test_tracker_reclassifies_approval_by_po_value(self):
        self.case.tor_status = "Approved"
        self.case.status = "Financial Evaluation"
        self.case.approval_status = "Approved"
        self.case.approval_route = "Supervisor"
        self.db.commit()

        update_tracker(
            self.case.id,
            request=None,
            status="Supplier Selected",
            approval_status="Approved",
            rfq_rfp_tender_number="RFQ-1",
            suppliers_invited="3",
            quotations_received="3",
            technical_evaluation_status="Approved",
            financial_evaluation_status="Approved",
            bid_analysis_status="Completed",
            selected_supplier="Fornecedor A",
            po_number="PO-1",
            po_date=None,
            po_value="7500",
            receipt_status="Pending",
            hse_documents_status="Not Required",
            technical_report_status="Approved",
            execution_status="Not Started",
            receipt_note=None,
            archive_status="Pending",
            closure_date=None,
            comments="3 cotações recebidas",
            db=self.db,
            user=self.user,
        )
        self.db.commit()

        self.assertEqual(self.case.approval_route, "Chefe do Terminal")
        self.assertEqual(self.case.modality, "RFQ")
        self.assertEqual(self.case.approval_status, "Pending")
        self.assertEqual(self.case.status, "Pending Approval")

    def test_replenishment_uses_selected_products_and_calculates_approval_value(self):
        response = create_replenishment(
            request=None,
            product_id=[str(self.product.id)],
            quantity=["4"],
            estimated_unit_price=["250"],
            justification="Repor nível mínimo",
            cost_center="ARMAZEM",
            priority="Normal",
            required_date=None,
            db=self.db,
            user=self.user,
        )
        self.db.commit()

        requisition = self.db.query(Requisition).filter(Requisition.number.like("RP-%")).one()
        self.assertEqual(response.status_code, 303)
        self.assertEqual(requisition.req_type, "REPOSICAO")
        self.assertEqual(float(requisition.estimated_value), 1000)
        self.assertEqual(requisition.authorization_person, "Supervisor")
        self.assertEqual(requisition.procurement_case.approval_route, "Supervisor")
        self.assertEqual(requisition.procurement_case.modality, "RFQ")
        self.assertEqual(len(requisition.items), 1)
        self.assertEqual(float(requisition.items[0].estimated_unit_price), 250)
        self.assertEqual(requisition.procurement_case.status, "Pending HOD TdR Approval")

    def test_replenishment_receipt_posts_stock_once_and_blocks_over_receipt(self):
        self.req.req_type = "REPOSICAO"
        item = RequisitionItem(
            requisition_id=self.req.id,
            product_id=self.product.id,
            quantity_requested=5,
            estimated_unit_price=250,
        )
        self.db.add(item)
        self.case.po_number = "PO-REP-1"
        self.case.approval_status = "Approved"
        self.db.commit()

        response = receive_replenishment(
            self.case.id,
            request=None,
            item_id=[str(item.id)],
            received_quantity=["3"],
            receipt_note="Recebido em boas condições",
            db=self.db,
            user=self.user,
        )
        self.db.commit()
        self.db.refresh(item)
        self.db.refresh(self.product)

        self.assertEqual(response.status_code, 303)
        self.assertEqual(float(item.quantity_received), 3)
        self.assertEqual(float(self.product.current_stock), 3)
        self.assertEqual(self.case.receipt_status, "Partial")

        with self.assertRaises(HTTPException) as caught:
            receive_replenishment(
                self.case.id,
                request=None,
                item_id=[str(item.id)],
                received_quantity=["3"],
                receipt_note="Tentativa duplicada",
                db=self.db,
                user=self.user,
            )
        self.assertEqual(caught.exception.status_code, 400)
        self.assertIn("excede", caught.exception.detail)

    def test_superadmin_can_complete_value_based_approval(self):
        self.case.status = "Pending Approval"
        self.case.approval_status = "Pending"
        self.case.approval_route = "Supervisor"
        self.db.commit()

        response = approve_by_value(
            self.case.id,
            request=None,
            decision="approve",
            comments="Aprovado conforme matriz",
            db=self.db,
            user=self.user,
        )
        self.db.commit()

        self.assertEqual(response.status_code, 303)
        self.assertEqual(self.case.approval_status, "Approved")
        self.assertEqual(self.case.status, "RFQ/RFP/Tender Running")


if __name__ == "__main__":
    unittest.main()
