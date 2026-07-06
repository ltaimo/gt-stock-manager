from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.i18n import language_for
from app.models.core import MovementAction, ProcurementCase, Product, Requisition, RequisitionItem, RequisitionStatus, User
from app.routers.common import templates
from app.security import current_user, has_permission, matches_approval_assignment, require_permission
from app.services.audit import audit_log
from app.services.forms import optional_float, optional_int, parse_float_list, parse_int_list, required_float, required_text
from app.services.inventory import StockError, post_movement
from app.services.notifications import (
    notify_procurement_budget_pending,
    notify_procurement_classification_pending,
    notify_procurement_permission,
    notify_procurement_requester,
)
from app.services.notifications import send_email
from app.services.procurement import (
    classify_procurement,
    days_open,
    next_non_stock_number,
    next_replenishment_number,
    suggested_replenishment_quantity,
)
from app.services.procurement import approval_label
from app.services.procurement_pdf import procurement_form_to_pdf
from app.services.tdr_pdf import terms_of_reference_to_pdf
from app.services.transactions import atomic

router = APIRouter(prefix="/procurement", tags=["procurement"])

PROCUREMENT_WORKFLOW_PERMISSIONS = {
    "procurement_manage",
    "budget_verify",
    "procurement_tor_approve_hod",
    "procurement_tor_approve_terminal",
    "procurement_value_approve",
    "procurement_technical_evaluate",
    "procurement_financial_evaluate",
    "procurement_hse_validate",
    "procurement_receive",
    "procurement_archive",
}


def parse_date(value: str | None) -> datetime | None:
    cleaned = str(value or "").strip()
    if not cleaned:
        return None
    try:
        return datetime.fromisoformat(cleaned).replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise HTTPException(400, "A data requerida deve ser uma data válida.") from exc


def can_view_case(user: User, case: ProcurementCase) -> bool:
    return (
        any(has_permission(user, permission) for permission in PROCUREMENT_WORKFLOW_PERMISSIONS)
        or case.requisition.requesting_user_id == user.id
    )


def can_update_tracker(user: User) -> bool:
    return has_permission(user, "procurement_manage")


def can_approve_by_matrix(db: Session, case: ProcurementCase, user: User) -> bool:
    amount = case.po_value if case.po_value is not None else case.estimated_budget
    rule = classify_procurement(db, amount)
    if not rule:
        return False
    return matches_approval_assignment(
        user,
        "procurement_value_approve",
        rule.approver_role_id,
        rule.final_approval,
    )


def case_or_404(db: Session, case_id: int, user: User) -> ProcurementCase:
    case = db.get(ProcurementCase, case_id)
    if not case:
        raise HTTPException(404)
    if not can_view_case(user, case):
        raise HTTPException(403)
    return case


