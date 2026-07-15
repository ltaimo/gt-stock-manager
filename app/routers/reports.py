from datetime import datetime, time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.i18n import language_for, localized_name, translate_text, translate_value
from app.models.core import Department, HseRecord, InternalOperationRecord, ProcurementCase, Product, Requisition, StockMovement, User
from app.routers.common import templates
from app.security import current_user, has_permission, require_permission
from app.services.exports import rows_to_csv, rows_to_pdf, rows_to_xlsx

router = APIRouter(prefix="/relatorios", tags=["relatorios"])


def can_view_reports_home(user: User) -> bool:
    return any(has_permission(user, permission) for permission in {"reports", "hse_reports", "internal_ops_reports"})


@router.get("")
def reports_home(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    if not can_view_reports_home(user):
        raise HTTPException(403)
    return templates.TemplateResponse(request, "reports/index.html", {"request": request, "user": user})


def stock_rows(db: Session, language: str = "pt"):
    products = db.scalars(select(Product).order_by(Product.name)).all()
    return [
        (
            p.code,
            localized_name(p, request=None) if language == "pt" else (p.name_en or p.name),
            (p.category.name_en or p.category.name) if language == "en" and p.category else p.category.name if p.category else translate_text("Sem Categoria", language),
            p.unit,
            p.unit_price,
            p.current_stock,
            p.minimum_stock,
            p.total_entries,
            p.total_exits,
            translate_value(p.status, language),
            translate_text("Sim" if p.requires_stock_control else "Não", language),
            translate_value(p.alert_status, language),
        )
        for p in products
    ]


def products_requiring_attention(db: Session) -> list[Product]:
    return [
        product
        for product in db.scalars(
            select(Product)
            .where(Product.status == "active", Product.requires_stock_control == True)
            .order_by(Product.name)
        ).all()
        if product.alert_status != "Stock Adequado"
    ]


@router.get("/stock")
def stock_report(request: Request, export: str = "", db: Session = Depends(get_db), user: User = Depends(require_permission("reports"))):
    language = language_for(user, request)
    headers = [translate_text(value, language) for value in ["Código", "Produto", "Categoria", "Unidade", "Preço Unit.", "Stock Atual", "Stock Mínimo", "Entradas", "Saídas", "Estado", "Monitorizado", "Alerta"]]
    rows = stock_rows(db, language)
    if export == "xlsx":
        return Response(rows_to_xlsx(headers, rows, translate_text("Stock", language), language), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": 'attachment; filename="stock.xlsx"'})
    if export == "pdf":
        return Response(rows_to_pdf(headers, rows, translate_text("Relatório de Stock", language), user.full_name, language), media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="stock.pdf"'})
    if export == "csv":
        return Response(rows_to_csv(headers, rows), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="stock.csv"'})
    return templates.TemplateResponse(request, "reports/stock.html", {"request": request, "user": user, "headers": headers, "rows": rows})


@router.get("/movimentos")
def movement_report(
    request: Request,
    action: str = "",
    product_id: int | None = None,
    department_id: int | None = None,
    user_id: int | None = None,
    date_from: str = "",
    date_to: str = "",
    export: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("reports")),
):
    language = language_for(user, request)
    stmt = select(StockMovement).order_by(StockMovement.posted_at.desc())
    if action:
        stmt = stmt.where(StockMovement.action_type == action)
    if product_id:
        stmt = stmt.where(StockMovement.product_id == product_id)
    if department_id:
        stmt = stmt.where(StockMovement.department_id == department_id)
    if user_id:
        stmt = stmt.where(StockMovement.registered_by_id == user_id)
    try:
        if date_from:
            stmt = stmt.where(StockMovement.posted_at >= datetime.combine(datetime.fromisoformat(date_from).date(), time.min))
        if date_to:
            stmt = stmt.where(StockMovement.posted_at <= datetime.combine(datetime.fromisoformat(date_to).date(), time.max))
    except ValueError as exc:
        raise HTTPException(400, "Informe datas válidas no formato AAAA-MM-DD.") from exc
    movements = db.scalars(stmt).all()
    headers = [translate_text(value, language) for value in ["Data", "Ação", "Código", "Item", "Destino", "Quantidade", "Tipo", "Responsável", "Departamento"]]
    rows = [(m.posted_at, translate_value(m.action_type, language), m.product.code, m.product.name_en or m.product.name if language == "en" else m.product.name, m.destination, m.quantity, m.reference_number, m.responsible_person, m.department.name if m.department else "") for m in movements]
    if export == "xlsx":
        return Response(rows_to_xlsx(headers, rows, translate_text("Movimentos", language), language), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": 'attachment; filename="movimentos.xlsx"'})
    if export == "pdf":
        return Response(rows_to_pdf(headers, rows, translate_text("Relatório de Movimentos", language), user.full_name, language), media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="movimentos.pdf"'})
    return templates.TemplateResponse(request, "reports/movements.html",
        {
            "request": request,
            "user": user,
            "headers": headers,
            "rows": rows,
            "action": action,
            "product_id": product_id,
            "department_id": department_id,
            "user_id": user_id,
            "date_from": date_from,
            "date_to": date_to,
            "products": db.scalars(select(Product).order_by(Product.name)).all(),
            "departments": db.scalars(select(Department).order_by(Department.name)).all(),
            "users": db.scalars(select(User).order_by(User.full_name)).all(),
        },
    )


@router.get("/requisicoes")
def requisition_report(request: Request, status: str = "", department_id: int | None = None, requester_id: int | None = None, export: str = "", db: Session = Depends(get_db), user: User = Depends(require_permission("reports"))):
    language = language_for(user, request)
    stmt = (
        select(Requisition)
        .where(Requisition.req_type.notin_(["NS", "REPOSICAO"]))
        .order_by(Requisition.request_date.desc())
    )
    if status:
        stmt = stmt.where(Requisition.status == status)
    if department_id:
        stmt = stmt.where(Requisition.department_id == department_id)
    if requester_id:
        stmt = stmt.where(Requisition.requesting_user_id == requester_id)
    reqs = db.scalars(stmt).all()
    headers = [translate_text(value, language) for value in ["Nº", "Data", "Estado", "Departamento", "Requisitante", "Valor", "Aprovador"]]
    rows = [(r.number, r.request_date, translate_value(r.status, language), r.department.name if r.department else "", r.requesting_user.full_name, r.estimated_value, r.authorization_person or "") for r in reqs]
    if export == "xlsx":
        return Response(rows_to_xlsx(headers, rows, translate_text("Requisições", language), language), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": 'attachment; filename="requisicoes.xlsx"'})
    if export == "pdf":
        return Response(rows_to_pdf(headers, rows, translate_text("Relatório de Requisições", language), user.full_name, language), media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="requisicoes.pdf"'})
    return templates.TemplateResponse(request, "reports/requisitions.html",
        {
            "request": request,
            "user": user,
            "requisitions": reqs,
            "status": status,
            "department_id": department_id,
            "requester_id": requester_id,
            "departments": db.scalars(select(Department).order_by(Department.name)).all(),
            "users": db.scalars(select(User).order_by(User.full_name)).all(),
        },
    )


@router.get("/procurement")
def procurement_report(request: Request, export: str = "", db: Session = Depends(get_db), user: User = Depends(require_permission("reports"))):
    language = language_for(user, request)
    cases = db.scalars(select(ProcurementCase).order_by(ProcurementCase.created_at.desc())).all()
    headers = [translate_text(value, language) for value in ["Nº", "Origem", "Requisitante", "Departamento", "Budget estimado", "Budget confirmado", "Modalidade", "Aprovação", "Estado", "Fornecedor", "PO", "Valor PO"]]
    rows = [
        (
            case.requisition.number,
            translate_text("Reposição de stock", language) if case.requisition.req_type == "REPOSICAO" else "Non-stock",
            case.requisition.requesting_user.full_name,
            case.requisition.department.name if case.requisition.department else "",
            case.estimated_budget,
            translate_text("Sim", language) if case.budget_confirmed else translate_text("Não", language) if case.budget_confirmed is False else translate_value("Pending", language),
            case.modality or "",
            case.approval_route or "",
            translate_value(case.status, language),
            case.selected_supplier or "",
            case.po_number or "",
            case.po_value or "",
        )
        for case in cases
    ]
    if export == "xlsx":
        return Response(rows_to_xlsx(headers, rows, "Procurement", language), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": 'attachment; filename="procurement.xlsx"'})
    if export == "pdf":
        return Response(rows_to_pdf(headers, rows, translate_text("Relatório de Procurement", language), user.full_name, language), media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="procurement.pdf"'})
    return templates.TemplateResponse(request, "reports/procurement.html", {"request": request, "user": user, "headers": headers, "rows": rows})


@router.get("/hse")
def hse_report(request: Request, export: str = "", db: Session = Depends(get_db), user: User = Depends(require_permission("hse_reports"))):
    language = language_for(user, request)
    records = db.scalars(select(HseRecord).order_by(HseRecord.created_at.desc())).all()
    headers = [translate_text(value, language) for value in ["Nº", "Área", "Título", "Estado", "Prioridade", "Responsável", "Departamento", "Prazo", "Progresso"]]
    rows = [
        (
            record.number,
            translate_text(record.module, language),
            record.title,
            translate_value(record.status, language),
            translate_value(record.priority, language),
            record.owner.full_name if record.owner else "",
            record.department.name if record.department else "",
            record.due_date.strftime("%Y-%m-%d") if record.due_date else "",
            f"{record.progress or 0}%",
        )
        for record in records
    ]
    if export == "xlsx":
        return Response(rows_to_xlsx(headers, rows, translate_text("Relatório HSE/HST", language), language), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": 'attachment; filename="hse.xlsx"'})
    if export == "pdf":
        return Response(rows_to_pdf(headers, rows, translate_text("Relatório HSE/HST", language), user.full_name, language), media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="hse.pdf"'})
    return templates.TemplateResponse(request, "reports/table.html", {"request": request, "user": user, "title": translate_text("Relatório HSE/HST", language), "headers": headers, "rows": rows})


@router.get("/operacoes-internas")
def internal_ops_report(request: Request, export: str = "", db: Session = Depends(get_db), user: User = Depends(require_permission("internal_ops_reports"))):
    language = language_for(user, request)
    records = db.scalars(select(InternalOperationRecord).order_by(InternalOperationRecord.record_date.desc())).all()
    headers = [translate_text(value, language) for value in ["Nº", "Data", "Tipo", "Descrição", "Fornecedor", "Quantidade", "Valor", "Departamento", "Estado"]]
    rows = [
        (
            record.number,
            record.record_date.strftime("%Y-%m-%d"),
            translate_text(record.kind, language),
            record.description,
            record.supplier or "",
            f"{record.quantity} {record.unit}",
            record.amount,
            record.department.name if record.department else "",
            translate_value(record.status, language),
        )
        for record in records
    ]
    if export == "xlsx":
        return Response(rows_to_xlsx(headers, rows, translate_text("Relatório de Operações Internas", language), language), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": 'attachment; filename="operacoes-internas.xlsx"'})
    if export == "pdf":
        return Response(rows_to_pdf(headers, rows, translate_text("Relatório de Operações Internas", language), user.full_name, language), media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="operacoes-internas.pdf"'})
    return templates.TemplateResponse(request, "reports/table.html", {"request": request, "user": user, "title": translate_text("Relatório de Operações Internas", language), "headers": headers, "rows": rows})


@router.get("/critico")
def critical_report(
    request: Request,
    export: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("reports")),
):
    language = language_for(user, request)
    products = products_requiring_attention(db)
    headers = [translate_text(value, language) for value in ["Código", "Produto", "Categoria", "Unidade", "Stock Atual", "Stock Mínimo", "Estado"]]
    rows = [
        (
            product.code,
            product.name_en or product.name if language == "en" else product.name,
            (product.category.name_en or product.category.name) if language == "en" and product.category else product.category.name if product.category else translate_text("Sem Categoria", language),
            product.unit,
            product.current_stock,
            product.minimum_stock,
            translate_value(product.alert_status, language),
        )
        for product in products
    ]
    if export == "xlsx":
        return Response(
            rows_to_xlsx(headers, rows, translate_text("Stock crítico", language), language),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": 'attachment; filename="stock-critico.xlsx"'},
        )
    if export == "pdf":
        return Response(
            rows_to_pdf(headers, rows, translate_text("Stock que Requer Atenção", language), user.full_name, language),
            media_type="application/pdf",
            headers={"Content-Disposition": 'attachment; filename="stock-critico.pdf"'},
        )
    return templates.TemplateResponse(request, "reports/critical.html", {"request": request, "user": user, "products": products})
