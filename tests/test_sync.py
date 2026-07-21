import unittest

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.main import app, settings
from app.models.core import Base, Department, Role, User
from app.services import sync as sync_service


class SyncSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.original_engine = sync_service.engine

    def tearDown(self):
        sync_service.engine = self.original_engine

    def test_snapshot_can_be_applied_to_an_empty_database(self):
        source_engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(source_engine)
        SourceSession = sessionmaker(bind=source_engine, future=True)
        with SourceSession() as db:
            role = Role(id=1, name="SuperAdmin", permissions=None, is_system=True)
            department = Department(id=1, name="Geral", is_active=True)
            db.add_all([role, department])
            db.flush()
            db.add(
                User(
                    id=1,
                    full_name="Administrador Principal",
                    username="superadmin",
                    email="superadmin@gt.co.mz",
                    password_hash="hash",
                    role_id=role.id,
                    department_id=department.id,
                )
            )
            db.commit()

        sync_service.engine = source_engine
        snapshot = sync_service.create_snapshot()

        target_engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(target_engine)
        sync_service.engine = target_engine
        counts = sync_service.apply_snapshot(snapshot)

        self.assertEqual(counts["roles"], 1)
        self.assertEqual(counts["departments"], 1)
        self.assertEqual(counts["users"], 1)
        with target_engine.connect() as connection:
            username = connection.execute(select(User.username)).scalar_one()
        self.assertEqual(username, "superadmin")

    def test_invalid_snapshot_format_is_rejected(self):
        with self.assertRaises(ValueError):
            sync_service.apply_snapshot({"format": "wrong"})


class SyncMirrorModeTests(unittest.TestCase):
    def test_mirror_mode_blocks_normal_writes(self):
        original_mode = settings.sync_mode
        original_read_only = settings.mirror_read_only
        try:
            settings.sync_mode = "mirror"
            settings.mirror_read_only = True
            response = TestClient(app).post("/preferencias/idioma", data={"language": "en"})
        finally:
            settings.sync_mode = original_mode
            settings.mirror_read_only = original_read_only

        self.assertEqual(response.status_code, 423)
        self.assertIn("modo espelho", response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
