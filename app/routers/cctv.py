import json
from datetime import date, datetime, timedelta, timezone
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.core import User, InternalOperationOption, Product
from app.models.reporting import CctvCamera, CctvStatusLog, CctvSchedule, CctvInspection, OperationalPending
from app.routers.common import templates
from app.routers.operational_reporting import save_or_conflict, check_revision
from app.security import current_user, has_permission
from app.services.reporting_common import *
from app.services.cctv import *
from app.services.audit import audit_log
from app.routers.reporting_route import ReportingRoute

router=APIRouter(prefix='/operacoes-internas',tags=['CCTV e pendências'],route_class=ReportingRoute)

def access(user,write=False):
    if not (has_permission(user,'cctv_manage') if write else (can_view(user,'it') or has_permission(user,'cctv_manage'))):raise HTTPException(403,'O seu perfil não permite esta operação CCTV.')

def camera_or_404(db,camera_id):
    camera=db.scalar(select(CctvCamera).where(CctvCamera.id==camera_id).with_for_update())
    if not camera:raise HTTPException(404,'Câmara não encontrada.')
    return camera

@router.get('/cctv')
def index(request:Request,area:str='',state:str='',day:str='',page:int=1,db:Session=Depends(get_db),user:User=Depends(current_user)):
    access(user);selected=parsed_date(day) if day else date.today()
    snapshot=cctv_snapshot(db,selected,selected)
    rows=[r for r in snapshot['cameras'] if (not area or r['area']==area) and (not state or r['status']==state)]
    return templates.TemplateResponse(request,'operational_reports/cctv.html',dict(request=request,user=user,camera=None,rows=rows[(max(page,1)-1)*25:max(page,1)*25],total=len(rows),page=max(page,1),stats=snapshot,areas=db.scalars(select(CctvCamera.area).distinct().order_by(CctvCamera.area)).all(),area=area,state=state,day=str(selected),statuses=status_options(db),editable=has_permission(user,'cctv_manage')))

@router.post('/cctv')
async def create_camera(request:Request,db:Session=Depends(get_db),user:User=Depends(current_user)):
    access(user,True);f=await request.form();code=text_value(f.get('code'),80).upper();area=text_value(f.get('area'),160)
    if not code or not area:raise HTTPException(400,'Indique o código e a área da câmara.')
    if db.scalar(select(CctvCamera.id).where(CctvCamera.code==code)):raise HTTPException(409,'Já existe uma câmara com este código.')
    product=None
    if f.get('product_id'):
        try:product=db.get(Product,int(f['product_id']))
        except ValueError:raise HTTPException(400,'Produto inválido.')
        if not product:raise HTTPException(400,'Produto não encontrado.')
    camera=CctvCamera(code=code,area=area,description=text_value(f.get('description'),220),model=text_value(f.get('model'),160),nvr=text_value(f.get('nvr'),160),location=text_value(f.get('location'),160),product_id=product.id if product else None,registered_on=date.today())
    db.add(camera);db.flush();audit_log(db,user,'Registou câmara CCTV','CCTV',str(camera.id),new_value={'code':code},request=request)
    save_or_conflict(db);return RedirectResponse(f'/operacoes-internas/cctv/{camera.id}',303)

@router.post('/cctv/estados')
def add_status(request:Request,name:str=Form(...),db:Session=Depends(get_db),user:User=Depends(current_user)):
    access(user,True);name=text_value(name,160)
    if not name:raise HTTPException(400,'Indique a designação do estado.')
    if name not in status_options(db):db.add(InternalOperationOption(option_type='cctv_status',name=name,kind='cctv'))
    save_or_conflict(db);return RedirectResponse('/operacoes-internas/cctv',303)

@router.get('/cctv/inspecoes')
def inspections(request:Request,date_from:str='',date_to:str='',db:Session=Depends(get_db),user:User=Depends(current_user)):
    access(user);start=parsed_date(date_from) if date_from else date.today();end=parsed_date(date_to) if date_to else start
    if end<start or (end-start).days>31:raise HTTPException(400,'Selecione até 31 dias de inspeções.')
    return templates.TemplateResponse(request,'operational_reports/inspections.html',dict(request=request,user=user,rows=checklist(db,start,end),date_from=str(start),date_to=str(end),results=INSPECTION_RESULTS,editable=has_permission(user,'cctv_manage'),today=date.today()))

