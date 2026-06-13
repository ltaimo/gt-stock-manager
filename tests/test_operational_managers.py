import unittest

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.core import Department, Role, User
from app.routers.requisitions import default_manager_id, manager_options


class OperationalManagerTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine, expire_on_commit=False)()
        direction = Department(name="Direção")
        warehouse = Department(name="Armazém")
        operational_role = Role(name="Gestor Operacional")
        director_role = Role(name="Director do Terminal")
        user_role = Role(name="User")
        self.db.add_all([direction, warehouse, operational_role, director_role, user_role])
        self.db.flush()
        self.by_role = User(
            full_name="Gestor Operacional",
            username="gestor-operacional",
            password_hash="x",
            role_id=operational_role.id,
            department_id=warehouse.id,
        )
        self.by_department = User(
            full_name="Membro da Direção",
            username="direcao",
            password_hash="x",
            role_id=user_role.id,
            department_id=direction.id,
        )
        self.ordinary = User(
            full_name="Utilizador Normal",
            username="normal",
            password_hash="x",
            role_id=user_role.id,
            department_id=warehouse.id,
        )
        self.by_director_role = User(
            full_name="Director",
            username="director",
            password_hash="x",
            role_id=director_role.id,
            department_id=warehouse.id,
        )
        self.db.add_all([self.by_role, self.by_department, self.by_director_role, self.ordinary])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_only_operational_manager_or_direction_member_is_listed(self):
        managers = manager_options(self.db)

        self.assertEqual(
            {user.id for user in managers},
            {self.by_role.id, self.by_department.id, self.by_director_role.id},
        )

    def test_default_manager_must_belong_to_allowed_list(self):
        managers = manager_options(self.db)

        self.assertEqual(default_manager_id(self.by_role, managers), self.by_role.id)
        self.assertNotEqual(default_manager_id(self.ordinary, managers), self.ordinary.id)


if __name__ == "__main__":
    unittest.main()
