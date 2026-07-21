from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.core import Department, MovementAction, Product, StockMovement, User
from app.routers.common import templates
from app.security import require_permission
from app.services.audit import audit_log
from app.services.documents import save_stock_document
from app.services.forms import optional_int, parse_float_list, parse_int_list
from app.services.inventory import (
    StockError,
    active_warehouses,
    default_warehouse,
    post_movement,
    product_warehouse_quantity,
    warehouse_stock_map,
)
from app.services.transactions import atomic

router = APIRouter(prefix="/movimentos", tags=["movimentos"])


ACTION_ALIASES = {
    "ENTRADA": MovementAction.entrada.value,
    "SAIDA": MovementAction.saida.value,
    "SAÍDA": MovementAction.saida.value,
    "SAÃDA": MovementAction.saida.value,
    "DEVOLUCAO": MovementAction.devolucao.value,
    "DEVOLUÇÃO": MovementAction.devolucao.value,
    "DEVOLUÃ‡ÃƒO": MovementAction.devolucao.value,
    "TRANSFERENCIA": MovementAction.transferencia.value,
    "TRANSFERÊNCIA": MovementAction.transferencia.value,
}


def movement_form_context(request: Request, db: Session, user: User, error: str | None = None) -> dict:
    products = db.scalars(select(Product).where(Product.status == "active").order_by(Product.name)).all()
    warehouses = active_warehouses(db)
    return {
        "request": request,
        "user": user,
        "products": products,
        "warehouses": warehouses,
        "default_warehouse_id": default_warehouse(db).id,
        "stock_by_product": warehouse_stock_map(db, products),
        "departments": db.scalars(select(Department).where(Department.is_active == True).order_by(Department.name)).all(),
        "requesters": db.scalars(select(User).where(User.is_active == True).order_by(User.full_name)).all(),
        "error": error,
    }


@router.get("")
def list_movements(request: Request, db: Session = Depends(get_db), user: User = Depends(require_permission("movements"))):
    movements = db.scalars(select(StockMovement).order_by(StockMovement.posted_at.desc()).limit(300)).all()
    return templates.TemplateResponse(request, "movements/index.html", {"request": request, "user": user, "movements": movements})


@router.get("/novo")
def new_movement(request: Request, db: Session = Depends(get_db), user: User = Depends(require_permission("movements"))):
    return templates.TemplateResponse(request, "movements/form.html", movement_form_context(request, db, user))


def validate_movement_lines(
    db: Session,
    product_ids: list[int],
    quantities: list[float],
    action_type: str,
    warehouse_id: int | None,
) -> list[tuple[Product, float]]:
    lines: list[tuple[Product, float]] = []
    requested_totals: dict[int, float] = {}
    for index, product_id in enumerate(product_ids):
        quantity = quantities[index]
        if quantity <= 0:
            raise StockError("A quantidade deve ser superior a zero.")
        product = db.get(Product, product_id)
        if not product or product.status != "active":
            raise StockError("Um dos produtos selecionados não está disponível.")
        lines.append((product, quantity))
        requested_totals[product.id] = requested_totals.get(product.id, 0) + quantity

    if not lines:
        raise StockError("Adicione pelo menos um produto ao movimento.")

    if action_type in {MovementAction.saida.value, MovementAction.transferencia.value}:
        checked: set[int] = set()
        for product, _quantity in lines:
            if product.id in checked:
                continue
            checked.add(product.id)
            available = product_warehouse_quantity(db, product, warehouse_id)
            requested = requested_totals[product.id]
            if requested > available:
                raise StockError(
                    f"A saída total para {product.code} - {product.name} excede o stock disponível no armazém selecionado ({available:g})."
                )
    return lines


@router.post("/novo")
async def create_movement(
    request: Request,
    product_id: list[str] = Form([]),
    action_type: str | None = Form(None),
    quantity: list[str] = Form([]),
    warehouse_id: str | None = Form(None),
    destination_warehouse_id: str | None = Form(None),
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
    user: User = Depends(require_permission("movements")),
):
    try:
        if len(product_id) != len(quantity):
            raise StockError("Cada produto deve ter uma quantidade correspondente.")
        parsed_product_ids = parse_int_list(product_id, "Produto")
        parsed_quantities = parse_float_list(quantity, "Quantidade")
        parsed_warehouse_id = optional_int(warehouse_id, "Armazém")
        parsed_destination_warehouse_id = optional_int(destination_warehouse_id, "Armazém de destino")
        parsed_department_id = optional_int(department_id, "Departamento")
        parsed_requester_id = optional_int(requesting_user_id, "Requisitante")
        raw_action = (action_type or "").strip().upper()
        clean_action = ACTION_ALIASES.get(raw_action, raw_action)
        allowed_actions = {
            MovementAction.entrada.value,
            MovementAction.saida.value,
            MovementAction.devolucao.value,
            MovementAction.transferencia.value,
        }
        if clean_action not in allowed_actions:
            raise StockError("Escolha uma ação de movimento válida.")
        if document_type not in {"Guia", "Fatura", "Proforma", "Outro"}:
            raise StockError("Tipo de documento inválido.")
        lines = validate_movement_lines(db, parsed_product_ids, parsed_quantities, clean_action, parsed_warehouse_id)

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
            elif clean_action == MovementAction.transferencia.value:
                if not parsed_destination_warehouse_id:
                    raise StockError("Escolha o armazém de destino da transferência.")
                destination = None
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

            movements = []
            for product, line_quantity in lines:
                movements.append(
                    post_movement(
                        db,
                        product=product,
                        action_type=clean_action,
                        quantity=line_quantity,
                        registered_by=user,
                        destination=destination,
                        responsible_person=(responsible_person or "").strip() or None,
                        requesting_user_id=movement_requester_id,
                        department_id=movement_department_id,
                        notes=notes,
                        reference_number=reference_number,
                        warehouse_id=parsed_warehouse_id,
                        destination_warehouse_id=parsed_destination_warehouse_id,
                    )
                )

            product_ids = sorted({product.id for product, _quantity in lines})
            document = await save_stock_document(
                db,
                upload=document_file,
                uploaded_by=user,
                product_ids=product_ids,
                document_type=document_type,
                document_number=document_number,
                notes=notes,
            )
            audit_log(
                db,
                user,
                "Criou movimento" if len(movements) == 1 else "Criou movimentos em lote",
                "Movimentos",
                movements[0].id,
                new_value={
                    "items": [{"product": product.code, "quantity": line_quantity} for product, line_quantity in lines],
                    "action": clean_action,
                    "warehouse_id": parsed_warehouse_id,
                    "destination_warehouse_id": parsed_destination_warehouse_id,
                },
                request=request,
            )
            if document:
                audit_log(
                    db,
                    user,
                    "Anexou documento de stock",
                    "Documentos",
                    document.id,
                    new_value={"filename": document.original_filename, "products": product_ids},
                    request=request,
                )
    except (StockError, ValueError, HTTPException) as exc:
        message = exc.detail if isinstance(exc, HTTPException) else str(exc)
        return templates.TemplateResponse(
            request,
            "movements/form.html",
            movement_form_context(request, db, user, message),
            status_code=400,
        )
    return RedirectResponse("/movimentos", status_code=303)
