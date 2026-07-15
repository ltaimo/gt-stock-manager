import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.maintenance.normalize_products import consolidate_exact_duplicate_products
from app.models.core import (
    Category,
    Department,
    MovementAction,
    Product,
    Requisition,
    RequisitionItem,
    Role,
    Setting,
    StockDocument,
    StockDocumentProduct,
    StockMovement,
    User,
)
from app.seed import consolidate_fixture_duplicate_products, repair_portuguese_labels, seed_ac_tools_products
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

    def test_consolidates_exact_duplicate_products_and_moves_links(self):
        category = Category(name="Canalização", normalized_name="canalizacao")
        self.db.add(category)
        self.db.flush()
        canonical = Product(code="IMP-00052", name="Torneiras de esquadrilha", category_id=category.id, unit="un")
        duplicate = Product(code="IMP-00095", name="Torneiras de esquadrilha", category_id=category.id, unit="un")
        self.db.add_all([canonical, duplicate])
        self.db.flush()
        post_movement(
            self.db,
            product=canonical,
            action_type=MovementAction.entrada.value,
            quantity=5,
            registered_by=self.user,
            reference_number="TEST-IMP-00052",
        )
        post_movement(
            self.db,
            product=duplicate,
            action_type=MovementAction.entrada.value,
            quantity=5,
            registered_by=self.user,
            reference_number="TEST-IMP-00095",
        )
        requisition = Requisition(number="REQ-DUP", requesting_user_id=self.user.id, status="Draft")
        self.db.add(requisition)
        self.db.flush()
        self.db.add(RequisitionItem(requisition_id=requisition.id, product_id=duplicate.id, quantity_requested=1))
        document = StockDocument(
            document_type="Guia",
            original_filename="guia.pdf",
            stored_filename="guia.pdf",
            file_path="/tmp/guia.pdf",
            uploaded_by_id=self.user.id,
        )
        self.db.add(document)
        self.db.flush()
        self.db.add(StockDocumentProduct(document_id=document.id, product_id=duplicate.id))
        self.db.commit()

        consolidated = consolidate_exact_duplicate_products(self.db)
        self.db.commit()

        self.assertEqual(consolidated, 1)
        self.assertIsNone(self.db.scalar(select(Product).where(Product.code == "IMP-00095")))
        canonical = self.db.scalar(select(Product).where(Product.code == "IMP-00052"))
        self.assertEqual(float(canonical.current_stock), 10.0)
        self.assertEqual(
            {product_id for (product_id,) in self.db.execute(select(StockMovement.product_id)).all()},
            {canonical.id},
        )
        self.assertEqual(self.db.scalar(select(RequisitionItem.product_id)), canonical.id)
        self.assertEqual(self.db.scalar(select(StockDocumentProduct.product_id)), canonical.id)

    def test_repairs_legacy_mojibake_without_changing_correct_labels(self):
        corrupted_department = "Operações".encode("utf-8").decode("latin-1")
        corrupted_category = "Climatização".encode("utf-8").decode("latin-1")
        department = Department(name=corrupted_department)
        category = Category(name=corrupted_category, normalized_name="legacy-climatizacao")
        self.db.add_all([department, category])
        self.db.flush()

        repair_portuguese_labels(self.db)
        self.db.flush()

        self.assertEqual(department.name, "Operações")
        self.assertEqual(category.name, "Climatização")
        self.assertEqual(category.normalized_name, "climatizacao")

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
