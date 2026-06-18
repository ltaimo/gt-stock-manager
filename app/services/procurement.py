from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.core import ApprovalMatrixRule, Requisition


DEFAULT_APPROVAL_MATRIX = [
    (0, Decimal("0.00"), Decimal("5000.00"), "RFQ", "Supervisor"),
    (1, Decimal("5001.00"), Decimal("10000.00"), "RFQ", "Chefe do terminal"),
    (2, Decimal("10001.00"), Decimal("30000.00"), "RFQ / RFP", "Diretor + Financeiro"),
    (3, Decimal("30001.00"), Decimal("1000000.00"), "RFQ / RFP", "Direcao Geral"),
    (4, Decimal("1000000.01"), None, "Tender formal", "Administracao / Conselho"),
]


def next_non_stock_number(db: Session) -> str:
    year = datetime.now(timezone.utc).year
    count = db.scalar(select(func.count(Requisition.id)).where(Requisition.number.like(f"NS-{year}-%"))) or 0
    return f"NS-{year}-{count + 1:05d}"


def classify_procurement(db: Session, amount: float | Decimal) -> ApprovalMatrixRule | None:
    value = Decimal(str(amount or 0))
    rules = db.scalars(
        select(ApprovalMatrixRule)
        .where(ApprovalMatrixRule.is_active == True)
        .order_by(ApprovalMatrixRule.sort_order, ApprovalMatrixRule.min_value)
    ).all()
    for rule in rules:
        min_value = Decimal(str(rule.min_value or 0))
        max_value = Decimal(str(rule.max_value)) if rule.max_value is not None else None
        if value >= min_value and (max_value is None or value <= max_value):
            return rule
    return None


def days_open(created_at, closure_date=None) -> int:
    end = closure_date or datetime.now(timezone.utc)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return max((end - created_at).days, 0)
