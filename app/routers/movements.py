from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.core import Department, MovementAction, Product, StockMovement, User
from app.routers.common import templates
from app.security import operational_roles, require_roles
from app.services.audit import audit_log
from app.services.documents import save_stock_document
from app.services.forms import optional_int, required_float, required_int
from app.services.inventory import StockError, post_movement
from app.services.transactions import atomic

router = APIRouter(prefix="/movimentos", tags=["movimentos"])


def movement_form_context(request: Request, db: Session, user: User, error: str | None = None) -> dict:
    return {
        "request": request,
        "user": user,
        "products": db.scalars(select(Product).where(Product.status == "active").order_by(Product.name)).all(),
        "departments": db.scalars(select(Department).where(Department.is_active == True).order_by(Department.name)).all(),
        "requesters": db.scalars(select(User).where(User.is_active == True).order_by(User.full_name)).all(),
        "error": error,
    }


@router.get("")
def list_movements(request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles(*operational_roles()))):
    movements = db.scalars(select(StockMovement).order_by(StockMovement.posted_at.desc()).limit(300)).all()
    return templates.TemplateResponse("movements/index.html", {"request": request, "user": user, "movements": movements})


@router.get("/novo")
def new_movement(request: Request, db: Session = Depends(get_db), user: User = Depends(require_roles(*operational_roles()))):
    return templates.TemplateResponse("movements/form.html", movement_form_context(request, db, user))


@router.post("/novo")
async def create_movement(
    request: Request,
    product_id: str | None = Form(None),
    action_type: str | None = Form(None),
    quantity: str | None = Form(None),
    department_id: str | None = Form(None),
    origin: str | None = Form(None),
    responsible_person: str | None = Form(None),
    requesting_user_id: str | None = Form(None),
    notes: str | None = Form(None),
    reference_number: str | None = Form(None),
    document_type: str = Form("Guia"),
    document_number: str | None = Form(None),
    document_file: UploadFile | None = File(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_roles(*operational_roles())),
):
    parsed_product_id = required_int(product_id, "Produto")
    parsed_quantity = required_float(quantity, "Quantidade")
    parsed_department_id = optional_int(department_id, "Departamento")
    parsed_requester_id = optional_int(requesting_user_id, "Requisitante")
    clean_action = (action_type or "").strip().upper()
    if clean_action not in {
        MovementAction.entrada.value,
        MovementAction.saida.value,
        MovementAction.devolucao.value,
    }:
        raise HTTPException(400, "Escolha uma acção de movimento válida.")
    if document_type not in {"Guia", "Fatura", "Proforma", "Outro"}:
        raise HTTPException(400, "Tipo de documento inválido.")
    product = db.get(Product, parsed_product_id)
    if not product:
        raise HTTPException(404)
    try:
        with atomic(db):
            department = db.get(Department, parsed_department_id) if parsed_department_id else None
            if clean_action == MovementAction.entrada.value:
                destination = (origin or "").strip()
                if not destination:
                    raise StockError("Indique a origem ou o fornecedor da entrada.")
                if len(destination) > 180:
                    raise StockError("Origem ou fornecedor não pode exceder 180 caracteres.")
                movement_department_id = None
                movement_requester_id = None
            else:
                if not department:
                    raise StockError("Escolha o departamento de destino.")
                destination = department.name
                movement_department_id = department.id
                if parsed_requester_id and not db.get(User, parsed_requester_id):
                    raise StockError("O requisitante selecionado não existe.")
                movement_requester_id = parsed_requester_id
                if clean_action == MovementAction.saida.value and not (responsible_person or "").strip():
                    raise StockError("Indique o responsável pela entrega da saída.")
                if len((responsible_person or "").strip()) > 160:
                    raise StockError("Responsável não pode exceder 160 caracteres.")

            movement = post_movement(
                db,
                product=product,
                action_type=clean_action,
                quantity=parsed_quantity,
                registered_by=user,
                destination=destination,
                responsible_person=(responsible_person or "").strip() or None,
                requesting_user_id=movement_requester_id,
                department_id=movement_department_id,
                notes=notes,
                reference_number=reference_number,
            )
            document = await save_stock_document(db, upload=document_file, uploaded_by=user, product_ids=[product.id], document_type=document_type, document_number=document_number, notes=notes)
            audit_log(db, user, "Criou movimento", "Movimentos", movement.id, new_value={"product": product.code, "action": clean_action, "quantity": parsed_quantity}, request=request)
            if document:
                audit_log(db, user, "Anexou documento de stock", "Documentos", document.id, new_value={"filename": document.original_filename, "product": product.code}, request=request)
    except (StockError, ValueError) as exc:
        return templates.TemplateResponse(
            "movements/form.html",
            movement_form_context(request, db, user, str(exc)),
            status_code=400,
        )
    return RedirectResponse("/movimentos", status_code=303)
