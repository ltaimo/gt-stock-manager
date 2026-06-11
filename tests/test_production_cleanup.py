import unittest

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from app.database import Base
from app.models.core import Product, Role, User
from app.services.production_cleanup import clean_for_production


class ProductionCleanupTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        role = Role(name="SuperAdmin")
        self.db.add(role)
        self.db.flush()
        self.superadmin = User(
            full_name="Administrador",
            username="superadmin",
            password_hash="hash",
            role_id=role.id,
        )
        other = User(full_name="Outro", username="outro", password_hash="hash", role_id=role.id)
        self.db.add_all([self.superadmin, other])
        self.db.flush()
        self.db.add(Product(code="DEMO", name="Produto Demo", created_by_id=self.superadmin.id))
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_cleanup_keeps_only_superadmin_and_removes_products(self):
        clean_for_production(self.db)
        self.db.commit()

        usernames = self.db.scalars(select(User.username)).all()
        self.assertEqual(usernames, ["superadmin"])
        self.assertEqual(self.db.scalar(select(func.count()).select_from(Product)), 0)


if __name__ == "__main__":
    unittest.main()
