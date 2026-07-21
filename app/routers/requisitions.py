from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.core import Product, Requisition, RequisitionItem, RequisitionStatus, User
from app.routers.common import templates
from app.security import current_user, has_permission, require_permission
from app.services.audit import audit_log
from app.services.approval_policy import can_user_approve_assignment
from app.services.forms import optional_int, parse_float_list, parse_int_list
from app.services.inventory import StockError, active_warehouses, default_warehouse, product_warehouse_quantity, warehouse_stock_map
from app.services.notifications import notify_requisition_decision, notify_requisition_pending
from app.services.procurement import approval_label, classify_procurement
from app.services.requisition_pdf import requisition_to_pdf
from app.services.requisitions import approve_requisition, issue_requisition, next_requisition_number
from app.services.transactions import atomic

router = APIRouter(prefix="/requisicoes", tags=["requisicoes"])


def manager_options(db: Session) -> list[User]:
    users = db.scalars(select(User).where(User.is_active == True).order_by(User.full_name)).all()
    return [
        user
        for user in users
        if "gestor operacional" in user.role.name.casefold()
        or "direção" in user.role.name.casefold()
        or "direccao" in user.role.name.casefold()
        or "direcção" in user.role.name.casefold()
        or "direcao" in user.role.name.casefold()
        or "director" in user.role.name.casefold()
        or "diretor" in user.role.name.casefold()
        or (user.department and user.department.name.casefold() in {"direção", "direccao", "direcção", "direcao"})
    ]


def default_manager_id(user: User, managers: list[User]) -> int | None:
    if any(manager.id == user.id for manager in managers):
        return user.id
    return managers[0].id if managers else None


def requisition_form_context(
    request: Request,
    db: Session,
    user: User,
    error: str | None = None,
) -> dict:
    managers = manager_options(db)
    products = db.scalars(select(Product).where(Product.status == "active").order_by(Product.name)).all()
    warehouses = active_warehouses(db)
    return {
        "request": request,
        "user": user,
        "products": products,
        "products_without_price": sum(1 for product in products if float(product.unit_price or 0) <= 0),
        "warehouses": warehouses,
        "default_warehouse_id": default_warehouse(db).id,
        "stock_by_product": warehouse_stock_map(db, products),
        "managers": managers,
        "default_manager_id": default_manager_id(user, managers),
        "authorization_person": "Gestor de Estoque",
        "error": error,
    }


def is_stock_request(req_type: str) -> bool:
    return "REQUISI" in (req_type or "").upper() or (req_type or "").upper() == "REQUISICAO"


def validate_requisition_items(
    db: Session,
    req_type: str,
    product_ids: list[int],
    quantities: list[float],
    *,
    warehouse_id: int | None = None,
    require_unit_price: bool = True,
) -> list[tuple[int, Product, float]]:
    validated: list[tuple[int, Product, float]] = []
    requested_totals: dict[int, float] = {}
    stock_request = is_stock_request(req_type)

    for idx, product_id in enumerate(product_ids):
        quantity = float(quantities[idx]) if idx < len(quantities) else 0
        if quantity <= 0:
            continue
        product = db.get(Product, product_id)
        if not product or product.status != "active":
            raise StockError("Um dos produtos selecionados não está disponível.")
        requested_totals[product.id] = requested_totals.get(product.id, 0) + quantity
        validated.append((idx, product, quantity))

    if not validated:
        raise StockError("Adicione pelo menos um item com quantidade válida.")

    if stock_request:
        for _idx, product, _quantity in validated:
            requested = requested_totals[product.id]
            available = product_warehouse_quantity(db, product, warehouse_id)
            if available <= 0:
                raise StockError(f"O item {product.code} - {product.name} não tem stock disponível no armazém selecionado.")
            if requested > available:
                raise StockError(
                    f"A quantidade pedida para {product.code} - {product.name} excede o stock disponível no armazém selecionado ({available:g})."
                )
            if require_unit_price and float(product.unit_price or 0) <= 0:
                raise StockError(
                    f"O produto {product.code} - {product.name} não tem preço unitário definido. "
                    "Atualize o preço antes de submeter a requisição."
                )
    return validated


