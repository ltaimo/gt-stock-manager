import json
import re
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.security import DEFAULT_ROLE_PERMISSIONS, PERMISSIONS, has_permission, role_permissions
from app.services.procurement import DEFAULT_APPROVAL_MATRIX


ROOT = Path(__file__).resolve().parents[1]


class PermissionTests(unittest.TestCase):
    def test_builtin_stock_manager_can_access_movements(self):
        role = SimpleNamespace(name="Gestor de Estoque", permissions=None)
        user = SimpleNamespace(role=role)

        self.assertIn("movements", DEFAULT_ROLE_PERMISSIONS["Gestor de Estoque"])
        self.assertTrue(has_permission(user, "movements"))
        self.assertTrue(has_permission(user, "stock_adjust"))
        self.assertFalse(has_permission(user, "requisitions_review"))

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

    def test_all_default_role_permissions_are_known(self):
        configured = set().union(*DEFAULT_ROLE_PERMISSIONS.values())
        self.assertEqual(configured - set(PERMISSIONS), set())

    def test_all_route_permission_dependencies_are_registered(self):
        used = set()
        for path in (ROOT / "app" / "routers").glob("*.py"):
            source = path.read_text(encoding="utf-8")
            used.update(re.findall(r'require_permission\\("([^"]+)"\\)', source))
        self.assertEqual(used - set(PERMISSIONS), set())

    def test_default_matrix_profiles_have_approval_capabilities(self):
        for _order, _minimum, _maximum, _modality, role_name in DEFAULT_APPROVAL_MATRIX:
            permissions = DEFAULT_ROLE_PERMISSIONS[role_name]
            self.assertIn("requisitions_all", permissions)
            self.assertIn("requisitions_review", permissions)
            self.assertIn("procurement_value_approve", permissions)


if __name__ == "__main__":
    unittest.main()
