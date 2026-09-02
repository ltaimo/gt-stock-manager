from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.core import ApprovalMatrixRule, Requisition


TERMINAL_DIRECTOR_APPROVAL = "Director do Terminal"
LOWER_THAN_TERMINAL_APPROVALS = {
    "gestor de estoque",
    "gestor de stock",
    "supervisor",
    "chefe do terminal",
    "chefe do terminal / terminal manager",
    "terminal manager",
}

DEFAULT_APPROVAL_MATRIX = [
    (0, Decimal("0.00"), Decimal("5000.00"), "RFQ", "Chefe do Terminal"),
    (1, Decimal("5000.01"), Decimal("10000.00"), "RFQ", "Chefe do Terminal"),
    (2, Decimal("10000.01"), Decimal("30000.00"), "RFQ / RFP", "Director Financeiro"),
    (3, Decimal("30000.01"), Decimal("1000000.00"), "RFQ / RFP", "Administrador Delegado"),
    (4, Decimal("1000000.01"), None, "Tender formal", "PCA"),
]


def next_non_stock_number(db: Session) -> str:
    year = datetime.now(timezone.utc).year
    count = db.scalar(select(func.count(Requisition.id)).where(Requisition.number.like(f"NS-{year}-%"))) or 0
    return f"NS-{year}-{count + 1:05d}"


def next_replenishment_number(db: Session) -> str:
    year = datetime.now(timezone.utc).year
    count = db.scalar(select(func.count(Requisition.id)).where(Requisition.number.like(f"RP-{year}-%"))) or 0
    return f"RP-{year}-{count + 1:05d}"


def suggested_replenishment_quantity(product) -> float:
    if product.status != "active" or not product.requires_stock_control:
        return 0
    current = Decimal(str(product.current_stock or 0))
    minimum = Decimal(str(product.minimum_stock or 0))
    if minimum <= 0 or current > minimum:
        return 0
    return float(max((minimum * 2) - current, Decimal("1")))


def classify_procurement(db: Session, amount: float | Decimal) -> ApprovalMatrixRule | None:
    value = Decimal(str(amount or 0))
    rules = active_approval_rules(db)
    return classify_procurement_from_rules(rules, value)


def active_approval_rules(db: Session) -> list[ApprovalMatrixRule]:
    return db.scalars(
        select(ApprovalMatrixRule)
        .where(ApprovalMatrixRule.is_active == True)
        .order_by(ApprovalMatrixRule.sort_order, ApprovalMatrixRule.min_value, ApprovalMatrixRule.id)
    ).all()


def classify_procurement_from_rules(rules: list[ApprovalMatrixRule], amount: float | Decimal) -> ApprovalMatrixRule | None:
    value = Decimal(str(amount or 0))
    matches = []
    for rule in rules:
        min_value = Decimal(str(rule.min_value or 0))
        max_value = Decimal(str(rule.max_value)) if rule.max_value is not None else None
        if value >= min_value and (max_value is None or value <= max_value):
            matches.append(rule)
    if matches:
        # In an accidental overlap, use the higher threshold to avoid under-approval.
        return matches[-1]
    for rule in rules:
        if value < Decimal(str(rule.min_value or 0)):
            # Fill accidental gaps conservatively with the next approval level.
            return rule
    return None


def approval_role_name(rule: ApprovalMatrixRule | None) -> str:
    if not rule:
        return ""
    return (rule.approver_role.name if rule.approver_role else rule.final_approval or "").strip()


def _is_terminal_director_rule(rule: ApprovalMatrixRule) -> bool:
    return approval_role_name(rule).casefold() == TERMINAL_DIRECTOR_APPROVAL.casefold()


def _is_below_terminal_director(rule: ApprovalMatrixRule | None) -> bool:
    return approval_role_name(rule).casefold() in LOWER_THAN_TERMINAL_APPROVALS


def classify_non_stock_approval(db: Session, amount: float | Decimal) -> ApprovalMatrixRule | None:
    rules = active_approval_rules(db)
    rule = classify_procurement_from_rules(rules, amount)
    terminal_rule = next((candidate for candidate in rules if _is_terminal_director_rule(candidate)), None)
    if terminal_rule and rule:
        rule_index = rules.index(rule)
        terminal_index = rules.index(terminal_rule)
        if rule_index < terminal_index:
            return terminal_rule
    if terminal_rule and not rule:
        return terminal_rule
    return terminal_rule if terminal_rule and _is_below_terminal_director(rule) else rule


def non_stock_approval_label(rule: ApprovalMatrixRule | None) -> str:
    if _is_below_terminal_director(rule):
        return TERMINAL_DIRECTOR_APPROVAL
    return approval_label(rule)


def approval_label(rule: ApprovalMatrixRule | None) -> str:
    if not rule:
        return ""
    return approval_role_name(rule)


def days_open(created_at, closure_date=None) -> int:
    end = closure_date or datetime.now(timezone.utc)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    return max((end - created_at).days, 0)
