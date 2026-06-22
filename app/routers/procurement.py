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
from app.services.notifications import (
    notify_procurement_budget_pending,
    notify_procurement_classification_pending,
    notify_procurement_permission,
    notify_procurement_requester,
)
from app.services.procurement import classify_procurement, days_open, next_non_stock_number
from app.services.procurement import approval_label
from app.services.procurement_pdf import procurement_form_to_pdf
from app.services.transactions import atomic

router = APIRouter(prefix="/procurement", tags=["procurement"])

PROCUREMENT_WORKFLOW_PERMISSIONS = {
    "procurement_manage",
    "budget_verify",
    "procurement_tor_approve_hod",
    "procurement_tor_approve_terminal",
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
        raise HTTPException(400, "Data requerida deve ser uma data valida.") from exc


def can_view_case(user: User, case: ProcurementCase) -> bool:
    return (
        any(has_permission(user, permission) for permission in PROCUREMENT_WORKFLOW_PERMISSIONS)
        or case.requisition.requesting_user_id == user.id
    )


def can_update_tracker(user: User) -> bool:
    return any(has_permission(user, permission) for permission in PROCUREMENT_WORKFLOW_PERMISSIONS)


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
        raise HTTPException(400, "Orcamento estimado nao pode ser negativo.")
    if priority not in {"Baixa", "Normal", "Alta", "Urgente"}:
        raise HTTPException(400, "Prioridade invalida.")
    if item_type not in {"Bem", "Serviço", "Obra"}:
        raise HTTPException(400, "Tipo invalido.")

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
        {"request": request, "user": user, "case": case, "officers": officers, "days_open": days_open, "error": None, "can_update_tracker": can_update_tracker(user)},
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
        raise HTTPException(400, "O TdR deve estar aprovado pelo HOD e Terminal Manager antes da verificacao de budget.")
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
    next_approval_status = required_text(approval_status, "Estado da aprovacao", 60)
    next_technical_status = required_text(technical_evaluation_status, "Estado da avaliacao tecnica", 60)
    next_financial_status = required_text(financial_evaluation_status, "Estado da avaliacao financeira", 60)
    next_bid_status = required_text(bid_analysis_status, "Estado da bid analysis", 60)
    next_receipt_status = required_text(receipt_status, "Estado da recepcao", 60)
    next_hse_status = required_text(hse_documents_status, "Estado HSE", 60)
    next_technical_report_status = required_text(technical_report_status, "Relatorio tecnico", 60)
    next_execution_status = required_text(execution_status, "Execucao / entrega", 60)
    next_archive_status = required_text(archive_status, "Arquivo", 60)
    next_quotations = int(optional_int(quotations_received, "Cotacoes recebidas") or 0)
    next_comments = (comments or "").strip() or None
    if next_financial_status == "Approved" and next_quotations < 3 and not next_comments:
        raise HTTPException(400, "Para aprovar a avaliação financeira com menos de 3 cotações, registe a justificativa nos comentários.")
    if next_status in {"PO Issued", "Mobilization / Delivery", "Receiving", "Closed"} and not (po_number or "").strip():
        raise HTTPException(400, "Informe o número da PO antes de avançar para PO/receção/fecho.")
    if next_status == "Closed" and next_receipt_status not in {"Received", "Completed"}:
        raise HTTPException(400, "O processo só pode fechar depois da nota de recebimento.")
    if next_status == "Closed" and next_archive_status != "Archived":
        raise HTTPException(400, "O processo só pode fechar depois de arquivado.")

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
        case.po_value = optional_float(po_value, "Valor da PO")
        case.receipt_status = next_receipt_status
        case.execution_status = next_execution_status
        case.receipt_note = (receipt_note or "").strip() or None
        case.archive_status = next_archive_status
        case.closure_date = parse_date(closure_date)
        case.comments = next_comments
        audit_log(db, user, "Atualizou tracker de procurement", "Procurement", case.requisition.number, request=request)
    return RedirectResponse(f"/procurement/{case.id}", status_code=303)
