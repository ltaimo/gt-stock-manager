import unittest

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.core import (
    Department,
    Product,
    Requisition,
    RequisitionItem,
    RequisitionStatus,
    Role,
    StockMovement,
    User,
)
from app.services.requisitions import approve_requisition, issue_requisition


class RequisitionStockLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, expire_on_commit=False)()
        role = Role(name="Gestor de Estoque")
        department = Department(name="Armazém")
        self.db.add_all([role, department])
        self.db.flush()
        self.actor = User(full_name="Gestor", username="gestor", password_hash="x", role_id=role.id)
        self.requester = User(full_name="Pedido", username="pedido", password_hash="x", role_id=role.id, department_id=department.id)
        self.product = Product(code="P-1", name="Produto", current_stock=0, unit="un")
        self.db.add_all([self.actor, self.requester, self.product])
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
        self.req = Requisition(
            number="REQ-TEST-1",
            requesting_user_id=self.requester.id,
            department_id=department.id,
            req_type="REQUISIÇÃO",
            status=RequisitionStatus.submitted.value,
        )
        self.db.add(self.req)
        self.db.flush()
        self.item = RequisitionItem(
            requisition_id=self.req.id,
            product_id=self.product.id,
            quantity_requested=2,
            destination=department.name,
        )
        self.db.add(self.item)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_stock_changes_only_once_when_approved_request_is_issued(self):
        approve_requisition(self.req)
        self.db.commit()

        self.assertEqual(float(self.product.current_stock), 10)
        self.assertEqual(self.db.scalars(select(StockMovement)).all().__len__(), 1)

        issue_requisition(self.db, self.req, self.actor)
        self.db.commit()

        self.assertEqual(float(self.product.current_stock), 8)
        self.assertEqual(len(self.db.scalars(select(StockMovement)).all()), 2)
        self.assertEqual(self.req.status, RequisitionStatus.issued.value)

        with self.assertRaisesRegex(ValueError, "Apenas requisições aprovadas"):
            issue_requisition(self.db, self.req, self.actor)
        self.assertEqual(float(self.product.current_stock), 8)
        self.assertEqual(len(self.db.scalars(select(StockMovement)).all()), 2)


if __name__ == "__main__":
    unittest.main()
