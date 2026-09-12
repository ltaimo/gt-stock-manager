import hashlib
import io
import json
import re
import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import PurePath
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse, Response
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.exc import StaleDataError
from app.database import get_db
from app.models.core import DepartmentDailyReport, FinancialDailyImport, User
from app.models.reporting import OperationalReport, ManagerReportSource, DailyReportEntry, OperationalReportSettings, OperationalPending
from app.routers.common import templates
from app.security import current_user, has_permission
from app.services.reporting_common import *
from app.services.operational_reporting import create_report, build_snapshot, report_presentation, submit_report, SUPPLEMENTS, source_details, SOURCE_TYPES
from app.services.department_presentation import reports_pdf, reports_docx
from app.services.transactions import atomic
from app.services.audit import audit_log
from app.routers.reporting_route import ReportingRoute
from app.services.report_access import visible, require_record, active, view_all
from app.services.report_text_extraction import suggested_metrics

router=APIRouter(prefix='/operacoes-internas/relatorios',tags=['relatórios operacionais'],route_class=ReportingRoute)

def read_report(db,user,report_id,edit=False):
    row=db.get(OperationalReport,report_id)
    require_record(db,user,row,'operational')
    if not row:raise HTTPException(404,'Relatório não encontrado.')
    require_access(user,row.department_key,write=edit)
    if edit:
        if row.status=='Submitted':raise HTTPException(409,'Esta versão oficial está fechada. Crie uma nova versão.')
        if row.created_by_id!=user.id and not has_permission(user,'operational_reports_settings'):raise HTTPException(403,'Apenas o autor pode editar este rascunho.')
    elif row.status!='Submitted' and row.created_by_id!=user.id and not view_all(user):
        raise HTTPException(403,'Este rascunho pertence a outro utilizador.')
    return row

def check_revision(row,value):
    if str(row.revision)!=str(value):raise HTTPException(409,'O registo foi alterado noutra sessão. Reabra a versão atual antes de guardar.')

def save_or_conflict(db):
    try:db.commit()
    except (IntegrityError,StaleDataError) as exc:
        db.rollback();raise HTTPException(409,'Já existe um registo ou uma versão mais recente. Atualize a página.') from exc

