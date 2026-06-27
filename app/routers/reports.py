from datetime import datetime, time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.core import Department, ProcurementCase, Product, Requisition, StockMovement, User
from app.routers.common import templates
from app.security import require_permission
from app.services.exports import rows_to_csv, rows_to_pdf, rows_to_xlsx

router = APIRouter(prefix="/relatorios", tags=["relatorios"])


@router.get("")
def reports_home(request: Request, db: Session = Depends(get_db), user: User = Depends(require_permission("reports"))):
    return templates.TemplateResponse("reports/index.html", {"request": request, "user": user})


def stock_rows(db: Session):
    products = db.scalars(select(Product).order_by(Product.name)).all()
    return [
        (
            p.code,
            p.name,
            p.category.name if p.category else "Sem Categoria",
            p.unit,
            p.unit_price,
            p.current_stock,
            p.minimum_stock,
            p.total_entries,
            p.total_exits,
            "Ativo" if p.status == "active" else "Inativo",
            "Sim" if p.requires_stock_control else "Não",
            p.alert_status,
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
    headers = ["Código", "Produto", "Categoria", "Unidade", "Preço Unit.", "Stock Atual", "Stock Mínimo", "Entradas", "Saídas", "Estado", "Monitorizado", "Alerta"]
    rows = stock_rows(db)
    if export == "xlsx":
        return Response(rows_to_xlsx(headers, rows, "Stock"), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": 'attachment; filename="stock.xlsx"'})
    if export == "pdf":
        return Response(rows_to_pdf(headers, rows, "Relatório de Stock", user.full_name), media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="stock.pdf"'})
    if export == "csv":
        return Response(rows_to_csv(headers, rows), media_type="text/csv", headers={"Content-Disposition": 'attachment; filename="stock.csv"'})
    return templates.TemplateResponse("reports/stock.html", {"request": request, "user": user, "headers": headers, "rows": rows})


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
    headers = ["Data", "Ação", "Código", "Item", "Destino", "Quantidade", "Tipo", "Responsável", "Departamento"]
    rows = [(m.posted_at, m.action_type, m.product.code, m.product.name, m.destination, m.quantity, m.reference_number, m.responsible_person, m.department.name if m.department else "") for m in movements]
    if export == "xlsx":
        return Response(rows_to_xlsx(headers, rows, "Movimentos"), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": 'attachment; filename="movimentos.xlsx"'})
    if export == "pdf":
        return Response(rows_to_pdf(headers, rows, "Relatório de Movimentos", user.full_name), media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="movimentos.pdf"'})
    return templates.TemplateResponse(
        "reports/movements.html",
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
    headers = ["Nº", "Data", "Estado", "Departamento", "Requisitante", "Valor", "Aprovador"]
    rows = [(r.number, r.request_date, r.status, r.department.name if r.department else "", r.requesting_user.full_name, r.estimated_value, r.authorization_person or "") for r in reqs]
    if export == "xlsx":
        return Response(rows_to_xlsx(headers, rows, "Requisições"), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": 'attachment; filename="requisicoes.xlsx"'})
    if export == "pdf":
        return Response(rows_to_pdf(headers, rows, "Relatório de Requisições", user.full_name), media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="requisicoes.pdf"'})
    return templates.TemplateResponse(
        "reports/requisitions.html",
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
    cases = db.scalars(select(ProcurementCase).order_by(ProcurementCase.created_at.desc())).all()
    headers = ["Nº", "Origem", "Requisitante", "Departamento", "Budget estimado", "Budget confirmado", "Modalidade", "Aprovação", "Estado", "Fornecedor", "PO", "Valor PO"]
    rows = [
        (
            case.requisition.number,
            "Reposição de stock" if case.requisition.req_type == "REPOSICAO" else "Non-stock",
            case.requisition.requesting_user.full_name,
            case.requisition.department.name if case.requisition.department else "",
            case.estimated_budget,
            "Sim" if case.budget_confirmed else "Não" if case.budget_confirmed is False else "Pendente",
            case.modality or "",
            case.approval_route or "",
            case.status,
            case.selected_supplier or "",
            case.po_number or "",
            case.po_value or "",
        )
        for case in cases
    ]
    if export == "xlsx":
        return Response(rows_to_xlsx(headers, rows, "Procurement"), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": 'attachment; filename="procurement.xlsx"'})
    if export == "pdf":
        return Response(rows_to_pdf(headers, rows, "Relatório de Procurement", user.full_name), media_type="application/pdf", headers={"Content-Disposition": 'attachment; filename="procurement.pdf"'})
    return templates.TemplateResponse("reports/procurement.html", {"request": request, "user": user, "headers": headers, "rows": rows})


@router.get("/critico")
def critical_report(
    request: Request,
    export: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("reports")),
):
    products = products_requiring_attention(db)
    headers = ["Código", "Produto", "Categoria", "Unidade", "Stock Atual", "Stock Mínimo", "Estado"]
    rows = [
        (
            product.code,
            product.name,
            product.category.name if product.category else "Sem Categoria",
            product.unit,
            product.current_stock,
            product.minimum_stock,
            product.alert_status,
        )
        for product in products
    ]
    if export == "xlsx":
        return Response(
            rows_to_xlsx(headers, rows, "Stock crítico"),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": 'attachment; filename="stock-critico.xlsx"'},
        )
    if export == "pdf":
        return Response(
            rows_to_pdf(headers, rows, "Stock que Requer Atenção", user.full_name),
            media_type="application/pdf",
            headers={"Content-Disposition": 'attachment; filename="stock-critico.pdf"'},
        )
    return templates.TemplateResponse("reports/critical.html", {"request": request, "user": user, "products": products})