def requisition_value(validated_items: list[tuple[int, Product, float]]) -> float:
    return round(sum(float(product.unit_price or 0) * quantity for _idx, product, quantity in validated_items), 2)


def approval_assignment_for_value(db: Session, total_value: float) -> tuple[str, int | None]:
    rule = classify_procurement(db, total_value)
    if not rule:
        return "Chefe do Terminal", None
    return approval_label(rule), rule.approver_role_id


def can_review_requisition(db: Session, req: Requisition, user: User) -> bool:
    return can_user_approve_assignment(
        db,
        user,
        "requisitions_review",
        req.approver_role_id,
        req.authorization_person,
        amount=float(req.estimated_value or 0),
    )


def requisition_detail_context(request: Request, db: Session, user: User, req: Requisition, error: str | None = None) -> dict:
    return {
        "request": request,
        "user": user,
        "req": req,
        "error": error,
        "can_review_requisition": can_review_requisition(db, req, user),
        "item_stock_at_warehouse": lambda item: product_warehouse_quantity(db, item.product, req.warehouse_id),
    }


def normalize_req_type(req_type: str) -> str:
    normalized = (req_type or "").strip().upper()
    if "REQUISI" in normalized:
        return "REQUISICAO"
    if "DEVOL" in normalized:
        return "DEVOLUCAO"
    if normalized == "OUTRO":
        return "OUTRO"
    raise HTTPException(400, "Tipo de requisição inválido.")


@router.get("")
def list_requisitions(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    stmt = (
        select(Requisition)
        .where(Requisition.req_type != "REPOSICAO")
        .order_by(Requisition.request_date.desc())
    )
    if not has_permission(user, "requisitions_all"):
        stmt = stmt.where(Requisition.requesting_user_id == user.id)
    return templates.TemplateResponse(request, "requisitions/index.html", {"request": request, "user": user, "requisitions": db.scalars(stmt).all()})


@router.get("/nova")
def new_requisition(request: Request, db: Session = Depends(get_db), user: User = Depends(require_permission("stock_requisitions_create"))):
    return templates.TemplateResponse(request, "requisitions/form.html", requisition_form_context(request, db, user))


@router.post("/nova")
def create_requisition(
    request: Request,
    operational_manager_id: str | None = Form(None),
    warehouse_id: str | None = Form(None),
    req_type: str = Form("REQUISICAO"),
    product_id: list[str] = Form([]),
    quantity: list[str] = Form([]),
    observation: list[str] = Form([]),
    submit: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("stock_requisitions_create")),
):
    parsed_manager_id = optional_int(operational_manager_id, "Gestor operacional")
    parsed_warehouse_id = optional_int(warehouse_id, "Armazém")
    if len(product_id) != len(quantity):
        raise HTTPException(400, "Cada item deve ter uma quantidade correspondente.")
    parsed_product_ids = parse_int_list(product_id, "Produto")
    parsed_quantities = parse_float_list(quantity, "Quantidade")
    managers = manager_options(db)
    allowed_manager_ids = {candidate.id for candidate in managers}
    manager = db.get(User, parsed_manager_id) if parsed_manager_id else None
    if not manager or manager.id not in allowed_manager_ids:
        raise HTTPException(400, "Escolha um Gestor Operacional ou um membro da Direção.")
    req_type = normalize_req_type(req_type)
    try:
        validated_items = validate_requisition_items(
            db,
            req_type,
            parsed_product_ids,
            parsed_quantities,
            warehouse_id=parsed_warehouse_id,
            require_unit_price=bool(submit),
        )
        with atomic(db):
            total_value = requisition_value(validated_items)
            approval_label_value, approver_role_id = approval_assignment_for_value(db, total_value)
            req = Requisition(
                number=next_requisition_number(db),
                requesting_user_id=user.id,
                department_id=user.department_id,
                warehouse_id=parsed_warehouse_id,
                operational_manager=manager.full_name if manager else None,
                authorization_person=approval_label_value,
                approver_role_id=approver_role_id,
                estimated_value=total_value,
                req_type=req_type,
                status=RequisitionStatus.submitted.value if submit else RequisitionStatus.draft.value,
            )
            db.add(req)
            db.flush()
            department_name = req.department.name if req.department else None
            for source_idx, product, item_quantity in validated_items:
                db.add(
                    RequisitionItem(
                        requisition_id=req.id,
                        product_id=product.id,
                        quantity_requested=item_quantity,
                        destination=department_name,
                        observation=observation[source_idx] if source_idx < len(observation) else None,
                    )
                )
            if submit:
                notify_requisition_pending(db, req)
            audit_log(db, user, "Criou requisição", "Requisições", req.number, request=request)
    except StockError as exc:
        return templates.TemplateResponse(
            request,
            "requisitions/form.html",
            requisition_form_context(request, db, user, str(exc)),
            status_code=400,
        )
    return RedirectResponse(f"/requisicoes/{req.id}", status_code=303)


