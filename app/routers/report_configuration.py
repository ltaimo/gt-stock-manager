import json
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.reporting import ReportFormSchema
from app.services.report_form_schema import current_schema
from app.services.department_presentation import SECTIONS
from app.services.reporting_common import DEPARTMENTS
from app.security import current_user, has_permission
from app.routers.common import templates
from app.routers.reporting_route import ReportingRoute
from app.services.audit import audit_log
from app.services.transactions import atomic

router=APIRouter(prefix='/operacoes-internas/relatorios/formularios',route_class=ReportingRoute)


def check(user,department):
    if not has_permission(user,'operational_reports_settings'):raise HTTPException(403)
    if department not in SECTIONS:raise HTTPException(404)


def text(value,limit=160):
    value=str(value or '').strip()
    if len(value)>limit:raise HTTPException(400,'Campo demasiado longo.')
    return value


def choices(value):
    values=list(dict.fromkeys(v.strip() for v in str(value or '').splitlines() if v.strip()))
    if len(values)>100 or any(len(v)>160 for v in values):raise HTTPException(400,'Use até 100 opções de 160 caracteres.')
    return values


@router.get('/{department}')
def form_settings(department:str,request:Request,db:Session=Depends(get_db),user=Depends(current_user)):
    check(user,department)
    return templates.TemplateResponse(request,'operational_reports/form_settings.html',dict(request=request,user=user,department=department,departments=DEPARTMENTS,schema=current_schema(db,department),sections=SECTIONS[department]))


@router.post('/{department}')
async def save_settings(department:str,request:Request,db:Session=Depends(get_db),user=Depends(current_user)):
    check(user,department);form=await request.form()
    if form.get('schema_ready')!='1':raise HTTPException(400,'O editor não terminou de carregar. Reabra a página.')
    current=current_schema(db,department)
    if str(current['revision'])!=str(form.get('revision')):raise HTTPException(409,'A configuração mudou. Reabra antes de guardar.')
    tables=[];keys=set()
    for i in range(16):
        title=text(form.get(f'table_{i}_title'))
        if not title:continue
        key=text(form.get(f'table_{i}_key'),80) or 'custom_'+uuid4().hex[:12]
        if key in keys or key=='_schema':raise HTTPException(400,'Tabela duplicada.')
        keys.add(key)
        section=text(form.get(f'table_{i}_section'))
        if section not in {s[0] for s in SECTIONS[department]}:raise HTTPException(400,'Secção inválida.')
        columns=[];options=[]
        for j in range(12):
            label=text(form.get(f'col_{i}_{j}_label'))
            if label:
                columns.append(label);options.append(choices(form.get(f'col_{i}_{j}_choices')))
        if not columns or len(set(columns))!=len(columns):raise HTTPException(400,'Cada tabela precisa de colunas com nomes distintos.')
        tables.append(dict(key=key,section=section,title=title,columns=columns,choices=options))
    payload=dict(tables=tables,shift=choices(form.get('shift')),location=choices(form.get('location')))
    with atomic(db):
        row=db.scalar(select(ReportFormSchema).where(ReportFormSchema.department_key==department))
        if not row:row=ReportFormSchema(department_key=department);db.add(row)
        row.payload=json.dumps(payload,ensure_ascii=False)
        audit_log(db,user,'Configurou campos e opções dos relatórios','RelatoriosOperacionais',department,new_value=payload,request=request)
    return RedirectResponse(f'{router.prefix}/{department}',303)
