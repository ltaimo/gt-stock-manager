import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.core import Department, Role, User
from app.security import hash_password
from app.services.notifications import unread_count


class LoginResilienceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine, autoflush=False, autocommit=False)
        self.db = self.SessionLocal()
        role = Role(name="SuperAdmin")
        department = Department(name="Geral")
        self.db.add_all([role, department])
        self.db.flush()
        self.user = User(
            full_name="Administrador Principal",
            username="superadmin",
            email="superadmin@example.com",
            password_hash=hash_password("Admin@12345"),
            role_id=role.id,
            department_id=department.id,
            must_reset_password=False,
        )
        self.db.add(self.user)
        self.db.commit()
        app.dependency_overrides[get_db] = self.override_db
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.db.close()
        self.engine.dispose()

    def override_db(self):
        db = self.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    def test_login_redirects_even_when_audit_write_fails(self):
        with patch("app.routers.auth.audit_log", side_effect=RuntimeError("audit unavailable")):
            response = self.client.post(
                "/login",
                data={"username": "superadmin", "password": "Admin@12345"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/dashboard")

    def test_invalid_login_still_shows_credentials_message_when_audit_write_fails(self):
        with patch("app.routers.auth.audit_log", side_effect=RuntimeError("audit unavailable")):
            response = self.client.post(
                "/login",
                data={"username": "superadmin", "password": "wrong"},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 400)
        self.assertIn("Credenciais", response.text)

    def test_unread_count_returns_zero_when_database_is_temporarily_unavailable(self):
        with patch("app.services.notifications.SessionLocal", side_effect=RuntimeError("database unavailable")):
            self.assertEqual(unread_count(self.user.id), 0)


if __name__ == "__main__":
    unittest.main()
