import unittest

from fastapi import HTTPException

from app.services.forms import optional_email, optional_float, optional_int, required_text


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

    def test_invalid_and_non_finite_numbers_are_rejected(self):
        with self.assertRaisesRegex(HTTPException, "número válido"):
            optional_float("um", "Quantidade")
        with self.assertRaisesRegex(HTTPException, "número finito"):
            optional_float("NaN", "Quantidade")

    def test_required_text_rejects_whitespace(self):
        with self.assertRaisesRegex(HTTPException, "não pode ficar vazio"):
            required_text("   ", "Nome")

    def test_text_length_and_email_are_validated(self):
        with self.assertRaisesRegex(HTTPException, "não pode exceder"):
            required_text("abcd", "Código", 3)
        self.assertEqual(optional_email(" pessoa@example.com "), "pessoa@example.com")
        with self.assertRaisesRegex(HTTPException, "email válido"):
            optional_email("email-invalido")


if __name__ == "__main__":
    unittest.main()
