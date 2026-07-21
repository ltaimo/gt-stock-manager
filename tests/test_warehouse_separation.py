import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.core import Department, MovementAction, Product, Requisition, RequisitionItem, RequisitionStatus, Role, User, Warehouse
from app.security import hash_password
from app.services.inventory import StockError, post_movement, product_warehouse_quantity
from app.services.requisitions import approve_requisition


class WarehouseSeparationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, expire_on_commit=False)()
        role = Role(name="SuperAdmin")
        department = Department(name="Geral")
        self.db.add_all([role, department])
        self.db.flush()
        self.user = User(
            full_name="Admin",
            username="admin",
            password_hash=hash_password("Admin@12345"),
            role_id=role.id,
            department_id=department.id,
        )
        self.default_warehouse = Warehouse(name="Armazem Principal", code="ARM-1", is_default=True, is_active=True)
        self.secondary_warehouse = Warehouse(name="Armazem Secundario", code="ARM-2", is_active=True)
        self.product = Product(code="WH-001", name="Produto multi-armazem", unit="un", current_stock=0)
        self.db.add_all([self.user, self.default_warehouse, self.secondary_warehouse, self.product])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_movements_are_separated_by_warehouse_and_transfers_keep_total(self):
        post_movement(
            self.db,
            product=self.product,
            action_type=MovementAction.entrada.value,
            quantity=10,
            registered_by=self.user,
            warehouse_id=self.default_warehouse.id,
        )
        post_movement(
            self.db,
            product=self.product,
            action_type=MovementAction.entrada.value,
            quantity=3,
            registered_by=self.user,
            warehouse_id=self.secondary_warehouse.id,
        )
        self.db.refresh(self.product)

        self.assertEqual(float(self.product.current_stock), 13)
        self.assertEqual(product_warehouse_quantity(self.db, self.product, self.default_warehouse.id), 10)
        self.assertEqual(product_warehouse_quantity(self.db, self.product, self.secondary_warehouse.id), 3)

        post_movement(
            self.db,
            product=self.product,
            action_type=MovementAction.transferencia.value,
            quantity=5,
            registered_by=self.user,
            warehouse_id=self.default_warehouse.id,
            destination_warehouse_id=self.secondary_warehouse.id,
        )
        self.db.refresh(self.product)

        self.assertEqual(float(self.product.current_stock), 13)
        self.assertEqual(product_warehouse_quantity(self.db, self.product, self.default_warehouse.id), 5)
        self.assertEqual(product_warehouse_quantity(self.db, self.product, self.secondary_warehouse.id), 8)

        with self.assertRaisesRegex(StockError, "Stock insuficiente"):
            post_movement(
                self.db,
                product=self.product,
                action_type=MovementAction.saida.value,
                quantity=6,
                registered_by=self.user,
                warehouse_id=self.default_warehouse.id,
            )

    def test_stock_requisition_uses_selected_warehouse_balance(self):
        post_movement(
            self.db,
            product=self.product,
            action_type=MovementAction.entrada.value,
            quantity=5,
            registered_by=self.user,
            warehouse_id=self.default_warehouse.id,
        )
        requisition = Requisition(
            number="REQ-WH-1",
            requesting_user_id=self.user.id,
            department_id=self.user.department_id,
            warehouse_id=self.secondary_warehouse.id,
            req_type="REQUISICAO",
            status=RequisitionStatus.submitted.value,
        )
        self.db.add(requisition)
        self.db.flush()
        self.db.add(RequisitionItem(requisition_id=requisition.id, product_id=self.product.id, quantity_requested=1))
        self.db.commit()
        self.db.refresh(requisition)

        with self.assertRaisesRegex(StockError, "Stock insuficiente"):
            approve_requisition(requisition, db=self.db)


if __name__ == "__main__":
    unittest.main()
