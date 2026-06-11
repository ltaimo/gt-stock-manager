import tempfile
import unittest
from pathlib import Path

from openpyxl import Workbook
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.database import Base
from app.models.core import Product, Role, StockMovement, User
from app.security import hash_password
from app.services.imports import build_import_preview, import_preview


class SimpleStockImportTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        role = Role(name="SuperAdmin")
        self.db.add(role)
        self.db.flush()
        self.actor = User(
            full_name="Administrador",
            username="superadmin",
            password_hash=hash_password("test"),
            role_id=role.id,
        )
        self.db.add(self.actor)
        self.db.flush()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def workbook_bytes(self) -> bytes:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Stock Corrigido"
        sheet.append(["Item", "Quantidade"])
        sheet.append(["Varetas de bronze", 5])
        sheet.append(["Lonas militares", None])
        sheet.append(["varetas de bronze", 24])
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as handle:
            path = Path(handle.name)
        try:
            workbook.save(path)
            return path.read_bytes()
        finally:
            path.unlink(missing_ok=True)

    def test_preview_consolidates_duplicates_and_accepts_blank_quantity(self):
        preview = build_import_preview(self.db, "stock.xlsx", self.workbook_bytes())

        self.assertEqual(preview["counts"]["products_total"], 2)
        self.assertEqual(preview["counts"]["products_valid"], 2)
        self.assertEqual(preview["counts"]["errors"], 0)
        self.assertEqual(preview["counts"]["warnings"], 2)
        quantities = {item["name"].casefold(): item["current_stock"] for item in preview["products"]}
        self.assertEqual(quantities["varetas de bronze"], 29)
        self.assertEqual(quantities["lonas militares"], 0)

    def test_import_creates_one_movement_only_for_positive_stock(self):
        preview = build_import_preview(self.db, "stock.xlsx", self.workbook_bytes())
        result = import_preview(self.db, preview, self.actor)
        self.db.commit()

        self.assertEqual(result.imported, 2)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(Product)), 2)
        self.assertEqual(self.db.scalar(select(func.count()).select_from(StockMovement)), 1)


if __name__ == "__main__":
    unittest.main()
