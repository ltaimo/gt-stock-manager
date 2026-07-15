import json
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.core import (
    ApprovalMatrixRule,
    Department,
    Notification,
    ProcurementCase,
    Product,
    Requisition,
    RequisitionItem,
    Role,
    User,
)
from app.routers.procurement import can_approve_by_matrix
from app.routers.requisitions import can_review_requisition
from app.security import grant_permissions, hash_password
from app.services.notifications import notify_requisition_pending, notify_user


APPROVER_PERMISSIONS = json.dumps(
    ["procurement_value_approve", "requisitions_all", "requisitions_review"]
)


class ApprovalRoutingTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.db = self.SessionLocal()

        self.terminal_role = Role(name="Chefe do Terminal", permissions=APPROVER_PERMISSIONS)
        self.stock_role = Role(name="Gestor de Estoque", permissions=APPROVER_PERMISSIONS)
        self.superadmin_role = Role(name="SuperAdmin")
        department = Department(name="Operacoes")
        self.db.add_all(
            [self.terminal_role, self.stock_role, self.superadmin_role, department]
        )
        self.db.flush()

        self.terminal_user = self._user("Jeronimo Macie", "jmacie", self.terminal_role, department)
        self.stock_user = self._user("Gestor Stock", "stock", self.stock_role, department)
        self.superadmin = self._user("Admin", "admin", self.superadmin_role, department)
        self.requester = self._user("Requester", "requester", self.stock_role, department)
        self.db.flush()

        product = Product(
            code="TEST-001",
            name="Produto",
            unit="un",
            unit_price=100,
            current_stock=20,
            minimum_stock=2,
            created_by_id=self.superadmin.id,
        )
        self.db.add(product)
        self.db.flush()
        self.req = Requisition(
            number="REQ-TEST-001",
            requesting_user_id=self.requester.id,
            department_id=department.id,
            authorization_person=self.terminal_role.name,
            approver_role_id=self.terminal_role.id,
            estimated_value=7500,
            req_type="REQUISICAO",
            status="Submitted",
        )
        self.db.add(self.req)
        self.db.flush()
        self.db.add(
            RequisitionItem(
                requisition_id=self.req.id,
                product_id=product.id,
                quantity_requested=2,
            )
        )
        self.stock_rule = ApprovalMatrixRule(
            min_value=0,
            max_value=5000,
            modality="RFQ",
            final_approval=self.stock_role.name,
            approver_role_id=self.stock_role.id,
            is_active=True,
            sort_order=0,
        )
        self.rule = ApprovalMatrixRule(
            min_value=5001,
            max_value=10000,
            modality="RFQ",
            final_approval=self.terminal_role.name,
            approver_role_id=self.terminal_role.id,
            is_active=True,
            sort_order=1,
        )
        self.db.add_all([self.stock_rule, self.rule])
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

    def _user(self, full_name, username, role, department):
        user = User(
            full_name=full_name,
            username=username,
            password_hash=hash_password("Test@12345"),
            role_id=role.id,
            department_id=department.id,
            notify_email=False,
        )
        self.db.add(user)
        return user

    def login(self, username):
        response = self.client.post(
            "/login",
            data={"username": username, "password": "Test@12345"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

    def test_lower_profile_cannot_review_higher_requisition(self):
        self.assertTrue(can_review_requisition(self.db, self.req, self.terminal_user))
        self.assertFalse(can_review_requisition(self.db, self.req, self.stock_user))
        self.assertTrue(can_review_requisition(self.db, self.req, self.superadmin))

    def test_higher_profile_can_review_lower_requisition(self):
        low_req = Requisition(
            number="REQ-TEST-LOW",
            requesting_user_id=self.req.requesting_user_id,
            department_id=self.req.department_id,
            authorization_person=self.stock_role.name,
            approver_role_id=self.stock_role.id,
            estimated_value=1000,
            req_type="REQUISICAO",
            status="Submitted",
        )
        self.db.add(low_req)
        self.db.commit()

        self.assertTrue(can_review_requisition(self.db, low_req, self.stock_user))
        self.assertTrue(can_review_requisition(self.db, low_req, self.terminal_user))

    def test_legacy_assignment_falls_back_to_profile_name(self):
        self.req.approver_role_id = None
        self.assertTrue(can_review_requisition(self.db, self.req, self.terminal_user))
        self.assertFalse(can_review_requisition(self.db, self.req, self.stock_user))

    def test_pending_notification_only_targets_assigned_profile_and_superadmin(self):
        notify_requisition_pending(self.db, self.req)
        self.db.commit()
        recipient_ids = set(
            self.db.scalars(
                select(Notification.user_id).where(
                    Notification.record_id == self.req.number
                )
            ).all()
        )
        self.assertEqual(
            recipient_ids,
            {self.terminal_user.id, self.superadmin.id},
        )

    def test_pending_notification_is_not_duplicated_for_same_user_and_record(self):
        notify_requisition_pending(self.db, self.req)
        notify_requisition_pending(self.db, self.req)
        self.db.commit()
        count = self.db.scalar(
            select(func.count(Notification.id)).where(
                Notification.user_id == self.terminal_user.id,
                Notification.record_id == self.req.number,
                Notification.is_read == False,
            )
        )
        self.assertEqual(count, 1)

    def test_record_notification_is_updated_when_title_changes_before_read(self):
        notify_user(self.db, self.terminal_user, "Requisicao pendente: REQ-TEST-001", "Primeira", "Requisições", self.req.number)
        notify_user(self.db, self.terminal_user, "Requisicao aprovada: REQ-TEST-001", "Segunda", "Requisicoes", self.req.number)
        self.db.commit()

        notifications = self.db.scalars(
            select(Notification).where(
                Notification.user_id == self.terminal_user.id,
                Notification.record_id == self.req.number,
                Notification.is_read == False,
            )
        ).all()

        self.assertEqual(len(notifications), 1)
        self.assertEqual(notifications[0].module, "Requisicoes")
        self.assertEqual(notifications[0].title, "Requisicao aprovada: REQ-TEST-001")
        self.assertEqual(notifications[0].message, "Segunda")

    def test_open_notification_marks_same_record_notifications_read(self):
        self.db.add_all(
            [
                Notification(
                    user_id=self.terminal_user.id,
                    title="Requisicao pendente: REQ-TEST-001",
                    message="Primeira",
                    module="Requisicoes",
                    record_id=self.req.number,
                ),
                Notification(
                    user_id=self.terminal_user.id,
                    title="Requisicao pendente: REQ-TEST-001",
                    message="Segunda",
                    module="Requisicoes",
                    record_id=self.req.number,
                ),
            ]
        )
        self.db.commit()
        notification = self.db.scalar(select(Notification).where(Notification.user_id == self.terminal_user.id))

        self.login("jmacie")
        response = self.client.get(f"/notificacoes/{notification.id}/abrir", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        self.db.expire_all()
        unread = self.db.scalars(
            select(Notification).where(
                Notification.user_id == self.terminal_user.id,
                Notification.record_id == self.req.number,
                Notification.is_read == False,
            )
        ).all()
        self.assertEqual(unread, [])

    def test_lower_pending_notification_targets_assigned_and_superior_profiles(self):
        low_req = Requisition(
            number="REQ-TEST-LOW-NOTIFY",
            requesting_user_id=self.req.requesting_user_id,
            department_id=self.req.department_id,
            authorization_person=self.stock_role.name,
            approver_role_id=self.stock_role.id,
            estimated_value=1000,
            req_type="REQUISICAO",
            status="Submitted",
        )
        self.db.add(low_req)
        self.db.commit()

        notify_requisition_pending(self.db, low_req)
        self.db.commit()
        recipient_ids = set(
            self.db.scalars(
                select(Notification.user_id).where(
                    Notification.record_id == low_req.number
                )
            ).all()
        )
        self.assertEqual(
            recipient_ids,
            {self.stock_user.id, self.terminal_user.id, self.superadmin.id, self.requester.id},
        )

    def test_detail_page_only_shows_approval_form_to_assigned_profile(self):
        self.login("jmacie")
        allowed = self.client.get(f"/requisicoes/{self.req.id}")
        self.assertEqual(allowed.status_code, 200)
        self.assertIn(f'action="/requisicoes/{self.req.id}/review"', allowed.text)

        self.client.post("/logout", follow_redirects=False)
        self.login("stock")
        denied = self.client.get(f"/requisicoes/{self.req.id}")
        self.assertEqual(denied.status_code, 200)
        self.assertNotIn(f'action="/requisicoes/{self.req.id}/review"', denied.text)
        self.assertIn("atribuído pela matriz", denied.text)

    def test_dashboard_lists_pending_requests_at_or_below_profile_level(self):
        stock_request = Requisition(
            number="REQ-TEST-STOCK",
            requesting_user_id=self.req.requesting_user_id,
            department_id=self.req.department_id,
            authorization_person=self.stock_role.name,
            approver_role_id=self.stock_role.id,
            estimated_value=1000,
            req_type="REQUISICAO",
            status="Submitted",
        )
        self.db.add(stock_request)
        self.db.commit()

        self.login("jmacie")
        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.req.number, response.text)
        self.assertIn(stock_request.number, response.text)

    def test_value_approval_requires_permission_and_matrix_assignment(self):
        case = ProcurementCase(
            requisition_id=self.req.id,
            description="Teste",
            estimated_budget=7500,
            status="Pending Approval",
            approval_status="Pending",
        )
        self.db.add(case)
        self.db.commit()

        self.assertTrue(can_approve_by_matrix(self.db, case, self.terminal_user))
        self.assertFalse(can_approve_by_matrix(self.db, case, self.stock_user))
        self.terminal_role.permissions = json.dumps(
            ["requisitions_all", "requisitions_review"]
        )
        self.assertFalse(can_approve_by_matrix(self.db, case, self.terminal_user))

    def test_assigning_matrix_profile_can_grant_required_permissions(self):
        role = Role(name="Novo Aprovador", permissions=json.dumps(["documents"]))
        added = grant_permissions(
            role,
            {"procurement_value_approve", "requisitions_all", "requisitions_review"},
        )
        self.assertEqual(
            added,
            {"procurement_value_approve", "requisitions_all", "requisitions_review"},
        )
        self.assertEqual(
            set(json.loads(role.permissions)),
            {
                "documents",
                "procurement_value_approve",
                "requisitions_all",
                "requisitions_review",
            },
        )

    def test_editing_matrix_profile_preserves_required_permissions(self):
        self.login("admin")
        response = self.client.post(
            f"/perfis/{self.terminal_role.id}/editar",
            data={
                "name": self.terminal_role.name,
                "permissions": ["documents"],
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.db.expire_all()
        permissions = set(
            json.loads(self.db.get(Role, self.terminal_role.id).permissions)
        )
        self.assertTrue(
            {
                "documents",
                "procurement_value_approve",
                "requisitions_all",
                "requisitions_review",
            }.issubset(permissions)
        )

    def test_profile_used_by_matrix_cannot_be_deleted(self):
        role = Role(name="Aprovador sem utilizador", permissions=APPROVER_PERMISSIONS)
        self.db.add(role)
        self.db.flush()
        self.db.add(
            ApprovalMatrixRule(
                min_value=10001,
                max_value=20000,
                modality="RFP",
                final_approval=role.name,
                approver_role_id=role.id,
                is_active=True,
                sort_order=2,
            )
        )
        self.db.commit()

        self.login("admin")
        response = self.client.post(
            f"/perfis/{role.id}/remover",
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("matriz de aprovações", response.text)


if __name__ == "__main__":
    unittest.main()
