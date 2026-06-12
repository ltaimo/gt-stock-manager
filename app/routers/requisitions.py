from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.core import Product, Requisition, RequisitionItem, RequisitionStatus, Role, User
from app.routers.common import templates
from app.security import current_user, has_permission, require_permission
from app.services.audit import audit_log
from app.services.forms import optional_int, parse_float_list, parse_int_list
from app.services.inventory import StockError
from app.services.notifications import notify_requisition_decision, notify_requisition_pending
from app.services.requisition_pdf import requisition_to_pdf
from app.services.requisitions import approve_requisition, issue_requisition, next_requisition_number
from app.services.transactions import atomic

router = APIRouter(prefix="/requisicoes", tags=["requisicoes"])


def manager_options(db: Session) -> list[User]:
    users = db.scalars(select(User).where(User.is_active == True).order_by(User.full_name)).all()
    return [user for user in users if has_permission(user, "requisitions_review")]


def default_manager_id(user: User, managers: list[User]) -> int | None:
    if has_permission(user, "requisitions_review"):
        return user.id
    return managers[0].id if managers else None


def requisition_form_context(
    request: Request,
    db: Session,
    user: User,
    error: str | None = None,
) -> dict:
    managers = manager_options(db)
    return {
        "request": request,
        "user": user,
        "products": db.scalars(select(Product).where(Product.status == "active").order_by(Product.name)).all(),
        "managers": managers,
        "default_manager_id": default_manager_id(user, managers),
        "authorization_person": "Gestor de Estoque",
        "error": error,
    }


def validate_requisition_items(
    db: Session,
    req_type: str,
    product_ids: list[int],
    quantities: list[float],
) -> list[tuple[int, Product, float]]:
    validated: list[tuple[int, Product, float]] = []
    requested_totals: dict[int, float] = {}
    is_stock_request = "REQUISI" in (req_type or "").upper()

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

    if is_stock_request:
        for _idx, product, _quantity in validated:
            requested = requested_totals[product.id]
            available = float(product.current_stock or 0)
            if available <= 0:
                raise StockError(f"O item {product.code} - {product.name} não tem stock disponível.")
            if requested > available:
                raise StockError(
                    f"A quantidade pedida para {product.code} - {product.name} excede o stock disponível ({available:g})."
                )
    return validated


@router.get("")
def list_requisitions(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    stmt = select(Requisition).order_by(Requisition.request_date.desc())
    if not has_permission(user, "requisitions_all"):
        stmt = stmt.where(Requisition.requesting_user_id == user.id)
    return templates.TemplateResponse("requisitions/index.html", {"request": request, "user": user, "requisitions": db.scalars(stmt).all()})


@router.get("/nova")
def new_requisition(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    return templates.TemplateResponse("requisitions/form.html", requisition_form_context(request, db, user))


@router.post("/nova")
def create_requisition(
    request: Request,
    operational_manager_id: str | None = Form(None),
    req_type: str = Form("REQUISIÇÃO"),
    product_id: list[str] = Form([]),
    quantity: list[str] = Form([]),
    observation: list[str] = Form([]),
    submit: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    parsed_manager_id = optional_int(operational_manager_id, "Gestor operacional")
    if len(product_id) != len(quantity):
        raise HTTPException(400, "Cada item deve ter uma quantidade correspondente.")
    parsed_product_ids = parse_int_list(product_id, "Produto")
    parsed_quantities = parse_float_list(quantity, "Quantidade")
    manager = db.get(User, parsed_manager_id) if parsed_manager_id else None
    if parsed_manager_id and not manager:
        raise HTTPException(400, "O gestor operacional selecionado não existe.")
    if req_type not in {"REQUISIÇÃO", "DEVOLUÇÃO", "OUTRO"}:
        raise HTTPException(400, "Tipo de requisição inválido.")
    try:
        validated_items = validate_requisition_items(db, req_type, parsed_product_ids, parsed_quantities)
        with atomic(db):
            req = Requisition(
                number=next_requisition_number(db),
                requesting_user_id=user.id,
                department_id=user.department_id,
                operational_manager=manager.full_name if manager else None,
                authorization_person="Gestor de Estoque",
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
    return templates.TemplateResponse("requisitions/detail.html", {"request": request, "user": user, "req": req, "error": None})


@router.post("/{req_id}/submit")
def submit_requisition(req_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    req = db.get(Requisition, req_id)
    if not req or (not has_permission(user, "requisitions_all") and req.requesting_user_id != user.id):
        raise HTTPException(404)
    if req.status != RequisitionStatus.draft.value:
        raise HTTPException(400, "Apenas requisições em rascunho podem ser submetidas.")
    try:
        validate_requisition_items(
            db,
            req.req_type,
            [item.product_id for item in req.items],
            [float(item.quantity_requested) for item in req.items],
        )
        with atomic(db):
            req.status = RequisitionStatus.submitted.value
            notify_requisition_pending(db, req)
            audit_log(db, user, "Submeteu requisição", "Requisições", req.number, request=request)
    except StockError as exc:
        return templates.TemplateResponse(
            "requisitions/detail.html",
            {"request": request, "user": user, "req": req, "error": str(exc)},
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
    can_manage = has_permission(user, "requisitions_review")
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
                approve_requisition(req)
                notify_requisition_decision(db, req, user, "Aprovada")
            else:
                quantities = {parsed_item_ids[idx]: parsed_quantities[idx] for idx in range(min(len(parsed_item_ids), len(parsed_quantities)))}
                notes = {parsed_item_ids[idx]: review_observation[idx] for idx in range(min(len(parsed_item_ids), len(review_observation)))}
                approve_requisition(req, approved_quantities=quantities, review_notes=notes)
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
        return templates.TemplateResponse("requisitions/detail.html", {"request": request, "user": user, "req": req, "error": str(exc)}, status_code=400)
    return RedirectResponse(f"/requisicoes/{req.id}", status_code=303)


@router.post("/{req_id}/issue")
def issue(req_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_permission("requisitions_issue"))):
    req = db.get(Requisition, req_id)
    if not req:
        raise HTTPException(404)
    try:
        with atomic(db):
            issue_requisition(db, req, user)
            audit_log(db, user, "Emitiu requisição", "Requisições", req.number, request=request)
    except StockError as exc:
        return templates.TemplateResponse("requisitions/detail.html", {"request": request, "user": user, "req": req, "error": str(exc)}, status_code=400)
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