@router.get("")
def tracker(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    stmt = select(ProcurementCase).join(ProcurementCase.requisition).order_by(ProcurementCase.created_at.desc())
    if not any(has_permission(user, permission) for permission in PROCUREMENT_WORKFLOW_PERMISSIONS):
        stmt = stmt.where(Requisition.requesting_user_id == user.id)
    cases = db.scalars(stmt).all()
    return templates.TemplateResponse(request, "procurement/index.html",
        {"request": request, "user": user, "cases": cases, "days_open": days_open},
    )


@router.get("/nova")
def new_non_stock(request: Request, user: User = Depends(require_permission("non_stock_requisitions_create"))):
    return templates.TemplateResponse(request, "procurement/form.html", {"request": request, "user": user, "error": None})


@router.post("/nova")
def create_non_stock(
    request: Request,
    description: str | None = Form(None),
    job_title: str | None = Form(None),
    tdr_number: str | None = Form(None),
    justification: str | None = Form(None),
    cost_center: str | None = Form(None),
    priority: str = Form("Normal"),
    item_type: str = Form("Bem"),
    estimated_budget: str | None = Form(None),
    required_date: str | None = Form(None),
    technical_requirements: str | None = Form(None),
    hse_requirements: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("non_stock_requisitions_create")),
):
    clean_description = required_text(description, "Descricao / escopo", 2000)
    budget = required_float(estimated_budget, "Orcamento estimado")
    if budget < 0:
        raise HTTPException(400, "O orçamento estimado não pode ser negativo.")
    if priority not in {"Baixa", "Normal", "Alta", "Urgente"}:
        raise HTTPException(400, "Prioridade inválida.")
    if item_type not in {"Bem", "Serviço", "Obra"}:
        raise HTTPException(400, "Tipo inválido.")

    with atomic(db):
        req = Requisition(
            number=next_non_stock_number(db),
            requesting_user_id=user.id,
            department_id=user.department_id,
            req_type="NS",
            status=RequisitionStatus.submitted.value,
            notes=(justification or "").strip() or None,
        )
        db.add(req)
        db.flush()
        clean_tdr_number = (tdr_number or "").strip() or f"TdR-{req.number}"
        case = ProcurementCase(
            requisition_id=req.id,
            tdr_number=clean_tdr_number,
            job_title=(job_title or "").strip() or clean_description[:120],
            description=clean_description,
            justification=(justification or "").strip() or None,
            cost_center=(cost_center or "").strip() or None,
            priority=priority,
            item_type=item_type,
            technical_requirements=(technical_requirements or "").strip() or None,
            hse_requirements=(hse_requirements or "").strip() or None,
            estimated_budget=budget,
            required_date=parse_date(required_date),
            tor_status="Pending HOD Approval",
            status="Pending HOD TdR Approval",
            hse_documents_status="Pending" if (hse_requirements or "").strip() else "Not Required",
        )
        db.add(case)
        db.flush()
        notify_procurement_permission(
            db,
            case,
            "procurement_tor_approve_hod",
            f"TdR para aprovação HOD: {req.number}",
            f"O processo {req.number} aguarda aprovação do HOD/Chefe do Departamento.",
        )
        audit_log(db, user, "Criou requisição non-stock", "Procurement", req.number, request=request)
    return RedirectResponse(f"/procurement/{case.id}", status_code=303)


def replenishment_form_context(request: Request, db: Session, user: User, error: str | None = None) -> dict:
    selected_ids = {
        int(value)
        for value in request.query_params.getlist("product_id")
        if str(value).isdigit()
    }
    products = db.scalars(
        select(Product).where(Product.status == "active").order_by(Product.name)
    ).all()
    products.sort(
        key=lambda product: (
            0 if suggested_replenishment_quantity(product) > 0 else 1,
            product.name.casefold(),
        )
    )
    return {
        "request": request,
        "user": user,
        "products": products,
        "selected_ids": selected_ids,
        "suggested_quantity": suggested_replenishment_quantity,
        "error": error,
    }


@router.get("/reposicao/nova")
def new_replenishment(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("stock_replenishment_create")),
):
    return templates.TemplateResponse(request, "procurement/replenishment_form.html",
        replenishment_form_context(request, db, user),
    )


