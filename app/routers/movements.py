from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.core import Department, Product, StockMovement, User
from app.routers.common import templates
from app.security import operational_roles, require_roles
from app.services.audit import audit_log
from app.services.documents import save_stock_document
from app.services.inventory import StockError, post_movement
from app.services.transactions import atomic

router = APIRouter(prefix="/movimentos", tags=["movimentos"])


@router.get("")
def list_movements(request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles(*operational_roles()))):
    movements = db.scalars(select(StockMovement).order_by(StockMovement.posted_at.desc()).limit(300)).all()
    return templates.TemplateResponse("movements/index.html", {"request": request, "user": user, "movements": movements})


@router.get("/novo")
def new_movement(request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles(*operational_roles()))):
    return templates.TemplateResponse("movements/form.html", {"request": request, "user": user, "products": db.scalars(select(Product).where(Product.status == "active").order_by(Product.name)).all(), "departments": db.scalars(select(Department).order_by(Department.name)).all(), "error": None})


@router.post("/novo")
async def create_movement(
    request: Request,
    product_id: int = Form(...),
    action_type: str = Form(...),
    quantity: float = Form(...),
    department_id: int | None = Form(None),
    notes: str | None = Form(None),
    reference_number: str | None = Form(None),
    document_type: str = Form("Guia"),
    document_number: str | None = Form(None),
    document_file: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*operational_roles())),
):
    product = db.get(Product, product_id)
    if not product:
        raise HTTPException(404)
    try:
        with atomic(db):
            department = db.get(Department, department_id) if department_id else None
            movement = post_movement(db, product=product, action_type=action_type, quantity=quantity, registered_by=user, destination=department.name if department else None, department_id=department_id, notes=notes, reference_number=reference_number)
            document = await save_stock_document(db, upload=document_file, uploaded_by=user, product_ids=[product.id], document_type=document_type, document_number=document_number, notes=notes)
            audit_log(db, user, "Criou movimento", "Movimentos", movement.id, new_value={"product": product.code, "action": action_type, "quantity": quantity}, request=request)
            if document:
                audit_log(db, user, "Anexou documento de stock", "Documentos", document.id, new_value={"filename": document.original_filename, "product": product.code}, request=request)
    except StockError as exc:
        return templates.TemplateResponse("movements/form.html", {"request": request, "user": user, "products": db.scalars(select(Product).where(Product.status == "active").order_by(Product.name)).all(), "departments": db.scalars(select(Department).order_by(Department.name)).all(), "error": str(exc)}, status_code=400)
    return RedirectResponse("/movimentos", status_code=303)
