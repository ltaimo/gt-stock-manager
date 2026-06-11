import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.services.stock_reset import reset_all_stock


class FakeScalars:
    def __init__(self, products):
        self.products = products

    def all(self):
        return self.products


class FakeSession:
    def __init__(self, products):
        self.products = products

    def scalars(self, _statement):
        return FakeScalars(self.products)


class StockResetTests(unittest.TestCase):
    @patch("app.services.stock_reset.post_movement")
    def test_reset_creates_adjustments_only_for_nonzero_stock(self, post_movement):
        products = [
            SimpleNamespace(id=1, current_stock=8),
            SimpleNamespace(id=2, current_stock=0),
            SimpleNamespace(id=3, current_stock=-2),
        ]
        actor = SimpleNamespace(id=10)

        result = reset_all_stock(FakeSession(products), actor)

        self.assertEqual(result["products_affected"], 2)
        self.assertEqual(result["quantity_removed"], 8)
        self.assertEqual(result["negative_quantity_corrected"], 2)
        self.assertEqual(post_movement.call_count, 2)
        self.assertEqual(post_movement.call_args_list[0].kwargs["adjustment_direction"], "decrease")
        self.assertEqual(post_movement.call_args_list[1].kwargs["adjustment_direction"], "increase")


if __name__ == "__main__":
    unittest.main()
