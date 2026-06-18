from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.core import ProcurementCase, Requisition, RequisitionStatus, User
from app.routers.common import templates
from app.security import current_user, has_permission, require_permission
from app.services.audit import audit_log
from app.services.forms import optional_float, optional_int, required_float, required_text
from app.services.notifications import notify_procurement_budget_pending, notify_procurement_classification_pending
from app.services.procurement import classify_procurement, days_open, next_non_stock_number
from app.services.procurement import approval_label
from app.services.procurement_pdf import procurement_form_to_pdf
from app.services.transactions import atomic

router = APIRouter(prefix="/procurement", tags=["procurement"])


def parse_date(value: str | None) -> datetime | None:
    cleaned = str(value or "").strip()
    if not cleaned:
        return None
    try:
        return datetime.fromisoformat(cleaned).replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise HTTPException(400, "Data requerida deve ser uma data valida.") from exc


def can_view_case(user: User, case: ProcurementCase) -> bool:
    return (
        has_permission(user, "procurement_manage")
        or has_permission(user, "budget_verify")
        or case.requisition.requesting_user_id == user.id
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
    if not (has_permission(user, "procurement_manage") or has_permission(user, "budget_verify")):
        stmt = stmt.where(Requisition.requesting_user_id == user.id)
    cases = db.scalars(stmt).all()
    return templates.TemplateResponse(
        "procurement/index.html",
        {"request": request, "user": user, "cases": cases, "days_open": days_open},
    )


@router.get("/nova")
def new_non_stock(request: Request, user: User = Depends(require_permission("non_stock_requisitions_create"))):
    return templates.TemplateResponse("procurement/form.html", {"request": request, "user": user, "error": None})


@router.post("/nova")
def create_non_stock(
    request: Request,
    description: str | None = Form(None),
    justification: str | None = Form(None),
    cost_center: str | None = Form(None),
    priority: str = Form("Normal"),
    estimated_budget: str | None = Form(None),
    required_date: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("non_stock_requisitions_create")),
):
    clean_description = required_text(description, "Descricao / escopo", 2000)
    budget = required_float(estimated_budget, "Orcamento estimado")
    if budget < 0:
        raise HTTPException(400, "Orcamento estimado nao pode ser negativo.")
    if priority not in {"Baixa", "Normal", "Alta", "Urgente"}:
        raise HTTPException(400, "Prioridade invalida.")

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
        case = ProcurementCase(
            requisition_id=req.id,
            description=clean_description,
            justification=(justification or "").strip() or None,
            cost_center=(cost_center or "").strip() or None,
            priority=priority,
            estimated_budget=budget,
            required_date=parse_date(required_date),
            status="Pending Budget Verification",
        )
        db.add(case)
        db.flush()
        notify_procurement_budget_pending(db, req)
        audit_log(db, user, "Criou requisicao non-stock", "Procurement", req.number, request=request)
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
    return templates.TemplateResponse(
        "procurement/detail.html",
        {"request": request, "user": user, "case": case, "officers": officers, "days_open": days_open, "error": None},
    )


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
    if decision not in {"confirm", "return"}:
        raise HTTPException(400, "Escolha uma decisao valida.")
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
        audit_log(db, user, "Verificou orcamento", "Procurement", case.requisition.number, new_value={"status": case.status}, request=request)
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
        raise HTTPException(400, "Nao existe regra ativa na matriz para este valor.")
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


@router.get("/{case_id}/formulario")
def procurement_form_pdf(case_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    case = case_or_404(db, case_id, user)
    disposition = "attachment" if request.query_params.get("download") == "1" else "inline"
    return Response(
        procurement_form_to_pdf(case, user),
        media_type="application/pdf",
        headers={"Content-Disposition": f'{disposition}; filename="{case.requisition.number}-NS.pdf"'},
    )


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
    closure_date: str | None = Form(None),
    comments: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement_manage")),
):
    case = case_or_404(db, case_id, user)
    with atomic(db):
        case.status = required_text(status, "Estado", 80)
        case.approval_status = required_text(approval_status, "Estado da aprovacao", 60)
        case.rfq_rfp_tender_number = (rfq_rfp_tender_number or "").strip() or None
        case.suppliers_invited = int(optional_int(suppliers_invited, "Fornecedores convidados") or 0)
        case.quotations_received = int(optional_int(quotations_received, "Cotacoes recebidas") or 0)
        case.technical_evaluation_status = required_text(technical_evaluation_status, "Estado da avaliacao tecnica", 60)
        case.financial_evaluation_status = required_text(financial_evaluation_status, "Estado da avaliacao financeira", 60)
        case.bid_analysis_status = required_text(bid_analysis_status, "Estado da bid analysis", 60)
        case.selected_supplier = (selected_supplier or "").strip() or None
        case.po_number = (po_number or "").strip() or None
        case.po_date = parse_date(po_date)
        case.po_value = optional_float(po_value, "Valor da PO")
        case.receipt_status = required_text(receipt_status, "Estado da recepcao", 60)
        case.closure_date = parse_date(closure_date)
        case.comments = (comments or "").strip() or None
        audit_log(db, user, "Atualizou tracker de procurement", "Procurement", case.requisition.number, request=request)
    return RedirectResponse(f"/procurement/{case.id}", status_code=303)
