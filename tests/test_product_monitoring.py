import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import __version__
from app.database import Base
from app.models.core import Product
from app.routers.reports import products_requiring_attention, stock_rows
from app.services.exports import display_value
from app.services.procurement import suggested_replenishment_quantity


class ProductMonitoringTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, expire_on_commit=False)()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def product(self, code: str, *, status: str = "active", monitored: bool = True) -> Product:
        product = Product(
            code=code,
            name=f"Produto {code}",
            unit="un",
            current_stock=0,
            minimum_stock=2,
            status=status,
            requires_stock_control=monitored,
        )
        self.db.add(product)
        self.db.flush()
        return product

    def test_inactive_product_is_not_an_attention_item(self):
        inactive = self.product("INATIVO", status="inactive")
        active = self.product("ATIVO")
        self.db.commit()

        attention = products_requiring_attention(self.db)

        self.assertEqual(inactive.alert_status, "Inativo")
        self.assertNotIn(inactive, attention)
        self.assertIn(active, attention)

    def test_active_one_off_product_does_not_trigger_alert_or_suggestion(self):
        one_off = self.product("PONTUAL", monitored=False)
        self.db.commit()

        self.assertEqual(one_off.alert_status, "Sem monitorização")
        self.assertEqual(suggested_replenishment_quantity(one_off), 0)
        self.assertNotIn(one_off, products_requiring_attention(self.db))

    def test_stock_report_keeps_inactive_products_with_explicit_state(self):
        self.product("INATIVO", status="inactive")
        self.db.commit()

        rows = stock_rows(self.db)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][9], "Inativo")
        self.assertEqual(rows[0][10], "Sim")
        self.assertEqual(rows[0][11], "Inativo")

    def test_release_version_is_2_1_0(self):
        self.assertEqual(__version__, "2.1.0")

    def test_report_exports_preserve_numeric_zero(self):
        self.assertEqual(display_value(0), "0")
        self.assertEqual(display_value(0.0), "0.0")
        self.assertEqual(display_value(None), "")


if __name__ == "__main__":
    unittest.main()
