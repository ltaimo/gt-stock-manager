import json
import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.core import Department, MovementAction, Product, Role, StockMovement, User
from app.security import hash_password
from app.services.inventory import post_movement


class BulkMovementTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine, expire_on_commit=False)
        self.db = self.SessionLocal()
        self.role = Role(name="Movimentos", permissions=json.dumps(["movements"]))
        self.department = Department(name="Operacoes")
        self.db.add_all([self.role, self.department])
        self.db.flush()
        self.user = User(
            full_name="Gestor",
            username="gestor",
            password_hash=hash_password("Test@12345"),
            role_id=self.role.id,
            department_id=self.department.id,
            notify_email=False,
        )
        self.product_a = Product(code="P-A", name="Produto A", unit="un", current_stock=0, created_by_id=None)
        self.product_b = Product(code="P-B", name="Produto B", unit="un", current_stock=0, created_by_id=None)
        self.db.add_all([self.user, self.product_a, self.product_b])
        self.db.flush()
        post_movement(self.db, product=self.product_a, action_type=MovementAction.entrada.value, quantity=10, registered_by=self.user)
        post_movement(self.db, product=self.product_b, action_type=MovementAction.entrada.value, quantity=5, registered_by=self.user)
        self.db.commit()
        self.initial_movement_count = 2

        app.dependency_overrides[get_db] = self.override_db
        self.client = TestClient(app)
        self.login()

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

    def login(self):
        response = self.client.post(
            "/login",
            data={"username": "gestor", "password": "Test@12345"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303, response.text)

    def test_bulk_entry_creates_one_movement_per_line(self):
        response = self.client.post(
            "/movimentos/novo",
            data={
                "product_id": [str(self.product_a.id), str(self.product_b.id)],
                "quantity": ["2", "3"],
                "action_type": "ENTRADA",
                "origin": "Fornecedor X",
                "document_type": "Guia",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303, response.text)
        self.db.expire_all()
        self.assertEqual(self.db.scalar(select(func.count()).select_from(StockMovement)), self.initial_movement_count + 2)
        self.assertEqual(float(self.db.get(Product, self.product_a.id).current_stock), 12)
        self.assertEqual(float(self.db.get(Product, self.product_b.id).current_stock), 8)

    def test_bulk_exit_with_multiple_products_updates_stock(self):
        response = self.client.post(
            "/movimentos/novo",
            data={
                "product_id": [str(self.product_a.id), str(self.product_b.id)],
                "quantity": ["4", "2"],
                "action_type": "SAÍDA",
                "department_id": str(self.department.id),
                "responsible_person": "Supervisor",
                "document_type": "Guia",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303, response.text)
        self.db.expire_all()
        self.assertEqual(self.db.scalar(select(func.count()).select_from(StockMovement)), self.initial_movement_count + 2)
        self.assertEqual(float(self.db.get(Product, self.product_a.id).current_stock), 6)
        self.assertEqual(float(self.db.get(Product, self.product_b.id).current_stock), 3)

    def test_duplicate_product_lines_cannot_overdraw_stock(self):
        response = self.client.post(
            "/movimentos/novo",
            data={
                "product_id": [str(self.product_b.id), str(self.product_b.id)],
                "quantity": ["4", "2"],
                "action_type": "SAÍDA",
                "department_id": str(self.department.id),
                "responsible_person": "Supervisor",
                "document_type": "Guia",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("excede o stock", response.text)
        self.db.expire_all()
        self.assertEqual(self.db.scalar(select(func.count()).select_from(StockMovement)), self.initial_movement_count)
        self.assertEqual(float(self.db.get(Product, self.product_b.id).current_stock), 5)


if __name__ == "__main__":
    unittest.main()
