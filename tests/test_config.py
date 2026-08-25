import unittest
from unittest.mock import patch

from app.config import auto_prepare_schema_enabled, resolve_database_url


class ConfigTests(unittest.TestCase):
    def test_production_requires_database_url(self):
        with patch.dict("os.environ", {"ENVIRONMENT": "production"}, clear=True):
            with self.assertRaises(RuntimeError):
                resolve_database_url()

    def test_development_can_use_local_sqlite_fallback(self):
        with patch.dict("os.environ", {"ENVIRONMENT": "development"}, clear=True):
            self.assertIn("stock_manager.db", resolve_database_url())

    def test_schema_prepare_is_disabled_by_default_in_production(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(auto_prepare_schema_enabled("production"))

    def test_schema_prepare_can_be_enabled_explicitly(self):
        with patch.dict("os.environ", {"GTIMS_AUTO_PREPARE_SCHEMA": "true"}, clear=True):
            self.assertTrue(auto_prepare_schema_enabled("production"))


if __name__ == "__main__":
    unittest.main()
