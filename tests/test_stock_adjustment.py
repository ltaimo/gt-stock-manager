import unittest

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.core import Product, Role, StockMovement, User
from app.services.inventory import StockError, adjust_product_stock


class StockAdjustmentTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, expire_on_commit=False)()
        role = Role(name="Gestor de Estoque")
        self.db.add(role)
        self.db.flush()
        self.actor = User(full_name="Gestor", username="gestor-ajuste", password_hash="x", role_id=role.id)
        self.product = Product(code="P-AJUSTE", name="Produto ajuste", current_stock=0, unit="un")
        self.db.add_all([self.actor, self.product])
        self.db.flush()
        self.db.add(
            StockMovement(
                action_type="ENTRADA",
                product_id=self.product.id,
                quantity=10,
                signed_quantity=10,
                registered_by_id=self.actor.id,
            )
        )
        self.product.current_stock = 10
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_adjustment_sets_exact_quantity_and_records_reason(self):
        movement = adjust_product_stock(
            self.db,
            product=self.product,
            target_quantity=6,
            reason="Contagem física confirmou seis unidades.",
            actor=self.actor,
        )
        self.db.commit()

        self.assertEqual(float(self.product.current_stock), 6)
        self.assertEqual(movement.action_type, "ACERTO")
        self.assertEqual(float(movement.signed_quantity), -4)
        self.assertEqual(movement.notes, "Contagem física confirmou seis unidades.")
        self.assertEqual(len(self.db.scalars(select(StockMovement)).all()), 2)

    def test_adjustment_rejects_negative_quantity(self):
        with self.assertRaisesRegex(StockError, "não pode ser negativa"):
            adjust_product_stock(
                self.db,
                product=self.product,
                target_quantity=-1,
                reason="Tentativa inválida.",
                actor=self.actor,
            )

        self.assertEqual(float(self.product.current_stock), 10)

    def test_adjustment_requires_reason(self):
        with self.assertRaisesRegex(StockError, "motivo obrigatório"):
            adjust_product_stock(
                self.db,
                product=self.product,
                target_quantity=8,
                reason=" ",
                actor=self.actor,
            )


if __name__ == "__main__":
    unittest.main()
