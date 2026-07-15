from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.core import ApprovalMatrixRule, User
from app.security import has_permission
from app.services.procurement import classify_procurement


def active_matrix_rules(db: Session) -> list[ApprovalMatrixRule]:
    return db.scalars(
        select(ApprovalMatrixRule)
        .where(ApprovalMatrixRule.is_active == True)
        .order_by(ApprovalMatrixRule.sort_order, ApprovalMatrixRule.min_value, ApprovalMatrixRule.id)
    ).all()


def _same_role(rule: ApprovalMatrixRule, role_id: int | None, role_name: str | None) -> bool:
    if role_id and rule.approver_role_id == role_id:
        return True
    expected = (role_name or "").strip().casefold()
    if not expected:
        return False
    labels = {
        (rule.final_approval or "").strip().casefold(),
        (rule.approver_role.name if rule.approver_role else "").strip().casefold(),
    }
    return expected in labels


def _exact_assignment(user: User, approver_role_id: int | None, approver_label: str | None) -> bool:
    if approver_role_id:
        return user.role_id == approver_role_id
    expected = (approver_label or "").strip().casefold()
    return bool(expected and user.role.name.strip().casefold() == expected)


def _rule_rank(rules: list[ApprovalMatrixRule], rule: ApprovalMatrixRule) -> int | None:
    for index, candidate in enumerate(rules):
        if candidate.id and rule.id and candidate.id == rule.id:
            return index
        if (
            candidate.min_value == rule.min_value
            and candidate.max_value == rule.max_value
            and candidate.sort_order == rule.sort_order
            and _same_role(candidate, rule.approver_role_id, rule.final_approval)
        ):
            return index
    return None


def role_matrix_rank(
    db: Session,
    *,
    role_id: int | None,
    role_name: str | None,
    highest: bool,
) -> int | None:
    ranks = [
        index
        for index, rule in enumerate(active_matrix_rules(db))
        if _same_role(rule, role_id, role_name)
    ]
    if not ranks:
        return None
    return max(ranks) if highest else min(ranks)


def can_user_approve_assignment(
    db: Session,
    user: User | None,
    permission: str,
    approver_role_id: int | None,
    approver_label: str | None,
    *,
    amount: float | None = None,
) -> bool:
    if not user or not has_permission(user, permission):
        return False
    if user.role.name == "SuperAdmin":
        return True
    has_explicit_assignment = bool(approver_role_id or (approver_label or "").strip())
    if has_explicit_assignment and _exact_assignment(user, approver_role_id, approver_label):
        return True

    rules = active_matrix_rules(db)
    required_rank: int | None = None
    if amount is not None:
        assigned_rule = classify_procurement(db, amount)
        if assigned_rule:
            required_rank = _rule_rank(rules, assigned_rule)
    if required_rank is None:
        if not has_explicit_assignment:
            return amount is None
        required_rank = role_matrix_rank(db, role_id=approver_role_id, role_name=approver_label, highest=False)
    user_rank = role_matrix_rank(db, role_id=user.role_id, role_name=user.role.name, highest=True)
    return user_rank is not None and required_rank is not None and user_rank >= required_rank


def users_for_approval_assignment(
    db: Session,
    permission: str,
    approver_role_id: int | None,
    approver_label: str | None,
    *,
    amount: float | None = None,
) -> list[User]:
    users = db.scalars(select(User).where(User.is_active == True)).all()
    return [
        user
        for user in users
        if can_user_approve_assignment(
            db,
            user,
            permission,
            approver_role_id,
            approver_label,
            amount=amount,
        )
    ]
