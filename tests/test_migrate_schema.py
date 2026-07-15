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
                         'REQ-TEST', false),
                        (3, 5, 'Requisição pendente: REQ-TEST', 'Requisições',
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
                    CREATE TABLE internal_operation_records (
                        id INTEGER PRIMARY KEY,
                        number VARCHAR(40),
                        kind VARCHAR(30),
                        unit VARCHAR(30)
                    )
                    """
                )
            )
            connection.execute(
                text("INSERT INTO internal_operation_records (id, number, kind, unit) VALUES (1, 'WATER-OLD', 'water', 'un')")
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
                        (1, 5001, 10000, 'RFQ', 'Chefe do Terminal', 9, true, 1),
                        (2, 0, 5000, 'RFQ', 'Supervisor', NULL, true, 0),
                        (3, 10001, 30000, 'RFQ / RFP', 'Diretor + Financeiro', NULL, true, 2),
                        (4, 30001, 1000000, 'RFQ / RFP', 'Direcao Geral', NULL, true, 3),
                        (5, 1000000.01, NULL, 'Tender formal', 'Administracao / Conselho', NULL, true, 4)
                    """
                )
            )
            connection.execute(
                text(
                    """
                    INSERT INTO requisitions
                        (id, number, authorization_person, estimated_value, status)
                    VALUES
                        (13, 'REQ-TEST', 'Chefe do Terminal', 7600, 'Submitted'),
                        (14, 'REQ-SUP', 'Supervisor', 1000, 'Submitted')
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
        self.assertIn(
            "fuel_type",
            {column["name"] for column in inspect(self.engine).get_columns("internal_operation_records")},
        )
        self.assertIn(
            "asset_name",
            {column["name"] for column in inspect(self.engine).get_columns("internal_operation_records")},
        )
        migrated_internal_columns = {column["name"] for column in inspect(self.engine).get_columns("internal_operation_records")}
        self.assertTrue(
            {"operation_type", "odometer_reading", "meter_reading", "payment_method"}.issubset(migrated_internal_columns)
        )
        self.assertIn("internal_operation_options", inspect(self.engine).get_table_names())
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
            notification_modules = dict(
                connection.execute(
                    text("SELECT id, module FROM notifications ORDER BY id")
                ).all()
            )
            unread_for_request = connection.execute(
                text(
                    """
                    SELECT count(*)
                    FROM notifications
                    WHERE is_read = false
                      AND record_id = 'REQ-TEST'
                      AND user_id = 5
                    """
                )
            ).scalar_one()
            procurement_status = connection.execute(
                text("SELECT status FROM procurement_cases WHERE id = 1")
            ).scalar_one()
            internal_operation = connection.execute(
                text("SELECT operation_type, unit FROM internal_operation_records WHERE id = 1")
            ).one()
            supervisor_role_id = connection.execute(
                text("SELECT id FROM roles WHERE name = 'Supervisor'")
            ).scalar_one()
            director_role_id = connection.execute(
                text("SELECT id FROM roles WHERE name = 'Director Financeiro'")
            ).scalar_one()
            delegated_admin_role_id = connection.execute(
                text("SELECT id FROM roles WHERE name = 'Administrador Delegado'")
            ).scalar_one()
            pca_role_id = connection.execute(
                text("SELECT id FROM roles WHERE name = 'PCA'")
            ).scalar_one()
            matrix_links = dict(
                connection.execute(
                    text("SELECT id, approver_role_id FROM approval_matrix_rules ORDER BY id")
                ).all()
            )
            supervisor_req_approver = connection.execute(
                text("SELECT approver_role_id FROM requisitions WHERE id = 14")
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
        self.assertTrue(bool(notification_states[1]))
        self.assertTrue(bool(notification_states[2]))
        self.assertFalse(bool(notification_states[3]))
        self.assertEqual(notification_modules[3], "Requisicoes")
        self.assertEqual(unread_for_request, 1)
        self.assertEqual(procurement_status, "Pending HOD TdR Approval")
        self.assertEqual(internal_operation[0], "water_purchase")
        self.assertEqual(internal_operation[1], "L")
        self.assertEqual(matrix_links[2], supervisor_role_id)
        self.assertEqual(matrix_links[3], director_role_id)
        self.assertEqual(matrix_links[4], delegated_admin_role_id)
        self.assertEqual(matrix_links[5], pca_role_id)
        self.assertEqual(supervisor_req_approver, supervisor_role_id)


if __name__ == "__main__":
    unittest.main()