@router.post("/reposicao/nova")
def create_replenishment(
    request: Request,
    product_id: list[str] = Form([]),
    quantity: list[str] = Form([]),
    estimated_unit_price: list[str] = Form([]),
    justification: str | None = Form(None),
    cost_center: str | None = Form(None),
    priority: str = Form("Normal"),
    required_date: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("stock_replenishment_create")),
):
    if not product_id:
        raise HTTPException(400, "Selecione pelo menos um produto para reposição.")
    if len(product_id) != len(quantity) or len(product_id) != len(estimated_unit_price):
        raise HTTPException(400, "Cada produto deve ter quantidade e preço estimado correspondentes.")
    product_ids = parse_int_list(product_id, "Produto")
    quantities = parse_float_list(quantity, "Quantidade")
    prices = parse_float_list(estimated_unit_price, "Preço unitário estimado")
    if len(set(product_ids)) != len(product_ids):
        raise HTTPException(400, "Cada produto só pode aparecer uma vez no pedido.")
    if priority not in {"Baixa", "Normal", "Alta", "Urgente"}:
        raise HTTPException(400, "Prioridade inválida.")

    selected_products: list[tuple[Product, float, float]] = []
    for product_id_value, quantity_value, price_value in zip(product_ids, quantities, prices):
        product = db.get(Product, product_id_value)
        if not product or product.status != "active":
            raise HTTPException(400, "Um dos produtos selecionados já não está disponível.")
        if quantity_value <= 0:
            raise HTTPException(400, f"A quantidade para {product.code} deve ser superior a zero.")
        if price_value <= 0:
            raise HTTPException(400, f"Indique um preço estimado válido para {product.code} - {product.name}.")
        selected_products.append((product, quantity_value, price_value))

    total_value = round(sum(quantity_value * price_value for _, quantity_value, price_value in selected_products), 2)
    approval_rule = classify_procurement(db, total_value)
    if not approval_rule:
        raise HTTPException(400, "Não existe uma regra ativa na matriz de aprovação para o valor deste pedido.")
    description = "Reposição de stock: " + ", ".join(
        f"{product.code} - {product.name} ({quantity_value:g} {product.unit})"
        for product, quantity_value, _ in selected_products
    )
    clean_justification = (justification or "").strip() or "Reposição dos níveis de stock para continuidade operacional."

    with atomic(db):
        req = Requisition(
            number=next_replenishment_number(db),
            requesting_user_id=user.id,
            department_id=user.department_id,
            estimated_value=total_value,
            authorization_person=approval_label(approval_rule),
            req_type="REPOSICAO",
            status=RequisitionStatus.submitted.value,
            notes=clean_justification,
        )
        db.add(req)
        db.flush()
        for product, quantity_value, price_value in selected_products:
            db.add(
                RequisitionItem(
                    requisition_id=req.id,
                    product_id=product.id,
                    quantity_requested=quantity_value,
                    estimated_unit_price=price_value,
                    destination="Armazém / Stock",
                    observation=clean_justification,
                )
            )
        case = ProcurementCase(
            requisition_id=req.id,
            tdr_number=f"PR-{req.number}",
            job_title=f"Pedido de reposição de stock {req.number}",
            description=description,
            justification=clean_justification,
            cost_center=(cost_center or "").strip() or None,
            priority=priority,
            item_type="Bem",
            technical_requirements="Fornecer os produtos e quantidades constantes no pedido de reposição.",
            estimated_budget=total_value,
            modality=approval_rule.modality,
            approval_route=approval_label(approval_rule),
            required_date=parse_date(required_date),
            tor_status="Pending HOD Approval",
            status="Pending HOD TdR Approval",
            hse_documents_status="Not Required",
        )
        db.add(case)
        db.flush()
        notify_procurement_permission(
            db,
            case,
            "procurement_tor_approve_hod",
            f"Reposição de stock para aprovação: {req.number}",
            f"O pedido {req.number}, no valor estimado de {total_value:.2f} MZN, aguarda aprovação do HOD.",
        )
        audit_log(
            db,
            user,
            "Criou pedido de reposição de stock",
            "Procurement",
            req.number,
            new_value={"items": len(selected_products), "estimated_value": total_value},
            request=request,
        )
    return RedirectResponse(f"/procurement/{case.id}", status_code=303)


@router.get("/matriz")
def matrix(request: Request, db: Session = Depends(get_db), user: User = Depends(require_permission("procurement_settings"))):
    return RedirectResponse("/configuracoes/matriz", status_code=303)


@router.post("/matriz")
def save_matrix(user: User = Depends(require_permission("procurement_settings"))):
    return RedirectResponse("/configuracoes/matriz", status_code=303)