@router.post('/cctv/inspecoes/{schedule_id}')
async def inspect_camera(request:Request,schedule_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    access(user,True);f=await request.form();schedule=db.get(CctvSchedule,schedule_id)
    if not schedule:raise HTTPException(404)
    camera=camera_or_404(db,schedule.camera_id);day=parsed_date(f.get('scheduled_on'));result=str(f.get('result'))
    if result not in INSPECTION_RESULTS or day>date.today() or not list(scheduled_dates(schedule,day,day)):raise HTTPException(400,'Data ou resultado de inspeção inválido.')
    if db.scalar(select(CctvInspection.id).where(CctvInspection.schedule_id==schedule.id,CctvInspection.scheduled_on==day)):raise HTTPException(409,'Esta inspeção já foi registada. O histórico não pode ser substituído.')
    previous=db.scalars(select(CctvStatusLog).where(CctvStatusLog.camera_id==camera.id).order_by(CctvStatusLog.effective_at.desc(),CctvStatusLog.id.desc())).first()
    row=CctvInspection(schedule_id=schedule.id,scheduled_on=day,result=result,previous_status=previous.status if previous else 'Sem observação',notes=text_value(f.get('notes')),performed_by_id=user.id)
    db.add(row);db.flush()
    if result in {'Necessita Manutenção','Câmara Indisponível'}:create_pending(db,user,f'inspection:{row.id}','it',f'{camera.code} — {result}',row.notes,camera_id=camera.id,owner=schedule.owner_id,priority='Alta')
    audit_log(db,user,'Registou inspeção CCTV','CCTV',str(camera.id),new_value={'result':result,'scheduled_on':str(day)},request=request)
    save_or_conflict(db);return RedirectResponse(f'/operacoes-internas/cctv/inspecoes?date_from={day}&date_to={day}',303)

@router.get('/cctv/{camera_id}')
def camera_detail(request:Request,camera_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    access(user);camera=db.get(CctvCamera,camera_id)
    if not camera:raise HTTPException(404)
    logs=db.scalars(select(CctvStatusLog).where(CctvStatusLog.camera_id==camera_id).order_by(CctvStatusLog.effective_at.desc(),CctvStatusLog.id.desc()).limit(100)).all()
    schedules=db.scalars(select(CctvSchedule).where(CctvSchedule.camera_id==camera_id).order_by(CctvSchedule.starts_on.desc())).all()
    return templates.TemplateResponse(request,'operational_reports/cctv.html',dict(request=request,user=user,camera=camera,logs=logs,schedules=schedules,statuses=status_options(db),priorities=PRIORITIES,users=db.scalars(select(User).where(User.is_active==True)).all(),editable=has_permission(user,'cctv_manage'),today=str(date.today()),now=datetime.now(timezone(timedelta(hours=2))).strftime('%Y-%m-%dT%H:%M')))

@router.post('/cctv/{camera_id}/estado')
async def log_state(request:Request,camera_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    access(user,True);camera=camera_or_404(db,camera_id);f=await request.form();status=str(f.get('status'));priority=str(f.get('priority','Normal'))
    try:
        effective=datetime.fromisoformat(str(f.get('effective_at')))
        if effective.tzinfo is None:effective=effective.replace(tzinfo=timezone(timedelta(hours=2)))
        effective=effective.astimezone(timezone.utc)
    except ValueError:raise HTTPException(400,'Data/hora inválida.')
    if status not in status_options(db) or priority not in PRIORITIES:raise HTTPException(400,'Estado ou prioridade inválida.')
    if effective>datetime.now(timezone.utc)+timedelta(minutes=1):raise HTTPException(400,'A observação não pode ser futura.')
    if record_day(effective)<camera.registered_on:raise HTTPException(400,'A observação não pode anteceder o cadastro da câmara.')
    previous=db.scalars(select(CctvStatusLog).where(CctvStatusLog.camera_id==camera_id).order_by(CctvStatusLog.effective_at.desc(),CctvStatusLog.id.desc())).first()
    if previous and effective.replace(tzinfo=None)<previous.effective_at.replace(tzinfo=None):raise HTTPException(409,'Registe observações em ordem cronológica para preservar o histórico de falhas.')
    row=CctvStatusLog(camera_id=camera_id,effective_at=effective,status=status,operational=f.get('operational')=='on',full_recording=f.get('full_recording')=='on',needs_cleaning=f.get('needs_cleaning')=='on' or status=='Necessita Limpeza',priority=priority,notes=text_value(f.get('notes')),created_by_id=user.id)
    db.add(row);db.flush()
    if row.needs_cleaning or not row.operational or not row.full_recording:
        open_item=db.scalar(select(OperationalPending).where(OperationalPending.camera_id==camera_id,OperationalPending.status!='Closed'))
        if not open_item:create_pending(db,user,f'camera-log:{row.id}','it',f'{camera.code} — {status}',row.notes,camera_id=camera_id,priority=priority)
    audit_log(db,user,'Registou estado CCTV','CCTV',str(camera_id),new_value={'state':status,'operational':row.operational,'recording':row.full_recording},request=request)
    save_or_conflict(db);return RedirectResponse(f'/operacoes-internas/cctv/{camera_id}',303)

@router.post('/cctv/{camera_id}/programar')
async def schedule_camera(request:Request,camera_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    access(user,True);camera=camera_or_404(db,camera_id);f=await request.form();start=parsed_date(f.get('starts_on'))
    try:interval=int(f.get('interval_days'))
    except (TypeError,ValueError):raise HTTPException(400,'Frequência inválida.')
    if not 1<=interval<=365 or start<date.today():raise HTTPException(400,'A nova programação deve começar hoje ou numa data futura, com frequência de 1 a 365 dias.')
    for old in db.scalars(select(CctvSchedule).where(CctvSchedule.camera_id==camera_id)).all():
        if old.starts_on>=start:raise HTTPException(409,'Já existe programação nessa data ou depois dela.')
        if old.ends_on is None or old.ends_on>=start:old.ends_on=start-timedelta(days=1)
    db.add(CctvSchedule(camera_id=camera_id,starts_on=start,interval_days=interval,owner_id=owner_id(db,f.get('owner_id')),notes=text_value(f.get('notes'))))
    audit_log(db,user,'Programou inspeções CCTV','CCTV',str(camera_id),new_value={'starts_on':str(start),'interval_days':interval},request=request)
    save_or_conflict(db);return RedirectResponse(f'/operacoes-internas/cctv/{camera_id}',303)

@router.get('/pendencias')
def pending_index(request:Request,department:str='',state:str='',page:int=1,db:Session=Depends(get_db),user:User=Depends(current_user)):
    allowed=[d for d in ['security','maintenance','it'] if can_view(user,d)]
    if department and department not in allowed:raise HTTPException(403)
    notify_overdue(db,allowed)
    stmt=select(OperationalPending).where(OperationalPending.department_key.in_([department] if department else allowed))
    if state:stmt=stmt.where(OperationalPending.status==state)
    rows=db.scalars(stmt.order_by(OperationalPending.opened_on.desc(),OperationalPending.id.desc()).offset((max(1,page)-1)*25).limit(25)).all()
    return templates.TemplateResponse(request,'operational_reports/pending.html',dict(request=request,user=user,rows=rows,allowed=allowed,departments=DEPARTMENTS,states=PENDING_STATES,department=department,state=state,page=max(1,page),priorities=PRIORITIES,users=db.scalars(select(User).where(User.is_active==True)).all(),today=date.today(),can_edit=lambda p:can_generate(user,p.department_key) or has_permission(user,'operational_pending_manage'),history=lambda p:json.loads(p.history or '[]')))

@router.post('/pendencias/{pending_id}')
async def update_pending(request:Request,pending_id:int,db:Session=Depends(get_db),user:User=Depends(current_user)):
    row=db.get(OperationalPending,pending_id)
    if not row:raise HTTPException(404)
    require_access(user,row.department_key)
    if not (can_generate(user,row.department_key) or has_permission(user,'operational_pending_manage')):raise HTTPException(403)
    f=await request.form();check_revision(row,f.get('revision'));state=str(f.get('status'))
    transitions={'Pending':['Pending','Assigned','In Progress'],'Assigned':['Assigned','In Progress'],'In Progress':['In Progress','Executed'],'Executed':['Executed','Verified','In Progress'],'Verified':['Verified','Closed','In Progress'],'Closed':[]}
    if state not in transitions[row.status]:raise HTTPException(400,'Transição inválida. Siga atribuição, execução, verificação e encerramento.')
    notes=text_value(f.get('notes'))
    if not notes:raise HTTPException(400,'Descreva a ação tomada.')
    row.owner_id=owner_id(db,f.get('owner_id'));row.due_date=parsed_date(f['due_date']) if f.get('due_date') else None
    if state!='Pending' and not row.owner_id:raise HTTPException(400,'Atribua um responsável antes de avançar.')
    row.status=state
    if state=='Closed':row.closed_on=date.today()
    events=json.loads(row.history or '[]');events.append({'date':datetime.now(timezone.utc).isoformat(),'status':state,'user_id':user.id,'owner_id':row.owner_id,'due_date':str(row.due_date) if row.due_date else None,'notes':notes});row.history=dumps(events)
    audit_log(db,user,'Atualizou pendência operacional','PendenciasOperacionais',str(row.id),new_value={'status':state},request=request)
    save_or_conflict(db);return RedirectResponse('/operacoes-internas/pendencias',303)
