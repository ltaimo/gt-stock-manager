import json
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.core import Department, Role, User
from app.security import hash_password


PROTECTED_GET_ROUTES = {
    "/produtos/novo": "products_manage",
    "/movimentos": "movements",
    "/documentos": "documents",
    "/requisicoes/nova": "stock_requisitions_create",
    "/procurement/nova": "non_stock_requisitions_create",
    "/procurement/reposicao/nova": "stock_replenishment_create",
    "/hse": "hse_view",
    "/relatorios": "reports",
    "/utilizadores": "users_manage",
    "/perfis": "profiles_manage",
    "/importar": "imports",
    "/auditoria": "audit",
    "/configuracoes": "settings_manage",
    "/configuracoes/matriz": "procurement_settings",
}


class ModuleAccessTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False)
        db = self.SessionLocal()
        department = Department(name="Geral")
        allowed_role = Role(
            name="Auditor de Modulos",
            permissions=json.dumps(sorted(set(PROTECTED_GET_ROUTES.values()))),
        )
        denied_role = Role(name="Sem Acessos", permissions="[]")
        db.add_all([department, allowed_role, denied_role])
        db.flush()
        db.add_all(
            [
                User(
                    full_name="Permitido",
                    username="permitido",
                    password_hash=hash_password("Test@12345"),
                    role_id=allowed_role.id,
                    department_id=department.id,
                ),
                User(
                    full_name="Bloqueado",
                    username="bloqueado",
                    password_hash=hash_password("Test@12345"),
                    role_id=denied_role.id,
                    department_id=department.id,
                ),
            ]
        )
        db.commit()
        db.close()
        app.dependency_overrides[get_db] = self.override_db
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()
        self.client.close()
        self.engine.dispose()

    def override_db(self):
        db = self.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    def login(self, username):
        response = self.client.post(
            "/login",
            data={"username": username, "password": "Test@12345"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

    def test_configured_permissions_open_every_corresponding_module(self):
        self.login("permitido")
        failures = {}
        for path in PROTECTED_GET_ROUTES:
            response = self.client.get(path, follow_redirects=False)
            if response.status_code != 200:
                failures[path] = response.status_code
        self.assertEqual(failures, {})

    def test_missing_permissions_block_every_protected_module(self):
        self.login("bloqueado")
        failures = {}
        for path in PROTECTED_GET_ROUTES:
            response = self.client.get(path, follow_redirects=False)
            if response.status_code != 403:
                failures[path] = response.status_code
        self.assertEqual(failures, {})


if __name__ == "__main__":
    unittest.main()
