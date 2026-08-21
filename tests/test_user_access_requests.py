import unittest

from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.core import AccessRequest, Department, Notification, Role, User
from app.security import hash_password


class UserAccessRequestTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)
        self.db = self.SessionLocal()
        self.admin_role = Role(name="SuperAdmin")
        self.user_role = Role(name="User")
        self.department = Department(name="IT")
        self.db.add_all([self.admin_role, self.user_role, self.department])
        self.db.flush()
        self.admin = User(
            full_name="Admin",
            username="admin",
            email="admin@example.com",
            password_hash=hash_password("Admin@12345"),
            role_id=self.admin_role.id,
            department_id=self.department.id,
        )
        self.target = User(
            full_name="Existing User",
            username="euser",
            email="existing@example.com",
            password_hash=hash_password("OldPass123"),
            role_id=self.user_role.id,
            department_id=self.department.id,
        )
        self.db.add_all([self.admin, self.target])
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

    def login_admin(self):
        response = self.client.post(
            "/login",
            data={"username": "admin", "password": "Admin@12345"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

    def test_public_access_request_creates_pending_request_and_admin_notification(self):
        login_page = self.client.get("/login")
        self.assertIn("/pedido-acesso", login_page.text)

        response = self.client.post(
            "/pedido-acesso",
            data={
                "full_name": "João Silva",
                "email": "joao.silva@example.com",
                "phone": "+258840000000",
                "note": "Operações",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("Pedido enviado com sucesso", response.text)

        with self.SessionLocal() as db:
            access_request = db.scalar(select(AccessRequest).where(AccessRequest.email == "joao.silva@example.com"))
            self.assertIsNotNone(access_request)
            self.assertEqual(access_request.username_suggestion, "jsilva")
            self.assertEqual(access_request.status, "Pending")
            notification = db.scalar(
                select(Notification).where(
                    Notification.user_id == self.admin.id,
                    Notification.module == "Utilizadores",
                    Notification.record_id == f"ACCESS_REQUEST:{access_request.id}",
                )
            )
            self.assertIsNotNone(notification)

    def test_admin_approves_access_request_by_creating_user(self):
        access_request = AccessRequest(
            full_name="Maria Muchanga",
            username_suggestion="mmuchanga",
            email="maria.muchanga@example.com",
            phone="+258850000000",
            note="Financeiro",
        )
        self.db.add(access_request)
        self.db.commit()
        self.login_admin()

        form = self.client.get(f"/utilizadores/novo?access_request_id={access_request.id}")
        self.assertEqual(form.status_code, 200)
        self.assertIn("mmuchanga", form.text)
        self.assertIn("maria.muchanga@example.com", form.text)

        response = self.client.post(
            "/utilizadores/novo",
            data={
                "access_request_id": str(access_request.id),
                "full_name": "Maria Muchanga",
                "username": "mmuchanga",
                "email": "maria.muchanga@example.com",
                "phone": "+258850000000",
                "password": "TempPass123",
                "role_id": str(self.user_role.id),
                "department_id": str(self.department.id),
                "preferred_language": "pt",
                "notify_email": "1",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

        with self.SessionLocal() as db:
            created = db.scalar(select(User).where(User.username == "mmuchanga"))
            treated_request = db.get(AccessRequest, access_request.id)
            self.assertIsNotNone(created)
            self.assertTrue(created.must_reset_password)
            self.assertEqual(treated_request.status, "Approved")
            self.assertEqual(treated_request.user_id, created.id)

        self.client.post("/logout", follow_redirects=False)
        login = self.client.post(
            "/login",
            data={"username": "mmuchanga", "password": "TempPass123"},
            follow_redirects=False,
        )
        self.assertEqual(login.status_code, 303)
        self.assertEqual(login.headers["location"], "/reset-password")

    def test_admin_can_reset_existing_user_password(self):
        self.login_admin()
        response = self.client.post(
            f"/utilizadores/{self.target.id}/editar",
            data={
                "full_name": "Existing User",
                "email": "existing@example.com",
                "phone": "",
                "role_id": str(self.user_role.id),
                "department_id": str(self.department.id),
                "is_active": "true",
                "preferred_language": "pt",
                "password": "NewPass123",
                "confirm_password": "NewPass123",
                "force_password_reset": "1",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

        self.client.post("/logout", follow_redirects=False)
        old_login = self.client.post(
            "/login",
            data={"username": "euser", "password": "OldPass123"},
            follow_redirects=False,
        )
        self.assertEqual(old_login.status_code, 400)

        new_login = self.client.post(
            "/login",
            data={"username": "euser", "password": "NewPass123"},
            follow_redirects=False,
        )
        self.assertEqual(new_login.status_code, 303)
        self.assertEqual(new_login.headers["location"], "/reset-password")
        blocked_dashboard = self.client.get("/dashboard", follow_redirects=False)
        self.assertEqual(blocked_dashboard.status_code, 303)
        self.assertEqual(blocked_dashboard.headers["location"], "/reset-password")

        reset = self.client.post(
            "/reset-password",
            data={"password": "FinalPass123", "confirm_password": "FinalPass123"},
            follow_redirects=False,
        )
        self.assertEqual(reset.status_code, 303)
        self.assertEqual(reset.headers["location"], "/dashboard")


if __name__ == "__main__":
    unittest.main()
