import unittest
from types import SimpleNamespace

from app.routers.requisitions import validate_requisition_items
from app.services.inventory import StockError


class FakeSession:
    def __init__(self, products):
        self.products = {product.id: product for product in products}

    def get(self, _model, product_id):
        return self.products.get(product_id)


def product(product_id: int, stock: float, unit_price: float = 100):
    return SimpleNamespace(
        id=product_id,
        code=f"P-{product_id}",
        name=f"Produto {product_id}",
        current_stock=stock,
        unit_price=unit_price,
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

    def test_requisition_allows_item_without_unit_price_while_prices_are_being_loaded(self):
        db = FakeSession([product(1, 5, unit_price=0)])

        validated = validate_requisition_items(db, "REQUISIÇÃO", [1], [1])

        self.assertEqual(validated[0][2], 1)

    def test_strict_unit_price_flag_can_reject_item_without_unit_price_later(self):
        db = FakeSession([product(1, 5, unit_price=0)])

        with self.assertRaisesRegex(StockError, "preço unitário"):
            validate_requisition_items(db, "REQUISIÇÃO", [1], [1], require_unit_price=True)

    def test_draft_requisition_can_keep_item_without_unit_price(self):
        db = FakeSession([product(1, 5, unit_price=0)])

        validated = validate_requisition_items(db, "REQUISIÇÃO", [1], [1], require_unit_price=False)

        self.assertEqual(validated[0][2], 1)

    def test_return_can_include_item_without_current_stock(self):
        db = FakeSession([product(1, 0)])

        validated = validate_requisition_items(db, "DEVOLUÇÃO", [1], [2])

        self.assertEqual(validated[0][2], 2)


if __name__ == "__main__":
    unittest.main()