@router.get("/{case_id}")
def detail(case_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    case = case_or_404(db, case_id, user)
    officers = db.scalars(select(User).where(User.is_active == True).order_by(User.full_name)).all()
    return templates.TemplateResponse(request, "procurement/detail.html",
        {
            "request": request,
            "user": user,
            "case": case,
            "officers": officers,
            "days_open": days_open,
            "error": None,
            "can_update_tracker": can_update_tracker(user),
            "can_approve_by_matrix": can_approve_by_matrix(db, case, user),
        },
    )


@router.post("/{case_id}/tdr/hod")
def approve_tdr_hod(
    case_id: int,
    request: Request,
    decision: str = Form(...),
    comments: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement_tor_approve_hod")),
):
    case = case_or_404(db, case_id, user)
    if decision not in {"approve", "return"}:
        raise HTTPException(400, "Escolha uma decisão válida.")
    with atomic(db):
        case.comments = (comments or "").strip() or case.comments
        if decision == "approve":
            case.tor_status = "Pending Terminal Manager Approval"
            case.hod_approved_by_id = user.id
            case.hod_approved_at = datetime.now(timezone.utc)
            case.status = "Pending Terminal Manager TdR Approval"
            notify_procurement_permission(
                db,
                case,
                "procurement_tor_approve_terminal",
                f"TdR para aprovação Terminal Manager: {case.requisition.number}",
                f"O HOD aprovou o TdR do processo {case.requisition.number}.",
            )
        else:
            case.tor_status = "Returned for Correction"
            case.status = "Returned - TdR Correction"
            case.requisition.status = RequisitionStatus.rejected.value
            notify_procurement_requester(
                db,
                case,
                f"TdR devolvido para correção: {case.requisition.number}",
                f"O HOD devolveu o TdR do processo {case.requisition.number} para correção.",
            )
        audit_log(db, user, "Decidiu TdR como HOD", "Procurement", case.requisition.number, new_value={"status": case.status}, request=request)
    return RedirectResponse(f"/procurement/{case.id}", status_code=303)


@router.post("/{case_id}/tdr/terminal")
def approve_tdr_terminal(
    case_id: int,
    request: Request,
    decision: str = Form(...),
    comments: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement_tor_approve_terminal")),
):
    case = case_or_404(db, case_id, user)
    if decision not in {"approve", "return"}:
        raise HTTPException(400, "Escolha uma decisão válida.")
    if case.tor_status not in {"Pending Terminal Manager Approval", "Approved"} and decision == "approve":
        raise HTTPException(400, "O TdR ainda precisa de aprovação HOD antes do Terminal Manager.")
    with atomic(db):
        case.comments = (comments or "").strip() or case.comments
        if decision == "approve":
            case.tor_status = "Approved"
            case.terminal_manager_approved_by_id = user.id
            case.terminal_manager_approved_at = datetime.now(timezone.utc)
            case.status = "Pending Budget Verification"
            notify_procurement_budget_pending(db, case.requisition)
        else:
            case.tor_status = "Returned for Correction"
            case.status = "Returned - TdR Correction"
            case.requisition.status = RequisitionStatus.rejected.value
            notify_procurement_requester(
                db,
                case,
                f"TdR devolvido pelo Terminal Manager: {case.requisition.number}",
                f"O Terminal Manager devolveu o TdR do processo {case.requisition.number} para correção.",
            )
        audit_log(db, user, "Decidiu TdR como Terminal Manager", "Procurement", case.requisition.number, new_value={"status": case.status}, request=request)
    return RedirectResponse(f"/procurement/{case.id}", status_code=303)


@router.post("/{case_id}/orcamento")
def verify_budget(
    case_id: int,
    request: Request,
    decision: str = Form(...),
    comments: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("budget_verify")),
):
    case = case_or_404(db, case_id, user)
    if case.tor_status != "Approved":
        raise HTTPException(400, "O TdR deve estar aprovado pelo HOD e pelo Diretor do Terminal antes da verificação do orçamento.")
    if decision not in {"confirm", "return"}:
        raise HTTPException(400, "Escolha uma decisão válida.")
    with atomic(db):
        case.budget_confirmed = decision == "confirm"
        case.budget_confirmed_at = datetime.now(timezone.utc)
        case.budget_verified_by_id = user.id
        case.comments = (comments or "").strip() or case.comments
        if decision == "confirm":
            case.status = "Pending Procurement Classification"
            case.requisition.status = RequisitionStatus.submitted.value
            notify_procurement_classification_pending(db, case.requisition)
        else:
            case.status = "Returned - No Budget"
            case.requisition.status = RequisitionStatus.rejected.value
        audit_log(db, user, "Verificou orçamento", "Procurement", case.requisition.number, new_value={"status": case.status}, request=request)
    return RedirectResponse(f"/procurement/{case.id}", status_code=303)