@router.get('')
def history(request:Request,department:str='',period:str='',status:str='',date_from:str='',date_to:str='',responsible:str='',page:int=1,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allowed=[key for key in DEPARTMENTS if can_view(user,key)]
    stmt=visible(select(OperationalReport).where(OperationalReport.department_key.in_(allowed)),OperationalReport,'operational',user)
    if not has_permission(user,'operational_reports_settings'):
        stmt=stmt.where((OperationalReport.status=='Submitted')|(OperationalReport.created_by_id==user.id))
    if department:
        require_access(user,department);stmt=stmt.where(OperationalReport.department_key==department)
    if period:stmt=stmt.where(OperationalReport.period==period)
    if status:stmt=stmt.where(OperationalReport.status==status)
    if date_from:stmt=stmt.where(OperationalReport.date_to>=parsed_date(date_from))
    if date_to:stmt=stmt.where(OperationalReport.date_from<=parsed_date(date_to))
    if responsible:
        try:stmt=stmt.where(OperationalReport.created_by_id==int(responsible))
        except ValueError:raise HTTPException(400,'Responsável inválido.')
    page=max(1,page);total=db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows=db.scalars(stmt.order_by(OperationalReport.created_at.desc(),OperationalReport.id.desc()).offset((page-1)*25).limit(25)).all()
    today=date.today()
    submitted=db.scalars(visible(select(DepartmentDailyReport),DepartmentDailyReport,'daily',user).where(DepartmentDailyReport.report_date>=utc_day(today),DepartmentDailyReport.report_date<utc_day(today+timedelta(days=1)),DepartmentDailyReport.status.in_(['Submitted','Validated']),DepartmentDailyReport.department_key.in_(allowed))).all()
    manager_ready=bool(db.scalar(select(ManagerReportSource.id).join(FinancialDailyImport,ManagerReportSource.import_id==FinancialDailyImport.id).where(FinancialDailyImport.report_date>=utc_day(today),FinancialDailyImport.report_date<utc_day(today+timedelta(days=1)),ManagerReportSource.status=='Reviewed'))) if can_manage(user) else False
    pending=db.scalars(select(OperationalPending).where(OperationalPending.department_key.in_(allowed if 'consolidated' not in allowed else list(DEPARTMENTS)),OperationalPending.status!='Closed')).all()
    return templates.TemplateResponse(request,'operational_reports/history.html',dict(request=request,user=user,rows=rows,total=total,page=page,allowed=allowed,departments=DEPARTMENTS,periods=PERIODS,states=STATES,department=department,period=period,status=status,date_from=date_from,date_to=date_to,responsible=responsible,today=str(today),ready={k:any(r.department_key==k for r in submitted) for k in allowed},manager_ready=manager_ready,generate_keys=[k for k in ['consolidated','security','maintenance','it'] if can_generate(user,k)],manager=can_manage(user),pending_count=len(pending),critical_count=sum(p.priority=='Crítica' for p in pending),settings=policy(db),users=db.scalars(select(User).where(User.is_active==True).order_by(User.full_name)).all() if allowed else []))

@router.post('/gerar')
def generate(request:Request,department:str=Form(...),period:str=Form(...),anchor:str=Form(...),db:Session=Depends(get_db),user:User=Depends(current_user)):
    require_access(user,department,True)
    if period=='inspection' and department!='it':raise HTTPException(400,'A inspeção CCTV pertence ao IT.')
    if period=='daily' and department!='consolidated':raise HTTPException(400,'Preencha o relatório diário no formulário departamental.')
    start,end=period_window(period,anchor,policy(db).week_start)
    row=create_report(db,user,department,period,start,end)
    audit_log(db,user,'Gerou relatório operacional','RelatoriosOperacionais',str(row.id),new_value={'number':row.number},request=request)
    save_or_conflict(db)
    return RedirectResponse(f'{router.prefix}/{row.id}',303)

@router.get('/configuracoes')
def get_settings_page(request:Request,db:Session=Depends(get_db),user:User=Depends(current_user)):
    if not has_permission(user,'operational_reports_settings'):raise HTTPException(403)
    return templates.TemplateResponse(request,'operational_reports/settings.html',dict(request=request,user=user,settings=policy(db)))

@router.post('/configuracoes')
def update_settings(request:Request,week_start:int=Form(...),allow_partial:str=Form(''),db:Session=Depends(get_db),user:User=Depends(current_user)):
    if not has_permission(user,'operational_reports_settings'):raise HTTPException(403)
    if week_start not in range(7):raise HTTPException(400,'Dia da semana inválido.')
    with atomic(db):
        row=policy(db);row.week_start=week_start;row.allow_partial=allow_partial=='on';db.add(row)
        audit_log(db,user,'Alterou regras dos relatórios','RelatoriosOperacionais','configuracoes',new_value={'week_start':week_start,'allow_partial':row.allow_partial},request=request)
    return RedirectResponse(router.prefix,303)

@router.get('/gestor')
def manager_sources(request:Request,page:int=1,db:Session=Depends(get_db),user:User=Depends(current_user)):
    if not can_manage(user):raise HTTPException(403)
    rows=db.execute(select(ManagerReportSource,FinancialDailyImport).join(FinancialDailyImport,ManagerReportSource.import_id==FinancialDailyImport.id).where(active(ManagerReportSource,'manager')).order_by(FinancialDailyImport.report_date.desc()).offset((max(1,page)-1)*25).limit(25)).all()
    return templates.TemplateResponse(request,'operational_reports/manager.html',dict(request=request,user=user,rows=rows,today=str(date.today()),page=max(1,page),source=None,imports=db.scalars(select(FinancialDailyImport).order_by(FinancialDailyImport.report_date.desc()).limit(200)).all()))

@router.post('/gestor')
async def upload_manager(request:Request,report_date:str=Form(...),document:UploadFile|None=File(None),import_id:str=Form(''),supersedes_id:str=Form(''),db:Session=Depends(get_db),user:User=Depends(current_user)):
    if not can_manage(user):raise HTTPException(403)
    day=parsed_date(report_date)
    existing=None
    if import_id:
        try:existing=db.get(FinancialDailyImport,int(import_id))
        except ValueError:raise HTTPException(400,'Importação inválida.')
        if not existing:raise HTTPException(404,'Importação não encontrada.')
        content=existing.content;filename=existing.original_filename
        if existing.report_date.date()!=day:raise HTTPException(400,'A data deve corresponder ao documento já importado.')
    else:
        if not document:raise HTTPException(400,'Selecione um documento PDF ou Word.')
        content=await document.read(10*1024*1024+1);filename=PurePath((document.filename or '').replace('\\','/')).name
    if not content or len(content)>10*1024*1024:raise HTTPException(400,'O documento deve ter conteúdo e no máximo 10 MB.')
    fingerprint=hashlib.sha256(content).hexdigest()
    if db.scalar(select(ManagerReportSource.id).where(ManagerReportSource.fingerprint==fingerprint)):raise HTTPException(409,'Este documento já foi carregado. Consulte o histórico do Gestor.')
    try:
        if filename.lower().endswith('.pdf') and content.startswith(b'%PDF'):
            from pypdf import PdfReader
            reader=PdfReader(io.BytesIO(content))
            if reader.is_encrypted or not 1<=len(reader.pages)<=100:raise ValueError()
            extracted='\n'.join(p.extract_text() or '' for p in reader.pages);content_type='application/pdf'
        elif filename.lower().endswith('.docx'):
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                if sum(i.file_size for i in archive.infolist())>30*1024*1024:raise ValueError()
                from xml.etree import ElementTree
                tree=ElementTree.fromstring(archive.read('word/document.xml'))
                extracted='\n'.join(n.text or '' for n in tree.iter('{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t'))
            content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document'
        else:raise ValueError()
    except Exception as exc:raise HTTPException(400,'Documento inválido, corrompido ou protegido. Use um PDF ou Word legível, até 100 páginas.') from exc
    if existing is None:
        # Reuse an earlier financial upload of this exact original when available.
        for candidate in db.scalars(select(FinancialDailyImport).where(FinancialDailyImport.report_date>=utc_day(day),FinancialDailyImport.report_date<utc_day(day+timedelta(days=1)))).all():
            if hashlib.sha256(candidate.content).hexdigest()==fingerprint:existing=candidate;break
    if existing is None:
        existing=FinancialDailyImport(report_date=utc_day(day),period_month=day.strftime('%Y-%m'),original_filename=filename,content_type=content_type,content=content,extracted_text=extracted[:500000],extracted_metrics='{}',uploaded_by_id=user.id)
        db.add(existing);db.flush()
    supersedes=None
    if supersedes_id:
        try:supersedes=db.get(ManagerReportSource,int(supersedes_id))
        except ValueError:raise HTTPException(400,'Documento anterior inválido.')
        if not supersedes or supersedes.status!='Reviewed' or db.get(FinancialDailyImport,supersedes.import_id).report_date.date()!=day:raise HTTPException(400,'A correção deve referenciar um documento revisto da mesma data.')
    row=ManagerReportSource(import_id=existing.id,supersedes_id=supersedes.id if supersedes else None,fingerprint=fingerprint,metrics='[]',extraction_warning='Documento sem texto extraível: consulte o original e valide a informação complementar.' if not extracted.strip() else '')
    # Conservative suggestions only where a literal labelled value exists; never use missing=0.
    suggestions=[]
    for key,pattern in [('vehicles_total',r'TOTAL\s+VE[IÍ]CULOS\s*:?\s*(\d+)'),('seized_vehicles',r'VIATURAS\s+APREENDIDAS\s*:?\s*(\d+)'),('revenue',r'(?:RECEITA\s+TOTAL|TOTAL\s+RECEITA)\s*:?\s*([\d.,]+)')]:
        found=re.search(pattern,extracted,re.I)
        if found:suggestions.append({'key':key,'dimension':'Geral','value':str(number(found[1]))})
    row.metrics=dumps(suggestions);db.add(row);db.flush()
    audit_log(db,user,'Carregou relatório diário do Gestor','RelatoriosOperacionais',f'gestor:{row.id}',new_value={'filename':filename,'date':str(day)},request=request)
    save_or_conflict(db);return RedirectResponse(f'{router.prefix}/gestor/{row.id}',303)

def manager_source(db,user,source_id):
    if not (can_manage(user) or has_permission(user,'operational_reports_receive')):raise HTTPException(403)
    row=db.get(ManagerReportSource,source_id)
    if not row:raise HTTPException(404,'Documento não encontrado.')
    from app.models.reporting import ReportDeletion
    if db.scalar(select(ReportDeletion.id).where(ReportDeletion.kind=='manager',ReportDeletion.record_id==row.id)):raise HTTPException(404)
    return row,db.get(FinancialDailyImport,row.import_id)


@router.post('/gestor/{source_id}/ocr')
async def save_ocr(source_id:int,request:Request,db:Session=Depends(get_db),user:User=Depends(current_user)):
    row,original=manager_source(db,user,source_id)
    if not can_manage(user):raise HTTPException(403)
    if row.status!='Draft':raise HTTPException(409,'Crie uma nova revisão antes de reler este documento.')
    form=await request.form();check_revision(row,form.get('revision'))
    text=str(form.get('text','')).strip()
    if not re.sub(r'Página\s+\d+|\s','',text) or len(text)>500000:raise HTTPException(400,'O OCR não devolveu texto válido ou excedeu o limite.')
    if original.content_type!='application/pdf':raise HTTPException(400,'O OCR está disponível para PDF.')
    from pypdf import PdfReader
    pages=len(PdfReader(io.BytesIO(original.content)).pages)
    if str(pages)!=str(form.get('pages')):raise HTTPException(400,'O OCR deve incluir todas as páginas do documento.')
    original.extracted_text=text
    row.extraction_warning='Texto obtido por OCR: confira o original, os nomes e os valores antes de validar.'
    if not json.loads(row.metrics or '[]'):row.metrics=dumps(suggested_metrics(text))
    # Even repeated OCR must advance the revision for concurrent reviewers.
    row.revision+=1
    audit_log(db,user,'Reconheceu texto do PDF por OCR','RelatoriosOperacionais',f'gestor:{row.id}',new_value={'pages':pages,'characters':len(text)},request=request)
    save_or_conflict(db)
    return {'revision':row.revision,'characters':len(text)}

@router.get('/gestor/{source_id}')
def source_review(request:Request,source_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    row,original=manager_source(db,user,source_id)
    return templates.TemplateResponse(request,'operational_reports/manager.html',dict(request=request,user=user,source=row,original=original,metrics=json.loads(row.metrics),metric_options=METRICS,editable=can_manage(user) and row.status=='Draft'))

@router.get('/gestor/{source_id}/original')
def source_original(source_id:int,download:bool=False,db:Session=Depends(get_db),user:User=Depends(current_user)):
    row,original=manager_source(db,user,source_id)
    return Response(original.content,media_type=original.content_type,headers={'Content-Disposition':f'{"attachment" if download else "inline"}; filename="gestor-{row.id}{".pdf" if original.content_type=="application/pdf" else ".docx"}"'})

@router.post('/gestor/{source_id}/versao')
def revise_manager(request:Request,source_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    if not can_manage(user):raise HTTPException(403)
    row,original=manager_source(db,user,source_id)
    if row.status!='Reviewed':raise HTTPException(409,'Continue a revisão já em rascunho.')
    if db.scalar(select(ManagerReportSource.id).where(ManagerReportSource.supersedes_id==row.id)):
        raise HTTPException(409,'Já existe uma revisão posterior deste documento. Consulte o histórico do Gestor.')
    latest=db.scalar(select(func.max(ManagerReportSource.version)).where(ManagerReportSource.fingerprint==row.fingerprint)) or 1
    new=ManagerReportSource(import_id=row.import_id,fingerprint=row.fingerprint,version=latest+1,supersedes_id=row.id,metrics=row.metrics,notes=row.notes,extraction_warning=row.extraction_warning)
    db.add(new);db.flush()
    audit_log(db,user,'Criou revisão dos dados do Gestor','RelatoriosOperacionais',f'gestor:{new.id}',new_value={'previous':row.id,'version':new.version},request=request)
    save_or_conflict(db);return RedirectResponse(f'{router.prefix}/gestor/{new.id}',303)

@router.post('/gestor/{source_id}')
async def save_manager(source_id:int,request:Request,db:Session=Depends(get_db),user:User=Depends(current_user)):
    row,original=manager_source(db,user,source_id)
    if not can_manage(user):raise HTTPException(403)
    if row.status!='Draft':raise HTTPException(409,'O original validado é imutável. Carregue um documento corrigido para revisão.')
    form=await request.form();check_revision(row,form.get('revision'))
    metrics=[];seen=set()
    for i in range(200):
        key=str(form.get(f'metric_{i}_key',''));value=str(form.get(f'metric_{i}_value','')).strip()
        if not key or not value:continue
        if key not in METRICS:raise HTTPException(400,'Indicador inválido.')
        dimension=text_value(form.get(f'metric_{i}_dimension'),160) or 'Geral'
        if (key,dimension) in seen:raise HTTPException(400,'Um indicador e regime/equipamento não podem ser repetidos no mesmo documento.')
        seen.add((key,dimension));metrics.append({'key':key,'dimension':dimension,'value':str(metric_value(key,value))})
    row.metrics=dumps(metrics);row.notes=text_value(form.get('notes'))
    if form.get('action')=='review':
        if row.extraction_warning and not row.notes:raise HTTPException(400,'Registe o resultado da revisão do documento sem texto extraível.')
        row.status='Reviewed';row.reviewed_by_id=user.id;row.reviewed_at=datetime.now(timezone.utc)
    audit_log(db,user,'Reviu documento do Gestor','RelatoriosOperacionais',f'gestor:{row.id}',new_value={'status':row.status},request=request)
    save_or_conflict(db)
    if 'application/json' in request.headers.get('accept',''):return {'id':row.id,'revision':row.revision,'status':row.status}
    return RedirectResponse(f'{router.prefix}/gestor/{row.id}',303)

@router.get('/diarios/{daily_id}/dados')
def daily_entries(request:Request,daily_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    row=db.get(DepartmentDailyReport,daily_id)
    require_record(db,user,row,'daily')
    if not row:raise HTTPException(404)
    require_access(user,row.department_key)
    editable=row.status=='Draft' and row.created_by_id==user.id and can_generate(user,row.department_key)
    entries=db.scalars(select(DailyReportEntry).where(DailyReportEntry.report_id==daily_id)).all()
    return templates.TemplateResponse(request,'operational_reports/entries.html',dict(request=request,user=user,daily=row,entries=entries,editable=editable,categories=CATEGORIES,metrics=METRICS,priorities=PRIORITIES,users=db.scalars(select(User).where(User.is_active==True)).all()))

@router.post('/diarios/{daily_id}/dados')
async def add_entry(request:Request,daily_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    row=db.scalar(select(DepartmentDailyReport).where(DepartmentDailyReport.id==daily_id).with_for_update())
    require_record(db,user,row,'daily')
    if not row:raise HTTPException(404)
    require_access(user,row.department_key,True)
    if row.status!='Draft' or row.created_by_id!=user.id:raise HTTPException(409,'Os dados só podem ser alterados pelo autor enquanto o diário estiver em rascunho.')
    f=await request.form()
    if f.get('remove_id'):
        try:entry=db.get(DailyReportEntry,int(f['remove_id']))
        except ValueError:raise HTTPException(400)
        if not entry or entry.report_id!=row.id:raise HTTPException(404)
        db.delete(entry)
    else:
        category=str(f.get('category',''));title=text_value(f.get('title'),220);metric=str(f.get('metric_key',''));priority=str(f.get('priority','Normal'))
        if category not in CATEGORIES or not title or priority not in PRIORITIES or (metric and metric not in METRICS):raise HTTPException(400,'Preencha a categoria, o título e os indicadores válidos.')
        entry=DailyReportEntry(report_id=row.id,category=category,title=title,description=text_value(f.get('description')),location=text_value(f.get('location'),160),equipment=text_value(f.get('equipment'),160),occurrence_key=text_value(f.get('occurrence_key'),80),metric_key=metric,dimension=text_value(f.get('dimension'),160) or 'Geral',value=metric_value(metric,f.get('value')) if metric else None,requires_action=f.get('requires_action')=='on',priority=priority,owner_id=owner_id(db,f.get('owner_id')),due_date=parsed_date(f['due_date']) if f.get('due_date') else None)
        db.add(entry)
    row.updated_at=datetime.now(timezone.utc)
    audit_log(db,user,'Atualizou dados estruturados do diário','RelatoriosOperacionais',row.number,request=request)
    save_or_conflict(db);return RedirectResponse(f'{router.prefix}/diarios/{daily_id}/dados',303)

@router.get('/{report_id}')
def detail(request:Request,report_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    row=read_report(db,user,report_id)
    versions=db.scalars(visible(select(OperationalReport),OperationalReport,'operational',user).where(OperationalReport.series_key==row.series_key).order_by(OperationalReport.version.desc())).all()
    return templates.TemplateResponse(request,'operational_reports/detail.html',dict(request=request,user=user,report=row,item=report_presentation(row),snapshot=json.loads(row.snapshot),notes=json.loads(row.supplements or '{}'),supplements=SUPPLEMENTS,versions=versions,editable=row.status!='Submitted' and can_generate(user,row.department_key) and (row.created_by_id==user.id or has_permission(user,'operational_reports_settings')),can_generate=can_generate(user,row.department_key),states=STATES,source_details=source_details,source_types=SOURCE_TYPES))

@router.post('/{report_id}/guardar')
async def save_review(request:Request,report_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    row=read_report(db,user,report_id,True);form=await request.form();check_revision(row,form.get('revision'))
    row.supplements=dumps({key:text_value(form.get(key)) for key in SUPPLEMENTS})
    action=str(form.get('action','Draft'))
    if action not in {'Draft','In Review','Submitted'}:raise HTTPException(400,'Estado inválido.')
    if action=='Submitted':submit_report(db,row,user)
    else:row.status=action
    if action!='Draft':audit_log(db,user,'Atualizou relatório operacional','RelatoriosOperacionais',str(row.id),new_value={'state':row.status},request=request)
    save_or_conflict(db)
    if 'application/json' in request.headers.get('accept',''):return {'id':row.id,'revision':row.revision,'status':row.status}
    return RedirectResponse(f'{router.prefix}/{row.id}',303)

@router.post('/{report_id}/regenerar')
def regenerate(request:Request,report_id:int,revision:int=Form(...),db:Session=Depends(get_db),user:User=Depends(current_user)):
    row=read_report(db,user,report_id,True);check_revision(row,revision)
    row.snapshot=dumps(build_snapshot(db,row.department_key,row.date_from,row.date_to,row.source_daily_id,row.period=='inspection',row.period,None if view_all(user) else user.id))
    row.status='Generated';save_or_conflict(db);return RedirectResponse(f'{router.prefix}/{row.id}',303)

@router.post('/{report_id}/versao')
def new_version(request:Request,report_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    row=read_report(db,user,report_id);require_access(user,row.department_key,True)
    if row.status!='Submitted':raise HTTPException(409,'Continue a versão em preparação.')
    new=create_report(db,user,row.department_key,row.period,row.date_from,row.date_to,row.source_daily_id,True)
    audit_log(db,user,'Criou nova versão de relatório','RelatoriosOperacionais',str(new.id),new_value={'previous':row.id},request=request)
    save_or_conflict(db);return RedirectResponse(f'{router.prefix}/{new.id}',303)

@router.get('/{report_id}/ficheiro/{format}')
def report_file(report_id:int,format:str,download:bool=False,db:Session=Depends(get_db),user:User=Depends(current_user)):
    row=read_report(db,user,report_id)
    if format not in {'pdf','docx'}:raise HTTPException(404,'Formato não encontrado.')
    if row.status=='Submitted':
        content=getattr(row,format)
        if not content:raise HTTPException(404,'O ficheiro oficial não está disponível. Contacte a administração; a versão não será regenerada silenciosamente.')
    else:
        item=report_presentation(row);content=(reports_pdf if format=='pdf' else reports_docx)([item],item['title'],user.full_name)
    return Response(content,media_type='application/pdf' if format=='pdf' else 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',headers={'Content-Disposition':f'{"attachment" if download or format=="docx" else "inline"}; filename="{row.number}.{format}"'})
