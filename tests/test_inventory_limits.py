import unittest
from types import SimpleNamespace

from app.services.inventory import StockError, post_movement


class FakeSession:
    def add(self, _value):
        pass

    def flush(self):
        pass


class InventoryLimitTests(unittest.TestCase):
    def test_superadmin_cannot_create_negative_stock(self):
        product = SimpleNamespace(id=1, current_stock=2)
        actor = SimpleNamespace(id=1, role=SimpleNamespace(name="SuperAdmin"))

        with self.assertRaisesRegex(StockError, "insuficiente"):
            post_movement(
                FakeSession(),
                product=product,
                action_type="SAÍDA",
                quantity=3,
                registered_by=actor,
            )


if __name__ == "__main__":
    unittest.main()