@router.get("/{req_id}")
def view_requisition(req_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    req = db.get(Requisition, req_id)
    if not req:
        raise HTTPException(404)
    if not has_permission(user, "requisitions_all") and req.requesting_user_id != user.id:
        raise HTTPException(403)
    return templates.TemplateResponse(request, "requisitions/detail.html", requisition_detail_context(request, db, user, req))


@router.post("/{req_id}/submit")
def submit_requisition(req_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    req = db.get(Requisition, req_id)
    if not req or (not has_permission(user, "requisitions_all") and req.requesting_user_id != user.id):
        raise HTTPException(404)
    if req.status != RequisitionStatus.draft.value:
        raise HTTPException(400, "Apenas requisições em rascunho podem ser submetidas.")
    try:
        validated_items = validate_requisition_items(
            db,
            req.req_type,
            [item.product_id for item in req.items],
            [float(item.quantity_requested) for item in req.items],
            warehouse_id=req.warehouse_id,
        )
        with atomic(db):
            total_value = requisition_value(validated_items)
            approval_label_value, approver_role_id = approval_assignment_for_value(db, total_value)
            req.estimated_value = total_value
            req.authorization_person = approval_label_value
            req.approver_role_id = approver_role_id
            req.status = RequisitionStatus.submitted.value
            notify_requisition_pending(db, req)
            audit_log(db, user, "Submeteu requisição", "Requisições", req.number, request=request)
    except StockError as exc:
        return templates.TemplateResponse(
            request,
            "requisitions/detail.html",
            requisition_detail_context(request, db, user, req, str(exc)),
            status_code=400,
        )
    return RedirectResponse(f"/requisicoes/{req.id}", status_code=303)


@router.post("/{req_id}/cancel")
def cancel_requisition(
    req_id: int,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    req = db.get(Requisition, req_id)
    if not req:
        raise HTTPException(404)
    can_manage = can_review_requisition(db, req, user)
    if req.requesting_user_id != user.id and not can_manage:
        raise HTTPException(403)
    if req.status not in {RequisitionStatus.draft.value, RequisitionStatus.submitted.value}:
        raise HTTPException(400, detail="Apenas requisições em rascunho ou submetidas podem ser canceladas.")

    with atomic(db):
        req.status = RequisitionStatus.cancelled.value
        audit_log(db, user, "Cancelou requisição", "Requisições", req.number, request=request)
    return RedirectResponse(f"/requisicoes/{req.id}", status_code=303)


@router.post("/{req_id}/review")
def review_requisition(
    req_id: int,
    request: Request,
    decision: str = Form(...),
    rejection_reason: str | None = Form(None),
    item_id: list[str] = Form([]),
    approved_quantity: list[str] = Form([]),
    review_observation: list[str] = Form([]),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("requisitions_review")),
):
    req = db.get(Requisition, req_id)
    if not req:
        raise HTTPException(404)
    if req.status != RequisitionStatus.submitted.value:
        raise HTTPException(400, "Apenas requisições submetidas podem ser analisadas.")
    if not can_review_requisition(db, req, user):
        raise HTTPException(403, f"Esta requisição deve ser aprovada por {req.authorization_person}.")
    if decision not in {"approve", "partial", "reject"}:
        raise HTTPException(400, "Escolha uma decisão válida.")
    parsed_item_ids = parse_int_list(item_id, "Item") if decision == "partial" else []
    parsed_quantities = parse_float_list(approved_quantity, "Quantidade aprovada") if decision == "partial" else []
    if decision == "partial":
        if len(parsed_item_ids) != len(parsed_quantities):
            raise HTTPException(400, "Cada item deve ter uma quantidade aprovada correspondente.")
        expected_ids = {item.id for item in req.items}
        if len(set(parsed_item_ids)) != len(parsed_item_ids) or set(parsed_item_ids) != expected_ids:
            raise HTTPException(400, "A seleção de itens da requisição é inválida ou incompleta.")
    try:
        with atomic(db):
            req.reviewed_by_id = user.id
            req.reviewed_at = datetime.now(timezone.utc)

            if decision == "reject":
                reason = (rejection_reason or "").strip()
                if not reason:
                    raise StockError("Indique o motivo da rejeição da requisição.")
                req.status = RequisitionStatus.rejected.value
                req.notes = reason
                for item in req.items:
                    item.quantity_issued = 0
                    item.quantity_rejected = item.quantity_requested
                    item.review_status = "Rejeitado"
                    item.review_observation = reason
                notify_requisition_decision(db, req, user, "Rejeitada")
            elif decision == "approve":
                approve_requisition(req, db=db)
                notify_requisition_decision(db, req, user, "Aprovada")
            else:
                quantities = {parsed_item_ids[idx]: parsed_quantities[idx] for idx in range(min(len(parsed_item_ids), len(parsed_quantities)))}
                notes = {parsed_item_ids[idx]: review_observation[idx] for idx in range(min(len(parsed_item_ids), len(review_observation)))}
                approve_requisition(req, approved_quantities=quantities, review_notes=notes, db=db)
                req.notes = (rejection_reason or "").strip() or req.notes
                notify_requisition_decision(db, req, user, "Aprovada parcialmente")

            audit_log(
                db,
                user,
                "Aprovou/Rejeitou requisição",
                "Requisições",
                req.number,
                new_value={"status": req.status, "decision": decision},
                request=request,
            )
    except StockError as exc:
        return templates.TemplateResponse(
            request,
            "requisitions/detail.html",
            requisition_detail_context(request, db, user, req, str(exc)),
            status_code=400,
        )
    return RedirectResponse(f"/requisicoes/{req.id}", status_code=303)


@router.post("/{req_id}/issue")
def issue(req_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_permission("requisitions_issue"))):
    req = None
    try:
        with atomic(db):
            req = db.scalar(select(Requisition).where(Requisition.id == req_id).with_for_update())
            if not req:
                raise HTTPException(404)
            issue_requisition(db, req, user)
            audit_log(db, user, "Emitiu requisição", "Requisições", req.number, request=request)
    except StockError as exc:
        if not req:
            raise HTTPException(404) from exc
        return templates.TemplateResponse(
            request,
            "requisitions/detail.html",
            requisition_detail_context(request, db, user, req, str(exc)),
            status_code=400,
        )
    return RedirectResponse(f"/requisicoes/{req.id}", status_code=303)


@router.get("/{req_id}/pdf")
def requisition_pdf(req_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    req = db.get(Requisition, req_id)
    if not req:
        raise HTTPException(404)
    if not has_permission(user, "requisitions_all") and req.requesting_user_id != user.id:
        raise HTTPException(403)
    forwarded_for = request.headers.get("x-forwarded-for", "")
    client_ip = forwarded_for.split(",")[0].strip() if forwarded_for else (request.client.host if request.client else "")
    disposition = "attachment" if request.query_params.get("download") == "1" else "inline"
    return Response(
        requisition_to_pdf(req, user, client_ip),
        media_type="application/pdf",
        headers={"Content-Disposition": f'{disposition}; filename="{req.number}.pdf"'},
    )
