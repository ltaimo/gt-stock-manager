import json
import unittest

from sqlalchemy import create_engine, inspect, text

from app.maintenance import migrate_schema


class ApprovalSchemaMigrationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    CREATE TABLE roles (
                        id INTEGER PRIMARY KEY,
                        name VARCHAR(30) UNIQUE NOT NULL,
                        permissions TEXT,
                        is_system BOOLEAN DEFAULT false
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE procurement_cases (
                        id INTEGER PRIMARY KEY,
                        status VARCHAR(80),
                        tor_status VARCHAR(60),
                        item_type VARCHAR(40),
                        tdr_number VARCHAR(80),
                        job_title VARCHAR(220),
                        technical_requirements TEXT,
                        hse_requirements TEXT,
                        hod_approved_by_id INTEGER,
                        hod_approved_at TIMESTAMP,
                        terminal_manager_approved_by_id INTEGER,
                        terminal_manager_approved_at TIMESTAMP,
                        technical_report_status VARCHAR(60),
                        hse_documents_status VARCHAR(60),
                        execution_status VARCHAR(60),
                        receipt_note TEXT,
                        archive_status VARCHAR(60)
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE users (
                        id INTEGER PRIMARY KEY,
                        role_id INTEGER NOT NULL REFERENCES roles(id)
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO procurement_cases (id, status, tor_status)
                    VALUES (1, 'Pending Budget Verification', 'Pending HOD Approval')
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE notifications (
                        id INTEGER PRIMARY KEY,
                        user_id INTEGER NOT NULL REFERENCES users(id),
                        title VARCHAR(180) NOT NULL,
                        module VARCHAR(80) NOT NULL,
                        record_id VARCHAR(80),
                        is_read BOOLEAN DEFAULT false,
                        read_at TIMESTAMP
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE departments (
                        id INTEGER PRIMARY KEY,
                        name VARCHAR(120) UNIQUE NOT NULL,
                        is_active BOOLEAN DEFAULT true,
                        created_at TIMESTAMP
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO roles (id, name, permissions)
                    VALUES (5, 'Gestor de Estoque',
                            '["requisitions_all", "requisitions_review"]')
                    """
                )
            )
            connection.execute(
                text("INSERT INTO users (id, role_id) VALUES (5, 9), (6, 5)")
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE approval_matrix_rules (
                        id INTEGER PRIMARY KEY,
                        min_value NUMERIC(14, 2),
                        max_value NUMERIC(14, 2),
                        modality VARCHAR(80) NOT NULL,
                        final_approval VARCHAR(160) NOT NULL,
                        approver_role_id INTEGER REFERENCES roles(id),
                        is_active BOOLEAN DEFAULT true,
                        sort_order INTEGER DEFAULT 0,
                        created_at TIMESTAMP
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO notifications
                        (id, user_id, title, module, record_id, is_read)
                    VALUES
                        (1, 5, 'Requisicao pendente: REQ-TEST', 'Requisicoes',
                         'REQ-TEST', false),
                        (2, 6, 'Requisicao pendente: REQ-TEST', 'Requisicoes',
                         'REQ-TEST', false)
                    """
                )
            )
            connection.execute(
                text(
                    """
                    CREATE TABLE requisitions (
                        id INTEGER PRIMARY KEY,
                        number VARCHAR(40) UNIQUE NOT NULL,
                        authorization_person VARCHAR(160),
                        estimated_value NUMERIC(14, 2) DEFAULT 0,
                        status VARCHAR(30)
                    )
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO roles (id, name, permissions)
                    VALUES (9, 'Chefe do Terminal', '["documents"]')
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO approval_matrix_rules
                        (id, min_value, max_value, modality, final_approval,
                         approver_role_id, is_active, sort_order)
                    VALUES
                        (1, 5001, 10000, 'RFQ', 'Chefe do Terminal', 9, true, 0)
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO requisitions
                        (id, number, authorization_person, estimated_value, status)
                    VALUES
                        (13, 'REQ-TEST', 'Chefe do Terminal', 7600, 'Submitted')
                    """
                )
            )
        self.original_engine = migrate_schema.engine
        migrate_schema.engine = self.engine

    def tearDown(self):
        migrate_schema.engine = self.original_engine
        self.engine.dispose()

    def test_migration_links_existing_requests_and_repairs_matrix_permissions(self):
        migrate_schema.ensure_schema()

        self.assertIn(
            "approver_role_id",
            {column["name"] for column in inspect(self.engine).get_columns("requisitions")},
        )
        with self.engine.connect() as connection:
            approver_role_id = connection.execute(
                text("SELECT approver_role_id FROM requisitions WHERE id = 13")
            ).scalar_one()
            stored = connection.execute(
                text("SELECT permissions FROM roles WHERE id = 9")
            ).scalar_one()
            notification_states = dict(
                connection.execute(
                    text("SELECT id, is_read FROM notifications ORDER BY id")
                ).all()
            )
            procurement_status = connection.execute(
                text("SELECT status FROM procurement_cases WHERE id = 1")
            ).scalar_one()

        self.assertEqual(approver_role_id, 9)
        permissions = set(json.loads(stored))
        self.assertTrue(
            {
                "documents",
                "procurement_value_approve",
                "requisitions_all",
                "requisitions_review",
            }.issubset(permissions)
        )
        self.assertFalse(bool(notification_states[1]))
        self.assertTrue(bool(notification_states[2]))
        self.assertEqual(procurement_status, "Pending HOD TdR Approval")


if __name__ == "__main__":
    unittest.main()
