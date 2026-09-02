import asyncio
import unittest
from io import BytesIO
from unittest.mock import patch

from fastapi import HTTPException
from fastapi import UploadFile
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.core import ApprovalMatrixRule, Department, ProcurementAttachment, ProcurementCase, Product, Requisition, RequisitionItem, RequisitionStatus, Role, User
from app.routers.procurement import archive_procurement_case, approve_bid_terminal, approve_by_value, approve_tdr_hod, approve_tdr_terminal, can_update_tracker, classify_case, confirm_delivery, create_non_stock, create_replenishment, receive_replenishment, register_po, submit_bid, technical_evaluation_decision, update_tracker, verify_budget
from app.security import has_permission, hash_password
from app.services.procurement import classify_non_stock_approval, classify_procurement, non_stock_approval_label
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

    def test_non_stock_minimum_approval_starts_at_terminal_director(self):
        rule = classify_non_stock_approval(self.db, 1000)

        self.assertEqual(rule.modality, "RFQ")
        self.assertEqual(non_stock_approval_label(rule), "Director do Terminal")

    def test_non_stock_never_uses_stock_manager_as_final_approval(self):
        self.db.add(
            ApprovalMatrixRule(
                min_value=0,
                max_value=5000,
                modality="RFQ",
                final_approval="Gestor de Estoque",
                sort_order=-1,
            )
        )
        self.db.commit()

        rule = classify_non_stock_approval(self.db, 0)

        self.assertEqual(non_stock_approval_label(rule), "Director do Terminal")


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
        terminal_role = Role(name="Director do Terminal", permissions='["procurement_tor_approve_terminal", "procurement_value_approve", "requisitions_all"]')
        finance_role = Role(name="Director Financeiro", permissions='["budget_verify", "procurement_value_approve", "requisitions_all"]')
        procurement_role = Role(name="Procurement Officer", permissions='["procurement_manage", "procurement_archive", "requisitions_all"]')
        department = Department(name="Geral")
        self.db.add_all([role, terminal_role, finance_role, procurement_role, department])
        self.db.flush()
        self.terminal_role = terminal_role
        self.finance_role = finance_role
        self.procurement_role = procurement_role
        self.user = User(
            full_name="Admin",
            username="admin",
            password_hash=hash_password("Admin@12345"),
            role_id=role.id,
            department_id=department.id,
        )
        self.db.add(self.user)
        self.db.flush()
        self.terminal_user = User(
            full_name="Director Terminal",
            username="terminal-director",
            password_hash=hash_password("Admin@12345"),
            role_id=terminal_role.id,
            department_id=department.id,
        )
        self.finance_user = User(
            full_name="Director Financeiro",
            username="finance-director",
            password_hash=hash_password("Admin@12345"),
            role_id=finance_role.id,
            department_id=department.id,
        )
        self.procurement_user = User(
            full_name="Procurement Officer",
            username="procurement-officer",
            password_hash=hash_password("Admin@12345"),
            role_id=procurement_role.id,
            department_id=department.id,
        )
        self.db.add_all([self.terminal_user, self.finance_user, self.procurement_user])
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
                ApprovalMatrixRule(min_value=0, max_value=30000, modality="RFQ", final_approval="Director do Terminal", approver_role_id=terminal_role.id, sort_order=0),
                ApprovalMatrixRule(min_value=30000.01, max_value=None, modality="RFP", final_approval="Director Financeiro", approver_role_id=finance_role.id, sort_order=1),
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

    def test_budget_confirmation_marks_technical_evaluation_as_mandatory(self):
        self.case.tor_status = "Approved"
        self.case.status = "Pending Budget Verification"
        self.case.technical_evaluation_required = False
        self.case.technical_evaluation_status = "Not Required"
        self.db.commit()

        response = verify_budget(
            self.case.id,
            request=None,
            decision="confirm",
            comments="Budget confirmado.",
            db=self.db,
            user=self.finance_user,
        )
        self.db.commit()

        self.assertEqual(response.status_code, 303)
        self.assertEqual(self.case.status, "Pending Procurement Classification")
        self.assertTrue(self.case.technical_evaluation_required)
        self.assertEqual(self.case.technical_evaluation_status, "Pending")
        self.assertEqual(self.case.technical_report_status, "Pending")

    def test_hod_approval_is_not_blocked_by_email_notification_failure(self):
        self.terminal_user.email = "terminal@gtsa.local"
        self.terminal_user.notify_email = True
        self.db.commit()

        with patch("app.services.notifications.send_email", side_effect=RuntimeError("smtp unavailable")):
            response = approve_tdr_hod(
                self.case.id,
                request=None,
                decision="approve",
                comments="Necessidade validada",
                db=self.db,
                user=self.user,
            )
        self.db.commit()

        self.assertEqual(response.status_code, 303)
        self.assertEqual(self.case.tor_status, "Pending Terminal Manager Approval")
        self.assertEqual(self.case.status, "Pending Terminal Manager TdR Approval")

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

        self.assertEqual(self.case.approval_route, "Director do Terminal")
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
        self.assertEqual(requisition.authorization_person, "Director do Terminal")
        self.assertEqual(requisition.procurement_case.approval_route, "Director do Terminal")
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
        self.assertEqual(self.case.status, "Approved for PO")

    def prepare_case_for_bid(self, amount: str = "25000"):
        self.case.tor_status = "Approved"
        self.case.status = "Pending Procurement Classification"
        self.case.budget_confirmed = True
        self.db.commit()
        classify_case(
            self.case.id,
            request=None,
            procurement_officer_id=str(self.procurement_user.id),
            technical_evaluation_required="1",
            db=self.db,
            user=self.procurement_user,
        )
        self.db.commit()
        upload = UploadFile(filename=f"cotacao-{amount}.pdf", file=BytesIO(b"%PDF quotation"))
        asyncio.run(
            submit_bid(
                self.case.id,
                request=None,
                rfq_rfp_tender_number="RFQ-NS-1",
                suppliers_invited="3",
                selected_supplier="Fornecedor Recomendado",
                bid_selected_amount=amount,
                procurement_recommendation="Fornecedor recomendado por conformidade técnica e melhor prazo.",
                comments="3 cotações recebidas",
                quotations=[upload],
                db=self.db,
                user=self.procurement_user,
            )
        )
        self.db.commit()
        technical_evaluation_decision(
            self.case.id,
            request=None,
            decision="approve",
            comments="Cotação cumpre o TdR e especificações técnicas solicitadas.",
            db=self.db,
            user=self.user,
        )
        self.db.commit()

    def test_bid_approved_by_terminal_is_final_when_matrix_assigns_terminal(self):
        self.prepare_case_for_bid("25000")

        approve_bid_terminal(
            self.case.id,
            request=None,
            decision="approve",
            approved_supplier="Fornecedor Recomendado",
            approved_amount="25000",
            comments="Bid aprovado pelo Director do Terminal.",
            db=self.db,
            user=self.terminal_user,
        )
        self.db.commit()

        self.assertEqual(self.case.terminal_bid_status, "Approved")
        self.assertEqual(self.case.approval_route, "Director do Terminal")
        self.assertEqual(self.case.approval_status, "Approved")
        self.assertEqual(self.case.status, "Approved for PO")

    def test_bid_above_terminal_matrix_level_goes_to_configured_value_approver(self):
        self.prepare_case_for_bid("45000")

        approve_bid_terminal(
            self.case.id,
            request=None,
            decision="approve",
            approved_supplier="Fornecedor Recomendado",
            approved_amount="45000",
            comments="Bid validado para escalonamento.",
            db=self.db,
            user=self.terminal_user,
        )
        self.db.commit()

        self.assertEqual(self.case.terminal_bid_status, "Approved")
        self.assertEqual(self.case.approval_route, "Director Financeiro")
        self.assertEqual(self.case.approval_status, "Pending")
        self.assertEqual(self.case.status, "Pending Approval")

        approve_by_value(
            self.case.id,
            request=None,
            decision="approve",
            comments="Aprovado pela matriz existente.",
            db=self.db,
            user=self.finance_user,
        )
        self.db.commit()

        self.assertEqual(self.case.status, "Approved for PO")
        self.assertEqual(self.case.approval_status, "Approved")

    def test_non_stock_procurement_runs_from_bid_to_archive(self):
        self.prepare_case_for_bid("45000")

        approve_bid_terminal(
            self.case.id,
            request=None,
            decision="approve",
            approved_supplier="Fornecedor Recomendado",
            approved_amount="45000",
            comments="Bid validado para escalonamento.",
            db=self.db,
            user=self.terminal_user,
        )
        self.db.commit()
        approve_by_value(
            self.case.id,
            request=None,
            decision="approve",
            comments="Aprovado pela matriz existente.",
            db=self.db,
            user=self.finance_user,
        )
        self.db.commit()
        register_po(
            self.case.id,
            request=None,
            po_number="PO-NS-1",
            po_date=None,
            po_value="45000",
            comments="PO emitida.",
            db=self.db,
            user=self.procurement_user,
        )
        self.db.commit()
        confirm_delivery(
            self.case.id,
            request=None,
            receipt_note="Serviço executado conforme PO e TdR.",
            comments="Entrega confirmada.",
            db=self.db,
            user=self.user,
        )
        self.db.commit()
        archive_procurement_case(
            self.case.id,
            request=None,
            comments="Processo completo e documentado.",
            db=self.db,
            user=self.procurement_user,
        )
        self.db.commit()

        self.assertEqual(self.case.status, "Closed")
        self.assertEqual(self.case.receipt_status, "Completed")
        self.assertEqual(self.case.execution_status, "Delivered")
        self.assertEqual(self.case.archive_status, "Archived")
        self.assertEqual(self.req.status, RequisitionStatus.approved.value)
        self.assertIsNotNone(self.case.closure_date)

    def test_procurement_bid_requires_upload_and_requester_technical_evaluation(self):
        self.case.tor_status = "Approved"
        self.case.status = "Pending Procurement Classification"
        self.case.budget_confirmed = True
        self.db.commit()
        classify_case(
            self.case.id,
            request=None,
            procurement_officer_id=str(self.procurement_user.id),
            technical_evaluation_required=None,
            db=self.db,
            user=self.procurement_user,
        )
        self.db.commit()

        upload = UploadFile(filename="cotacao-a.pdf", file=BytesIO(b"%PDF quotation"))
        response = asyncio.run(
            submit_bid(
                self.case.id,
                request=None,
                rfq_rfp_tender_number="RFQ-NS-2",
                suppliers_invited="3",
                selected_supplier="Fornecedor A",
                bid_selected_amount="25000",
                procurement_recommendation="Recomenda-se a cotação do Fornecedor A por cumprir as especificações.",
                comments=None,
                quotations=[upload],
                db=self.db,
                user=self.procurement_user,
            )
        )
        self.db.commit()

        self.assertEqual(response.status_code, 303)
        self.assertEqual(self.case.status, "Technical Evaluation")
        self.assertEqual(self.case.technical_evaluation_status, "Pending")
        self.assertEqual(self.case.financial_evaluation_status, "Approved")
        self.assertEqual(self.case.bid_analysis_status, "Completed")
        self.assertEqual(self.case.approval_route, "Director do Terminal")
        self.assertEqual(self.db.query(ProcurementAttachment).filter_by(case_id=self.case.id).count(), 1)

        technical_evaluation_decision(
            self.case.id,
            request=None,
            decision="approve",
            comments="Cotação cumpre o TdR e especificações técnicas solicitadas.",
            db=self.db,
            user=self.user,
        )
        self.db.commit()

        self.assertEqual(self.case.status, "Pending Terminal Director Bid Approval")
        self.assertEqual(self.case.technical_evaluation_status, "Approved")

    def test_procurement_officer_submits_bid_directly_from_pending_classification(self):
        self.case.tor_status = "Approved"
        self.case.status = "Pending Procurement Classification"
        self.case.budget_confirmed = True
        self.case.procurement_officer_id = None
        self.db.commit()

        upload = UploadFile(filename="cotacao-direta.pdf", file=BytesIO(b"%PDF quotation"))
        response = asyncio.run(
            submit_bid(
                self.case.id,
                request=None,
                rfq_rfp_tender_number="RFQ-NS-DIRECT",
                suppliers_invited="3",
                selected_supplier="Fornecedor Direto",
                bid_selected_amount="25000",
                procurement_recommendation="Fornecedor recomendado por melhor conformidade técnica.",
                comments=None,
                quotations=[upload],
                db=self.db,
                user=self.procurement_user,
            )
        )
        self.db.commit()

        self.assertEqual(response.status_code, 303)
        self.assertEqual(self.case.procurement_officer_id, self.procurement_user.id)
        self.assertEqual(self.case.status, "Technical Evaluation")
        self.assertEqual(self.case.modality, "RFQ")
        self.assertEqual(self.case.approval_route, "Director do Terminal")
        self.assertEqual(self.case.bid_selected_supplier, "Fornecedor Direto")

    def test_procurement_bid_technical_evaluation_is_limited_to_requester(self):
        self.case.status = "Technical Evaluation"
        self.case.technical_evaluation_status = "Pending"
        self.db.commit()

        with self.assertRaises(HTTPException) as caught:
            technical_evaluation_decision(
                self.case.id,
                request=None,
                decision="approve",
                comments="Tentativa de aprovação por outro utilizador.",
                db=self.db,
                user=self.procurement_user,
            )

        self.assertEqual(caught.exception.status_code, 403)

    def test_premature_po_is_blocked_before_final_approval(self):
        self.prepare_case_for_bid("45000")

        with self.assertRaises(HTTPException) as caught:
            update_tracker(
                self.case.id,
                request=None,
                status="PO Issued",
                approval_status=self.case.approval_status,
                rfq_rfp_tender_number="RFQ-NS-1",
                suppliers_invited="3",
                quotations_received="3",
                technical_evaluation_status="Approved",
                financial_evaluation_status="Approved",
                bid_analysis_status="Completed",
                selected_supplier="Fornecedor Recomendado",
                bid_selected_amount="45000",
                procurement_recommendation="Fornecedor recomendado por conformidade técnica.",
                po_number="PO-PREMATURA",
                po_date=None,
                po_value="45000",
                receipt_status="Pending",
                hse_documents_status="Approved",
                technical_report_status="Approved",
                execution_status="Not Started",
                receipt_note=None,
                archive_status="Pending",
                closure_date=None,
                comments="Tentativa prematura",
                db=self.db,
                user=self.procurement_user,
            )

        self.assertEqual(caught.exception.status_code, 400)
        self.assertIn("aprovação final", caught.exception.detail)

    def test_terminal_can_return_bid_without_destroying_procurement_data(self):
        self.prepare_case_for_bid("25000")

        approve_bid_terminal(
            self.case.id,
            request=None,
            decision="return",
            approved_supplier=None,
            approved_amount=None,
            comments="Corrigir comparação e anexos antes da decisão.",
            db=self.db,
            user=self.terminal_user,
        )
        self.db.commit()

        self.assertEqual(self.case.status, "Returned - Bid Correction")
        self.assertEqual(self.case.terminal_bid_status, "Returned")
        self.assertEqual(self.case.bid_selected_supplier, "Fornecedor Recomendado")
        self.assertEqual(float(self.case.bid_selected_amount), 25000)
        self.assertIn("Fornecedor recomendado", self.case.procurement_recommendation)

    def test_terminal_must_justify_selecting_different_supplier(self):
        self.prepare_case_for_bid("25000")

        with self.assertRaises(HTTPException) as caught:
            approve_bid_terminal(
                self.case.id,
                request=None,
                decision="approve",
                approved_supplier="Fornecedor Alternativo",
                approved_amount="25000",
                comments=None,
                db=self.db,
                user=self.terminal_user,
            )

        self.assertEqual(caught.exception.status_code, 400)
        self.assertIn("Justifique", caught.exception.detail)

        approve_bid_terminal(
            self.case.id,
            request=None,
            decision="approve",
            approved_supplier="Fornecedor Alternativo",
            approved_amount="25000",
            comments="Fornecedor alternativo aprovado por melhor garantia.",
            db=self.db,
            user=self.terminal_user,
        )
        self.db.commit()

        self.assertEqual(self.case.selected_supplier, "Fornecedor Alternativo")


if __name__ == "__main__":
    unittest.main()
