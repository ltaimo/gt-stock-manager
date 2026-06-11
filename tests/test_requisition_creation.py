import unittest
from types import SimpleNamespace

from app.routers.requisitions import validate_requisition_items
from app.services.inventory import StockError


class FakeSession:
    def __init__(self, products):
        self.products = {product.id: product for product in products}

    def get(self, _model, product_id):
        return self.products.get(product_id)


def product(product_id: int, stock: float):
    return SimpleNamespace(
        id=product_id,
        code=f"P-{product_id}",
        name=f"Produto {product_id}",
        current_stock=stock,
        status="active",
    )


class RequisitionCreationValidationTests(unittest.TestCase):
    def test_requisition_rejects_item_without_stock(self):
        db = FakeSession([product(1, 0)])

        with self.assertRaisesRegex(StockError, "não tem stock"):
            validate_requisition_items(db, "REQUISIÇÃO", [1], [1])

    def test_requisition_rejects_total_above_stock_across_duplicate_rows(self):
        db = FakeSession([product(1, 5)])

        with self.assertRaisesRegex(StockError, "excede o stock"):
            validate_requisition_items(db, "REQUISIÇÃO", [1, 1], [3, 3])

    def test_return_can_include_item_without_current_stock(self):
        db = FakeSession([product(1, 0)])

        validated = validate_requisition_items(db, "DEVOLUÇÃO", [1], [2])

        self.assertEqual(validated[0][2], 2)


if __name__ == "__main__":
    unittest.main()