@router.post("/{case_id}/classificar")
def classify_case(
    case_id: int,
    request: Request,
    procurement_officer_id: str | None = Form(None),
    technical_evaluation_required: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement_manage")),
):
    case = case_or_404(db, case_id, user)
    officer_id = optional_int(procurement_officer_id, "Procurement officer")
    officer = db.get(User, officer_id) if officer_id else None
    rule = classify_procurement(db, case.estimated_budget)
    if not rule:
        raise HTTPException(400, "Não existe uma regra ativa na matriz para este valor.")
    with atomic(db):
        case.procurement_officer_id = officer.id if officer else None
        case.modality = rule.modality
        case.approval_route = approval_label(rule)
        case.approval_status = "Pending"
        case.technical_evaluation_required = technical_evaluation_required == "1"
        case.technical_evaluation_status = "Pending" if case.technical_evaluation_required else "Not Required"
        case.status = "Pending Approval"
        audit_log(db, user, "Classificou procurement", "Procurement", case.requisition.number, new_value={"modality": case.modality, "approval": case.approval_route}, request=request)
    return RedirectResponse(f"/procurement/{case.id}", status_code=303)


@router.post("/{case_id}/aprovar-valor")
def approve_by_value(
    case_id: int,
    request: Request,
    decision: str = Form(...),
    comments: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    case = case_or_404(db, case_id, user)
    if case.status != "Pending Approval" or case.approval_status != "Pending":
        raise HTTPException(400, "Este processo não está pendente de aprovação por valor.")
    if not can_approve_by_matrix(db, case, user):
        raise HTTPException(403, f"Este processo deve ser aprovado pelo perfil {case.approval_route or 'definido na matriz'}.")
    if decision not in {"approve", "return"}:
        raise HTTPException(400, "Escolha uma decisão válida.")
    clean_comments = (comments or "").strip()
    if decision == "return" and not clean_comments:
        raise HTTPException(400, "Indique o motivo para devolver o processo.")

    with atomic(db):
        case.approval_status = "Approved" if decision == "approve" else "Returned"
        case.status = "RFQ/RFP/Tender Running" if decision == "approve" else "Returned - Approval"
        case.comments = clean_comments or case.comments
        notify_procurement_requester(
            db,
            case,
            f"Decisão de aprovação: {case.requisition.number}",
            (
                f"O processo {case.requisition.number} foi aprovado por {user.full_name}."
                if decision == "approve"
                else f"O processo {case.requisition.number} foi devolvido por {user.full_name}: {clean_comments}"
            ),
        )
        audit_log(
            db,
            user,
            "Aprovou processo pela matriz" if decision == "approve" else "Devolveu processo pela matriz",
            "Procurement",
            case.requisition.number,
            new_value={"approval_status": case.approval_status, "approval_route": case.approval_route},
            request=request,
        )
    return RedirectResponse(f"/procurement/{case.id}", status_code=303)


@router.get("/{case_id}/formulario")
def procurement_form_pdf(case_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    case = case_or_404(db, case_id, user)
    disposition = "attachment" if request.query_params.get("download") == "1" else "inline"
    return Response(
        procurement_form_to_pdf(case, user),
        media_type="application/pdf",
        headers={"Content-Disposition": f'{disposition}; filename="{case.requisition.number}-NS.pdf"'},
    )


@router.get("/{case_id}/tdr")
def tdr_pdf(case_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    case = case_or_404(db, case_id, user)
    disposition = "attachment" if request.query_params.get("download") == "1" else "inline"
    filename = f"{case.tdr_number or 'TdR-' + case.requisition.number}.pdf"
    return Response(
        terms_of_reference_to_pdf(case, user),
        media_type="application/pdf",
        headers={"Content-Disposition": f'{disposition}; filename="{filename}"'},
    )


@router.post("/{case_id}/tdr/enviar")
def send_tdr_email(
    case_id: int,
    request: Request,
    email_to: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    case = case_or_404(db, case_id, user)
    target = (email_to or "").strip() or case.requisition.requesting_user.email
    if not target:
        raise HTTPException(400, "Indique o e-mail de destino ou configure e-mail no requisitante.")
    is_replenishment = case.requisition.req_type == "REPOSICAO"
    filename = (
        f"{case.requisition.number}-Pedido-Reposicao.pdf"
        if is_replenishment
        else f"{case.tdr_number or 'TdR-' + case.requisition.number}.pdf"
    )
    pdf = procurement_form_to_pdf(case, user) if is_replenishment else terms_of_reference_to_pdf(case, user)
    if language_for(user, request) == "en":
        subject = (
            f"Stock Replenishment Request - {case.requisition.number}"
            if is_replenishment
            else f"Term of Reference - {case.tdr_number or case.requisition.number}"
        )
        body = (
            f"Please find attached the {'stock replenishment request' if is_replenishment else 'Term of Reference'} for process {case.requisition.number}.\n\n"
            f"Job title: {case.job_title or case.description[:120]}\n"
            f"Base value: {float(case.po_value or case.estimated_budget or 0):.2f} MZN\n"
            f"Value-based approval: {case.approval_route or 'To be defined'}\n\n"
            "The PDF is attached."
        )
    else:
        subject = (
            f"Pedido de Reposição de Stock - {case.requisition.number}"
            if is_replenishment
            else f"Termo de Referência - {case.tdr_number or case.requisition.number}"
        )
        body = (
            f"Segue, em anexo, o {'pedido de reposição de stock' if is_replenishment else 'Termo de Referência'} do processo {case.requisition.number}.\n\n"
            f"Título do trabalho: {case.job_title or case.description[:120]}\n"
            f"Valor base: {float(case.po_value or case.estimated_budget or 0):.2f} MZN\n"
            f"Aprovação por valor: {case.approval_route or 'Por definir'}\n\n"
            "O PDF segue em anexo."
        )
    with atomic(db):
        send_email(target, subject, body, attachments=[(filename, pdf, "application/pdf")])
        audit_log(
            db,
            user,
            "Enviou pedido de reposição por e-mail" if is_replenishment else "Enviou TdR por e-mail",
            "Procurement",
            case.requisition.number,
            new_value={"to": target},
            request=request,
        )
    return RedirectResponse(f"/procurement/{case.id}", status_code=303)


@router.post("/{case_id}/receber-reposicao")
def receive_replenishment(
    case_id: int,
    request: Request,
    item_id: list[str] = Form([]),
    received_quantity: list[str] = Form([]),
    receipt_note: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement_receive")),
):
    case = case_or_404(db, case_id, user)
    if case.requisition.req_type != "REPOSICAO":
        raise HTTPException(400, "Este processo não é um pedido de reposição de stock.")
    if not case.po_number:
        raise HTTPException(400, "Registe a PO antes de receber produtos para o stock.")
    if case.approval_status != "Approved":
        raise HTTPException(400, "A aprovação do processo deve estar concluída antes da receção.")
    if len(item_id) != len(received_quantity):
        raise HTTPException(400, "Cada item deve ter uma quantidade recebida correspondente.")
    parsed_item_ids = parse_int_list(item_id, "Item")
    parsed_quantities = parse_float_list(received_quantity, "Quantidade recebida")
    if len(set(parsed_item_ids)) != len(parsed_item_ids):
        raise HTTPException(400, "A lista de itens recebidos contém duplicados.")
    clean_note = required_text(receipt_note, "Nota de recebimento", 1000)

    try:
        with atomic(db):
            items = db.scalars(
                select(RequisitionItem)
                .where(
                    RequisitionItem.requisition_id == case.requisition_id,
                    RequisitionItem.id.in_(parsed_item_ids),
                )
                .with_for_update()
            ).all()
            items_by_id = {item.id: item for item in items}
            if set(items_by_id) != set(parsed_item_ids):
                raise StockError("Um dos itens selecionados não pertence a este pedido.")

            received_any = False
            for item_id_value, quantity_value in zip(parsed_item_ids, parsed_quantities):
                if quantity_value < 0:
                    raise StockError("A quantidade recebida não pode ser negativa.")
                if quantity_value == 0:
                    continue
                item = items_by_id[item_id_value]
                remaining = float(item.quantity_requested or 0) - float(item.quantity_received or 0)
                if quantity_value > remaining:
                    raise StockError(
                        f"A receção de {item.product.code} excede a quantidade pendente ({remaining:g})."
                    )
                post_movement(
                    db,
                    product=item.product,
                    action_type=MovementAction.entrada.value,
                    quantity=quantity_value,
                    registered_by=user,
                    destination="Armazém / Stock",
                    responsible_person=user.full_name,
                    department_id=user.department_id,
                    notes=clean_note,
                    reference_number=case.po_number,
                )
                item.quantity_received = float(item.quantity_received or 0) + quantity_value
                item.review_status = (
                    "Recebido"
                    if float(item.quantity_received) >= float(item.quantity_requested)
                    else "Recebido parcialmente"
                )
                received_any = True

            if not received_any:
                raise StockError("Indique pelo menos uma quantidade recebida superior a zero.")

            complete = all(
                float(item.quantity_received or 0) >= float(item.quantity_requested or 0)
                for item in case.requisition.items
            )
            case.receipt_status = "Received" if complete else "Partial"
            case.execution_status = "Delivered" if complete else "In Progress"
            case.status = "Receiving" if not complete else "Ready for Archive"
            case.receipt_note = clean_note
            notify_procurement_requester(
                db,
                case,
                f"Reposição recebida: {case.requisition.number}",
                (
                    f"Os produtos do pedido {case.requisition.number} foram recebidos no stock."
                    if complete
                    else f"Foi registada uma receção parcial do pedido {case.requisition.number}."
                ),
            )
            audit_log(
                db,
                user,
                "Recebeu produtos de reposição",
                "Procurement",
                case.requisition.number,
                new_value={"receipt_status": case.receipt_status, "po": case.po_number},
                request=request,
            )
    except StockError as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(f"/procurement/{case.id}", status_code=303)


@router.post("/{case_id}/tracker")
def update_tracker(
    case_id: int,
    request: Request,
    status: str | None = Form(None),
    approval_status: str | None = Form(None),
    rfq_rfp_tender_number: str | None = Form(None),
    suppliers_invited: str | None = Form(None),
    quotations_received: str | None = Form(None),
    technical_evaluation_status: str | None = Form(None),
    financial_evaluation_status: str | None = Form(None),
    bid_analysis_status: str | None = Form(None),
    selected_supplier: str | None = Form(None),
    po_number: str | None = Form(None),
    po_date: str | None = Form(None),
    po_value: str | None = Form(None),
    receipt_status: str | None = Form(None),
    hse_documents_status: str | None = Form(None),
    technical_report_status: str | None = Form(None),
    execution_status: str | None = Form(None),
    receipt_note: str | None = Form(None),
    archive_status: str | None = Form(None),
    closure_date: str | None = Form(None),
    comments: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    if not can_update_tracker(user):
        raise HTTPException(403)
    case = case_or_404(db, case_id, user)
    next_status = required_text(status, "Estado", 80)
    next_approval_status = case.approval_status
    next_technical_status = required_text(technical_evaluation_status, "Estado da avaliação técnica", 60)
    next_financial_status = required_text(financial_evaluation_status, "Estado da avaliação financeira", 60)
    next_bid_status = required_text(bid_analysis_status, "Estado da bid analysis", 60)
    next_receipt_status = required_text(receipt_status, "Estado da recepcao", 60)
    next_hse_status = required_text(hse_documents_status, "Estado HSE", 60)
    next_technical_report_status = required_text(technical_report_status, "Relatório técnico", 60)
    next_execution_status = required_text(execution_status, "Execucao / entrega", 60)
    next_archive_status = required_text(archive_status, "Arquivo", 60)
    next_quotations = int(optional_int(quotations_received, "Cotacoes recebidas") or 0)
    next_po_value = optional_float(po_value, "Valor da PO")
    next_comments = (comments or "").strip() or None
    if next_financial_status == "Approved" and next_quotations < 3 and not next_comments:
        raise HTTPException(400, "Para aprovar a avaliação financeira com menos de 3 cotações, registe a justificativa nos comentários.")
    if next_status in {"PO Issued", "Mobilization / Delivery", "Receiving", "Closed"} and not (po_number or "").strip():
        raise HTTPException(400, "Informe o número da PO antes de avançar para PO/receção/fecho.")
    post_approval_statuses = {
        "RFQ/RFP/Tender Running",
        "Technical Evaluation",
        "Financial Evaluation",
        "Bid Analysis",
        "Supplier Selected",
        "PO Issued",
        "Mobilization / Delivery",
        "Receiving",
        "Ready for Archive",
        "Closed",
    }
    if next_status in post_approval_statuses and case.approval_status != "Approved":
        raise HTTPException(400, "Conclua a aprovação pelo perfil definido na matriz antes de avançar o processo.")
    if next_status == "Closed" and next_receipt_status not in {"Received", "Completed"}:
        raise HTTPException(400, "O processo só pode fechar depois da nota de recebimento.")
    if next_status == "Closed" and next_archive_status != "Archived":
        raise HTTPException(400, "O processo só pode fechar depois de arquivado.")
    if case.requisition.req_type == "REPOSICAO" and next_receipt_status in {"Received", "Completed"}:
        fully_received = all(
            float(item.quantity_received or 0) >= float(item.quantity_requested or 0)
            for item in case.requisition.items
        )
        if not fully_received:
            raise HTTPException(
                400,
                "Confirme as quantidades na secção de receção da reposição; o stock é atualizado por essa ação.",
            )
    approval_amount = next_po_value if next_po_value is not None else case.estimated_budget
    approval_rule = classify_procurement(db, approval_amount)
    if not approval_rule:
        raise HTTPException(400, "Não existe uma regra ativa na matriz para o valor atualizado do processo.")
    updated_approval_route = approval_label(approval_rule)
    approval_route_changed = bool(case.approval_route and case.approval_route != updated_approval_route)

    with atomic(db):
        case.status = next_status
        case.approval_status = next_approval_status
        case.rfq_rfp_tender_number = (rfq_rfp_tender_number or "").strip() or None
        case.suppliers_invited = int(optional_int(suppliers_invited, "Fornecedores convidados") or 0)
        case.quotations_received = next_quotations
        case.technical_evaluation_status = next_technical_status
        case.technical_report_status = next_technical_report_status
        case.financial_evaluation_status = next_financial_status
        case.bid_analysis_status = next_bid_status
        case.hse_documents_status = next_hse_status
        case.selected_supplier = (selected_supplier or "").strip() or None
        case.po_number = (po_number or "").strip() or None
        case.po_date = parse_date(po_date)
        case.po_value = next_po_value
        case.modality = approval_rule.modality
        case.approval_route = updated_approval_route
        if approval_route_changed and case.approval_status == "Approved":
            case.approval_status = "Pending"
            case.status = "Pending Approval"
        case.receipt_status = next_receipt_status
        case.execution_status = next_execution_status
        case.receipt_note = (receipt_note or "").strip() or None
        case.archive_status = next_archive_status
        case.closure_date = parse_date(closure_date)
        case.comments = next_comments
        audit_log(db, user, "Atualizou tracker de procurement", "Procurement", case.requisition.number, request=request)
    return RedirectResponse(f"/procurement/{case.id}", status_code=303)
