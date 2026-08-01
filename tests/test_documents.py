import unittest

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.database import Base
from app.models.core import Role, StockDocument, StockDocumentFile, User
from app.routers.documents import download_document
from app.security import hash_password


class DocumentDownloadTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.db = Session(self.engine)
        role = Role(name="SuperAdmin")
        self.db.add(role)
        self.db.flush()
        self.user = User(
            full_name="Administrador",
            username="superadmin",
            password_hash=hash_password("test"),
            role_id=role.id,
        )
        self.db.add(self.user)
        self.db.flush()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def add_document(self, *, with_blob: bool) -> StockDocument:
        document = StockDocument(
            document_type="Guia",
            original_filename="guia.pdf",
            stored_filename="missing.pdf",
            file_path="/tmp/gtims/missing.pdf",
            uploaded_by_id=self.user.id,
        )
        self.db.add(document)
        self.db.flush()
        if with_blob:
            self.db.add(
                StockDocumentFile(
                    document_id=document.id,
                    content=b"%PDF-test",
                    content_type="application/pdf",
                )
            )
        self.db.commit()
        return document

    def test_download_uses_database_blob_when_file_is_not_on_disk(self):
        document = self.add_document(with_blob=True)

        response = download_document(document.id, self.db, self.user)

        self.assertEqual(response.body, b"%PDF-test")
        self.assertEqual(response.media_type, "application/pdf")
        self.assertIn("filename*=UTF-8''guia.pdf", response.headers["content-disposition"])

    def test_missing_document_file_returns_clean_404(self):
        document = self.add_document(with_blob=False)

        with self.assertRaises(HTTPException) as raised:
            download_document(document.id, self.db, self.user)

        self.assertEqual(raised.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
