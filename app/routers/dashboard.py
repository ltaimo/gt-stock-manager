import calendar
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request
from sqlalchemy import extract, func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.core import ProcurementCase, Product, Requisition, RequisitionStatus, StockMovement, User
from app.routers.common import templates
from app.security import current_user, has_permission

router = APIRouter()


@router.get("/dashboard")
def dashboard(request: Request, db: Session = Depends(get_db), user: User = Depends(current_user)):
    now = datetime.now(timezone.utc)
    days_in_month = calendar.monthrange(now.year, now.month)[1]
    elapsed_days = max(now.day, 1)

    products = db.scalars(select(Product).order_by(Product.name)).all()
    can_view_movements = has_permission(user, "movements")
    can_review_requisitions = has_permission(user, "requisitions_review")
    can_view_procurement = has_permission(user, "procurement_manage") or has_permission(user, "budget_verify")
    movements = (
        db.scalars(select(StockMovement).order_by(StockMovement.posted_at.desc()).limit(8)).all()
        if can_view_movements
        else []
    )
    pending_stmt = select(Requisition).where(Requisition.status == RequisitionStatus.submitted.value)
    if not can_review_requisitions:
        pending_stmt = pending_stmt.where(Requisition.requesting_user_id == user.id)
    pending = db.scalars(pending_stmt.limit(8)).all()
    procurement_pending = db.scalars(select(ProcurementCase).where(ProcurementCase.status != "Closed").order_by(ProcurementCase.created_at.desc()).limit(8)).all() if can_view_procurement else []

    active_products = [p for p in products if p.status == "active"]
    attention_statuses = {"Sem Stock", "Stock Crítico", "Stock em Atenção", "Erro: Stock Negativo"}
    critical_products = [p for p in products if p.alert_status in attention_statuses]
    stockout_products = [p for p in products if p.alert_status == "Sem Stock"]
    warning_products = [p for p in products if p.alert_status == "Stock em Atenção"]
    negative_products = [p for p in products if p.alert_status == "Erro: Stock Negativo"]

    entries_month = db.scalar(
        select(func.coalesce(func.sum(StockMovement.quantity), 0)).where(
            StockMovement.action_type.in_(["ENTRADA", "DEVOLUÇÃO"]),
            extract("month", StockMovement.posted_at) == now.month,
            extract("year", StockMovement.posted_at) == now.year,
        )
    ) or 0
    exits_month = db.scalar(
        select(func.coalesce(func.sum(StockMovement.quantity), 0)).where(
            StockMovement.action_type == "SAÍDA",
            extract("month", StockMovement.posted_at) == now.month,
            extract("year", StockMovement.posted_at) == now.year,
        )
    ) or 0

    daily_entries = {day: 0 for day in range(1, days_in_month + 1)}
    daily_exits = {day: 0 for day in range(1, days_in_month + 1)}
    current_month_movements = db.scalars(
        select(StockMovement).where(
            extract("month", StockMovement.posted_at) == now.month,
            extract("year", StockMovement.posted_at) == now.year,
        )
    ).all()
    for movement in current_month_movements:
        day = movement.posted_at.day
        if movement.action_type in {"ENTRADA", "DEVOLUÇÃO"}:
            daily_entries[day] += float(movement.quantity or 0)
        elif movement.action_type == "SAÍDA":
            daily_exits[day] += float(movement.quantity or 0)

    month_chart = {
        "labels": [str(day) for day in range(1, days_in_month + 1)],
        "entries": [daily_entries[day] for day in range(1, days_in_month + 1)],
        "exits": [daily_exits[day] for day in range(1, days_in_month + 1)],
    }

    most_requested = db.execute(
        select(Product.name, func.coalesce(func.sum(StockMovement.quantity), 0).label("total"))
        .join(StockMovement, StockMovement.product_id == Product.id)
        .where(StockMovement.action_type == "SAÍDA")
        .group_by(Product.id)
        .order_by(func.coalesce(func.sum(StockMovement.quantity), 0).desc())
        .limit(8)
    ).all()

    movement_type_rows = db.execute(
        select(StockMovement.action_type, func.coalesce(func.sum(StockMovement.quantity), 0))
        .group_by(StockMovement.action_type)
        .order_by(StockMovement.action_type)
    ).all()
    movement_type_chart = {
        "labels": [row[0] for row in movement_type_rows],
        "values": [float(row[1] or 0) for row in movement_type_rows],
    }

    unit_rows = db.execute(
        select(Product.unit, func.count(Product.id)).group_by(Product.unit).order_by(func.count(Product.id).desc())
    ).all()
    unit_chart = {
        "labels": [row[0] or "un" for row in unit_rows],
        "values": [int(row[1] or 0) for row in unit_rows],
    }

    projected_entries = round(float(entries_month) / elapsed_days * days_in_month, 2)
    projected_exits = round(float(exits_month) / elapsed_days * days_in_month, 2)
    stock_health = round(((len(products) - len(critical_products)) / len(products) * 100), 1) if products else 0

    return templates.TemplateResponse(
        "dashboard/index.html",
        {
            "request": request,
            "user": user,
            "total_products": len(products),
            "active_products": len(active_products),
            "critical": len(critical_products),
            "stockout": len(stockout_products),
            "warning": len(warning_products),
            "negative": len(negative_products),
            "pending_count": len(pending),
            "procurement_pending_count": len(procurement_pending),
            "entries_month": entries_month,
            "exits_month": exits_month,
            "projected_entries": projected_entries,
            "projected_exits": projected_exits,
            "stock_health": stock_health,
            "recent_movements": movements,
            "pending_requisitions": pending,
            "pending_procurement": procurement_pending,
            "most_requested": most_requested,
            "critical_products": critical_products[:10],
            "month_chart": month_chart,
            "movement_type_chart": movement_type_chart,
            "unit_chart": unit_chart,
            "can_view_movements": can_view_movements,
            "can_view_procurement": can_view_procurement,
        },
    )
