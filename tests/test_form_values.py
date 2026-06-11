import unittest

from fastapi import HTTPException

from app.services.forms import optional_int


class OptionalIntegerFormTests(unittest.TestCase):
    def test_blank_value_becomes_none(self):
        self.assertIsNone(optional_int("", "Departamento"))
        self.assertIsNone(optional_int(None, "Departamento"))
        self.assertIsNone(optional_int("  ", "Departamento"))

    def test_numeric_value_becomes_integer(self):
        self.assertEqual(optional_int("12", "Departamento"), 12)

    def test_invalid_value_returns_readable_error(self):
        with self.assertRaisesRegex(HTTPException, "Departamento inválido"):
            optional_int("abc", "Departamento")


if __name__ == "__main__":
    unittest.main()
