from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.core import StockDocument, User
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
    return FileResponse(document.file_path, filename=document.original_filename)
