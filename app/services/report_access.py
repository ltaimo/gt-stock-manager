from fastapi import HTTPException
from sqlalchemy import select
from app.models.reporting import ReportDeletion


def view_all(user):
    from app.routers.internal_ops import can_view_all_department_reports
    return can_view_all_department_reports(user)


def active(model, kind):
    clause = ~model.id.in_(select(ReportDeletion.record_id).where(ReportDeletion.kind == kind))
    if kind == 'operational':
        clause = clause & (model.source_daily_id.is_(None) | ~model.source_daily_id.in_(select(ReportDeletion.record_id).where(ReportDeletion.kind == 'daily')))
    return clause


def visible(stmt, model, kind, user):
    stmt = stmt.where(active(model, kind))
    if not view_all(user): stmt = stmt.where(model.created_by_id == user.id)
    return stmt


def require_record(db, user, row, kind):
    if not row or db.scalar(select(ReportDeletion.id).where(ReportDeletion.kind == kind, ReportDeletion.record_id == row.id)):
        raise HTTPException(404, 'Relatório não encontrado.')
    if kind == 'operational' and row.source_daily_id and db.scalar(select(ReportDeletion.id).where(ReportDeletion.kind == 'daily', ReportDeletion.record_id == row.source_daily_id)):
        raise HTTPException(404, 'Relatório não encontrado.')
    if not view_all(user) and row.created_by_id != user.id:
        raise HTTPException(403, 'Só pode consultar os seus próprios relatórios.')
