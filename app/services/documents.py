import uuid
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.core import StockDocument, StockDocumentProduct, User


async def save_stock_document(
    db: Session,
    *,
    upload: UploadFile | None,
    uploaded_by: User,
    product_ids: list[int],
    document_type: str = "Guia",
    document_number: str | None = None,
    notes: str | None = None,
) -> StockDocument | None:
    if not upload or not upload.filename:
        return None
    settings = get_settings()
    suffix = Path(upload.filename).suffix
    stored_filename = f"{uuid.uuid4()}{suffix}"
    destination = settings.documents_dir / stored_filename
    content = await upload.read()
    destination.write_bytes(content)
    document = StockDocument(
        document_type=document_type or "Guia",
        document_number=document_number or None,
        original_filename=upload.filename,
        stored_filename=stored_filename,
        file_path=str(destination),
        notes=notes,
        uploaded_by_id=uploaded_by.id,
    )
    db.add(document)
    db.flush()
    for product_id in set(product_ids):
        db.add(StockDocumentProduct(document_id=document.id, product_id=product_id))
    return document
