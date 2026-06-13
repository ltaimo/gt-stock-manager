import json
import unittest
from types import SimpleNamespace

from app.security import DEFAULT_ROLE_PERMISSIONS, has_permission, role_permissions


class PermissionTests(unittest.TestCase):
    def test_builtin_stock_manager_can_access_movements(self):
        role = SimpleNamespace(name="Gestor de Estoque", permissions=None)
        user = SimpleNamespace(role=role)

        self.assertIn("movements", DEFAULT_ROLE_PERMISSIONS["Gestor de Estoque"])
        self.assertTrue(has_permission(user, "movements"))
        self.assertTrue(has_permission(user, "stock_adjust"))

    def test_custom_profile_uses_configured_permissions(self):
        role = SimpleNamespace(name="HSE Officer", permissions=json.dumps(["documents", "reports"]))
        user = SimpleNamespace(role=role)

        self.assertEqual(role_permissions(role), {"documents", "reports"})
        self.assertTrue(has_permission(user, "documents"))
        self.assertFalse(has_permission(user, "movements"))

    def test_superadmin_always_has_every_permission(self):
        role = SimpleNamespace(name="SuperAdmin", permissions="[]")
        user = SimpleNamespace(role=role)

        self.assertTrue(has_permission(user, "profiles_manage"))
        self.assertTrue(has_permission(user, "stock_reset"))

    def test_admin_does_not_adjust_stock_by_default(self):
        role = SimpleNamespace(name="Admin", permissions=None)
        user = SimpleNamespace(role=role)

        self.assertFalse(has_permission(user, "stock_adjust"))


if __name__ == "__main__":
    unittest.main()
