import io
import unittest

from fastapi.testclient import TestClient
from openpyxl import load_workbook
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.core import Department, Product, ProductImage, Role, User
from app.security import hash_password


class ProductExportAndImageTests(unittest.TestCase):
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
        department = Department(name="IT")
        self.db.add_all([role, department])
        self.db.flush()
        self.user = User(
            full_name="Admin",
            username="admin",
            email="admin@example.com",
            password_hash=hash_password("Admin@12345"),
            role_id=role.id,
            department_id=department.id,
        )
        self.product = Product(
            code="PRD-00001",
            name="Silicone",
            name_en="Sealant",
            unit="un",
            unit_price=125,
            minimum_stock=5,
            current_stock=12,
            created_by_id=self.user.id,
        )
        self.db.add_all([self.user, self.product])
        self.db.commit()
        app.dependency_overrides[get_db] = self.override_db
        self.client = TestClient(app)
        response = self.client.post(
            "/login",
            data={"username": "admin", "password": "Admin@12345"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

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

    def test_products_can_be_exported_with_public_image_url(self):
        csv_response = self.client.get("/produtos?export=csv")
        self.assertEqual(csv_response.status_code, 200)
        self.assertIn("produtos.csv", csv_response.headers["content-disposition"])
        self.assertIn("URL da imagem", csv_response.text)
        self.assertIn("Silicone", csv_response.text)

        xlsx_response = self.client.get("/produtos?export=xlsx")
        self.assertEqual(xlsx_response.status_code, 200)
        sheet = load_workbook(io.BytesIO(xlsx_response.content)).active
        headers = [cell.value for cell in sheet[4]]
        self.assertIn("URL da imagem", headers)
        self.assertEqual(sheet["B5"].value, "Silicone")

    def test_product_image_upload_renders_thumbnail_and_public_endpoint(self):
        image_bytes = b"\x89PNG\r\n\x1a\nGTIMS"
        response = self.client.post(
            f"/produtos/{self.product.id}/editar",
            data={
                "name": "Silicone",
                "name_en": "Sealant",
                "category_id": "",
                "unit": "un",
                "unit_price": "125",
                "minimum_stock": "5",
                "requires_stock_control": "1",
                "status": "active",
            },
            files={"image_file": ("silicone.png", image_bytes, "image/png")},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

        with self.SessionLocal() as db:
            stored = db.scalar(select(ProductImage).where(ProductImage.product_id == self.product.id))
            self.assertIsNotNone(stored)
            self.assertEqual(stored.content, image_bytes)

        page = self.client.get("/produtos")
        self.assertEqual(page.status_code, 200)
        self.assertIn('class="product-thumb"', page.text)
        self.assertIn(f"/produtos/{self.product.id}/imagem", page.text)

        self.client.post("/logout", follow_redirects=False)
        public_image = self.client.get(f"/produtos/{self.product.id}/imagem")
        self.assertEqual(public_image.status_code, 200)
        self.assertEqual(public_image.headers["content-type"], "image/png")
        self.assertEqual(public_image.content, image_bytes)


if __name__ == "__main__":
    unittest.main()
