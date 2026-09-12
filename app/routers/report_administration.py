from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.core import DepartmentDailyReport, FinancialDailyImport
from app.models.reporting import OperationalReport, ManagerReportSource, ReportDeletion
from app.routers.common import templates
from app.security import current_user, has_permission
from app.services.audit import audit_log
from app.services.transactions import atomic
from app.routers.reporting_route import ReportingRoute

router=APIRouter(prefix='/operacoes-internas/relatorios/administracao',route_class=ReportingRoute)
MODELS={'daily':DepartmentDailyReport,'operational':OperationalReport,'manager':ManagerReportSource}


def require_delete(user):
    if not has_permission(user,'operational_reports_delete'): raise HTTPException(403,'Sem permissão para apagar relatórios.')


@router.get('/eliminados')
def deleted_reports(request:Request,db:Session=Depends(get_db),user=Depends(current_user)):
    require_delete(user)
    rows=db.scalars(select(ReportDeletion).order_by(ReportDeletion.deleted_at.desc()).limit(100)).all()
    return templates.TemplateResponse(request,'operational_reports/deleted.html',dict(request=request,user=user,rows=rows))


@router.post('/{kind}/{record_id}/apagar')
def delete_report(kind:str,record_id:int,request:Request,reason:str=Form(...),db:Session=Depends(get_db),user=Depends(current_user)):
    require_delete(user)
    if kind not in MODELS:raise HTTPException(404)
    row=db.get(MODELS[kind],record_id)
    if not row:raise HTTPException(404)
    reason=reason.strip()
    if not reason or len(reason)>1000:raise HTTPException(400,'Indique um motivo de até 1000 caracteres.')
    with atomic(db):
        if not db.scalar(select(ReportDeletion.id).where(ReportDeletion.kind==kind,ReportDeletion.record_id==record_id)):
            db.add(ReportDeletion(kind=kind,record_id=record_id,deleted_by_id=user.id,reason=reason))
            audit_log(db,user,'Apagou relatório (recuperável)','RelatoriosOperacionais',f'{kind}:{record_id}',new_value={'reason':reason},request=request)
    return RedirectResponse('/operacoes-internas/relatorios/administracao/eliminados',303)


@router.post('/{deletion_id}/restaurar')
def restore_report(deletion_id:int,request:Request,db:Session=Depends(get_db),user=Depends(current_user)):
    require_delete(user)
    row=db.get(ReportDeletion,deletion_id)
    if not row:raise HTTPException(404)
    with atomic(db):
        audit_log(db,user,'Restaurou relatório','RelatoriosOperacionais',f'{row.kind}:{row.record_id}',request=request)
        db.delete(row)
    return RedirectResponse('/operacoes-internas/relatorios/administracao/eliminados',303)
