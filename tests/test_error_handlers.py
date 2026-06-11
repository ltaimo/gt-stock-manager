import asyncio
import unittest

from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.requests import Request

from app.errors import http_error_handler, validation_error_handler


def request(path: str = "/teste") -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": path,
            "headers": [],
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("127.0.0.1", 1234),
            "scheme": "http",
            "session": {},
        }
    )


class ErrorHandlerTests(unittest.TestCase):
    def test_validation_error_is_rendered_as_friendly_html(self):
        exc = RequestValidationError(
            [
                {
                    "type": "int_parsing",
                    "loc": ("body", "department_id"),
                    "msg": "Input should be a valid integer",
                    "input": "",
                }
            ]
        )

        response = asyncio.run(validation_error_handler(request(), exc))

        self.assertEqual(response.status_code, 400)
        self.assertTrue(response.media_type.startswith("text/html"))
        self.assertIn("Departamento contém um valor inválido", response.body.decode("utf-8"))
        self.assertNotIn('"detail"', response.body.decode("utf-8"))

    def test_not_found_is_rendered_as_friendly_html(self):
        response = asyncio.run(http_error_handler(request("/ausente"), HTTPException(404)))

        self.assertEqual(response.status_code, 404)
        self.assertIn("não foi encontrado", response.body.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
