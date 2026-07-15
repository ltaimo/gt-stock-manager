import unittest
from unittest.mock import patch

from app.config import resolve_database_url


class ConfigTests(unittest.TestCase):
    def test_production_requires_database_url(self):
        with patch.dict("os.environ", {"ENVIRONMENT": "production"}, clear=True):
            with self.assertRaises(RuntimeError):
                resolve_database_url()

    def test_development_can_use_local_sqlite_fallback(self):
        with patch.dict("os.environ", {"ENVIRONMENT": "development"}, clear=True):
            self.assertIn("stock_manager.db", resolve_database_url())


if __name__ == "__main__":
    unittest.main()
