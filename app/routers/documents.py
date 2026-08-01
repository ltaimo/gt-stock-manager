from pathlib import Path
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.core import StockDocument, StockDocumentFile, User
from app.routers.common import templates
from app.security import require_permission

router = APIRouter(prefix="/documentos", tags=["documentos"])


@router.get("")
def list_documents(request: Request, db: Session = Depends(get_db), user: User = Depends(require_permission("documents"))):
    documents = db.scalars(select(StockDocument).order_by(StockDocument.created_at.desc()).limit(300)).all()
    return templates.TemplateResponse(request, "documents/index.html", {"request": request, "user": user, "documents": documents})


@router.get("/{document_id}/download")
def download_document(document_id: int, db: Session = Depends(get_db), user: User = Depends(require_permission("documents"))):
    document = db.get(StockDocument, document_id)
    if not document:
        raise HTTPException(404)
    file_path = Path(document.file_path)
    if file_path.exists():
        return FileResponse(file_path, filename=document.original_filename)
    stored_file = db.get(StockDocumentFile, document.id)
    if stored_file:
        quoted_name = quote(document.original_filename)
        return Response(
            stored_file.content,
            media_type=stored_file.content_type or "application/octet-stream",
            headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quoted_name}"},
        )
    raise HTTPException(404, "O ficheiro deste documento nao esta disponivel no armazenamento atual.")
