import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.core import Category, Department, MovementAction, Product, Role, Setting, StockMovement, User
from app.seed import consolidate_fixture_duplicate_products, seed_ac_tools_products
from app.security import hash_password
from app.services.inventory import post_movement


class SeedAndLanguageTests(unittest.TestCase):
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
        )
        self.db.add(self.user)
        self.db.commit()

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

    def test_ac_tools_seed_is_idempotent_and_posts_initial_stock(self):
        created = seed_ac_tools_products(self.db, self.user)
        self.db.commit()
        created_again = seed_ac_tools_products(self.db, self.user)
        self.db.commit()

        self.assertEqual(created, 53)
        self.assertEqual(created_again, 0)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(Product)), 53)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(StockMovement)), 39)
        self.assertEqual(float(self.db.scalar(select(func.coalesce(func.sum(Product.current_stock), 0)))), 118.0)
        self.assertIsNotNone(self.db.scalar(select(Setting).where(Setting.key == "seed_ac_tools_products_20260618")))
        self.assertIsNotNone(self.db.scalar(select(Product).where(Product.code == "FR-001")))
        gree_12000 = self.db.scalar(select(Product).where(Product.code == "AC-002"))
        self.assertIsNotNone(gree_12000)
        self.assertEqual(gree_12000.name, "Ar condicionado Gree 12000 BTU")
        self.assertEqual(float(gree_12000.current_stock), 32.0)

    def test_consolidates_previous_duplicate_air_conditioners(self):
        category = Category(name="Ar Condicionado", normalized_name="ar condicionado")
        self.db.add(category)
        self.db.flush()
        canonical = Product(code="AC-002", name="Ar condicionado Gree 12000 BTU", category_id=category.id, unit="un")
        duplicate = Product(code="AC-005", name="Ar condicionado Gree 12000 BTU", category_id=category.id, unit="un")
        self.db.add_all([canonical, duplicate])
        self.db.flush()
        post_movement(
            self.db,
            product=canonical,
            action_type=MovementAction.entrada.value,
            quantity=10,
            registered_by=self.user,
            reference_number="TEST-AC-002",
        )
        post_movement(
            self.db,
            product=duplicate,
            action_type=MovementAction.entrada.value,
            quantity=5,
            registered_by=self.user,
            reference_number="TEST-AC-005",
        )
        self.db.commit()

        consolidated = consolidate_fixture_duplicate_products(self.db)
        self.db.commit()

        self.assertEqual(consolidated, 1)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(Product).where(Product.code.in_(["AC-002", "AC-005"]))), 1)
        canonical = self.db.scalar(select(Product).where(Product.code == "AC-002"))
        self.assertEqual(float(canonical.current_stock), 15.0)
        movement_product_ids = {product_id for (product_id,) in self.db.execute(select(StockMovement.product_id)).all()}
        self.assertEqual(movement_product_ids, {canonical.id})

    def test_language_selector_persists_and_changes_navigation_after_login(self):
        app.dependency_overrides[get_db] = self.override_db
        client = TestClient(app)

        login = client.post(
            "/login",
            data={"username": "superadmin", "password": "Admin@12345"},
            follow_redirects=False,
        )
        self.assertEqual(login.status_code, 303)

        response = client.post(
            "/preferencias/idioma",
            data={"language": "en"},
            headers={"referer": "http://testserver/dashboard"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

        dashboard = client.get("/dashboard")
        self.assertEqual(dashboard.status_code, 200)
        html = dashboard.text
        self.assertIn('<html lang="en">', html)
        self.assertIn("Store / Products", html)
        self.assertIn("New SR Request", html)
