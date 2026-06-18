import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.core import ApprovalMatrixRule, Role
from app.security import has_permission
from app.services.procurement import classify_procurement


class ProcurementMatrixTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, expire_on_commit=False)()
        self.db.add_all(
            [
                ApprovalMatrixRule(min_value=0, max_value=5000, modality="RFQ", final_approval="Supervisor", sort_order=0),
                ApprovalMatrixRule(min_value=5001, max_value=10000, modality="RFQ", final_approval="Chefe do terminal", sort_order=1),
                ApprovalMatrixRule(min_value=1000000.01, max_value=None, modality="Tender formal", final_approval="Administracao / Conselho", sort_order=2),
            ]
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_classifies_procurement_value_by_active_matrix(self):
        low = classify_procurement(self.db, 5000)
        middle = classify_procurement(self.db, 7500)
        high = classify_procurement(self.db, 1500000)

        self.assertEqual(low.final_approval, "Supervisor")
        self.assertEqual(middle.final_approval, "Chefe do terminal")
        self.assertEqual(high.modality, "Tender formal")


class ProcurementPermissionTests(unittest.TestCase):
    def test_user_can_create_stock_and_non_stock_requests_by_default(self):
        role = Role(name="User", permissions=None)
        user = type("UserObj", (), {"role": role})()

        self.assertTrue(has_permission(user, "stock_requisitions_create"))
        self.assertTrue(has_permission(user, "non_stock_requisitions_create"))
        self.assertFalse(has_permission(user, "procurement_manage"))


if __name__ == "__main__":
    unittest.main()
