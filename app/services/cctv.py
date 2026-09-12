"""Append-only observations and dated schedules preserve historical indicators."""
import json
from datetime import date, datetime, timedelta, timezone
from sqlalchemy import select
from app.models.core import InternalOperationOption
from app.models.reporting import CctvCamera, CctvStatusLog, CctvSchedule, CctvInspection, OperationalPending
from app.services.reporting_common import dumps, utc_day, record_day

STATUS_DEFAULTS = ['Operacional', 'Com Falha', 'Offline', 'Problema de Gravação', 'Problema de Imagem', 'Necessita Limpeza', 'Em Manutenção']
PENDING_STATES = {'Pending':'Pendente', 'Assigned':'Atribuído', 'In Progress':'Em execução', 'Executed':'Executado', 'Verified':'Verificado', 'Closed':'Encerrado'}
INSPECTION_RESULTS = ['Concluído', 'Não Realizado', 'Necessita Manutenção', 'Câmara Indisponível']

def status_options(db):
    return list(dict.fromkeys(STATUS_DEFAULTS + list(db.scalars(select(InternalOperationOption.name).where(InternalOperationOption.option_type=='cctv_status', InternalOperationOption.is_active==True)).all())))

def pending_state_at(item, end):
    events=[e for e in json.loads(item.history or '[]') if record_day(e['date']) <= end]
    return events[-1]['status'] if events else 'Pending'

def create_pending(db, user, key, department, title, description='', camera_id=None, owner=None, priority='Normal', due=None, opened=None):
    existing=db.scalar(select(OperationalPending).where(OperationalPending.source_key==key))
    if existing: return existing
    opened=opened or date.today()
    item=OperationalPending(source_key=key, department_key=department, title=title, description=description, camera_id=camera_id, owner_id=owner, priority=priority, due_date=due, opened_on=opened, history=dumps([{'date':datetime.now(timezone.utc).isoformat(), 'status':'Pending','user_id':user.id,'owner_id':owner,'due_date':str(due) if due else None,'notes':description}]))
    db.add(item);db.flush()
    if priority=='Crítica':
        from app.services.notifications import notify_user
        from app.models.core import User
        from app.security import has_permission
        for target in db.scalars(select(User).where(User.is_active==True)).all():
            if has_permission(target,'operational_reports_manage') or target.id==owner:
                notify_user(db,target,'Pendência operacional crítica',title,'PendenciasOperacionais',str(item.id),email=False)
    return item

def notify_overdue(db, departments):
    """One in-app notice per due date, checked when the work queue is consulted."""
    from app.config import get_settings
    from app.services.notifications import notify_user
    from app.models.core import User
    from app.services.reporting_common import can_manage, can_generate
    if get_settings().sync_mode=='mirror':return
    users=db.scalars(select(User).where(User.is_active==True)).all()
    changed=False
    for item in db.scalars(select(OperationalPending).where(OperationalPending.department_key.in_(departments),OperationalPending.status!='Closed',OperationalPending.due_date<date.today())).all():
        events=json.loads(item.history or '[]');marker=str(item.due_date)
        if any(e.get('overdue_notice')==marker for e in events):continue
        for target in users:
            if target.id==item.owner_id or can_manage(target) or can_generate(target,item.department_key):
                notify_user(db,target,'Pendência com prazo ultrapassado',item.title,'PendenciasOperacionais',str(item.id),email=False)
        events.append({'date':datetime.now(timezone.utc).isoformat(),'status':item.status,'user_id':None,'owner_id':item.owner_id,'due_date':marker,'notes':'Aviso de prazo ultrapassado enviado aos responsáveis.','overdue_notice':marker})
        item.history=dumps(events);changed=True
    if changed:db.commit()

def scheduled_dates(schedule, start, end):
    start=max(start,schedule.starts_on)
    end=min(end,schedule.ends_on) if schedule.ends_on else end
    offset=max(0,(start-schedule.starts_on).days)
    first=schedule.starts_on+timedelta(days=((offset+schedule.interval_days-1)//schedule.interval_days)*schedule.interval_days)
    while first<=end:
        yield first
        first+=timedelta(days=schedule.interval_days)

def checklist(db,start,end):
    cameras={c.id:c for c in db.scalars(select(CctvCamera)).all()}
    done={(i.schedule_id,i.scheduled_on):i for i in db.scalars(select(CctvInspection).where(CctvInspection.scheduled_on>=start,CctvInspection.scheduled_on<=end)).all()}
    result=[]
    for s in db.scalars(select(CctvSchedule).where(CctvSchedule.starts_on<=end)).all():
        camera=cameras[s.camera_id]
        for day in scheduled_dates(s,start,end):
            if camera.retired_on and day>=camera.retired_on:continue
            result.append({'schedule':s,'camera':camera,'day':day,'inspection':done.get((s.id,day))})
    return sorted(result,key=lambda r:(r['day'],r['camera'].area,r['camera'].code))

def cctv_snapshot(db,start,end):
    end_exclusive=utc_day(end+timedelta(days=1))-timedelta(hours=2)
    cameras=db.scalars(select(CctvCamera).where(CctvCamera.registered_on<=end).order_by(CctvCamera.area,CctvCamera.code)).all()
    logs=db.scalars(select(CctvStatusLog).where(CctvStatusLog.effective_at<end_exclusive).order_by(CctvStatusLog.effective_at,CctvStatusLog.id)).all()
    by_camera={}
    for log in logs:by_camera.setdefault(log.camera_id,[]).append(log)
    details=[];durations=[];new_failures=resolved=0
    for camera in cameras:
        if camera.retired_on and camera.retired_on<=start:continue
        history=by_camera.get(camera.id,[])
        last=history[-1] if history else None
        days_operational=days_recording=known_days=0
        failure_start=None
        for entry in history:
            if not entry.operational and failure_start is None:
                failure_start=entry.effective_at
                if start<=record_day(entry.effective_at)<=end:new_failures+=1
            elif entry.operational and failure_start is not None:
                if start<=record_day(entry.effective_at)<=end:
                    resolved+=1;durations.append((entry.effective_at-failure_start).total_seconds()/3600)
                failure_start=None
        day=max(start,camera.registered_on)
        while day<=end and (not camera.retired_on or day<camera.retired_on):
            observed=[l for l in history if record_day(l.effective_at)<=day]
            if observed:
                known_days+=1;days_operational+=int(observed[-1].operational);days_recording+=int(observed[-1].full_recording)
            day+=timedelta(days=1)
        details.append({'id':camera.id,'code':camera.code,'area':camera.area,'status':last.status if last else 'Sem observação', 'operational':last.operational if last else None,'full_recording':last.full_recording if last else None,'needs_cleaning':last.needs_cleaning if last else None,'priority':last.priority if last else '', 'notes':last.notes if last else '', 'failure_since':failure_start.isoformat() if failure_start else None,'days_operational':days_operational,'days_recording':days_recording,'known_days':known_days,'logs':[{'id':l.id,'date':l.effective_at.isoformat(),'reported_at':l.reported_at.isoformat(),'status':l.status,'operational':l.operational,'full_recording':l.full_recording,'notes':l.notes,'user_id':l.created_by_id} for l in history]})
    checks=checklist(db,start,end)
    planned=len(checks)
    executed=sum(bool(r['inspection'] and record_day(r['inspection'].performed_at)<=end and r['inspection'].result=='Concluído') for r in checks)
    known=sum(d['operational'] is not None for d in details);operating=sum(d['operational'] is True for d in details)
    return {'total':len(details),'known':known,'operational':operating,'failed':sum(d['operational'] is False for d in details),'without_recording':sum(d['full_recording'] is False for d in details),'needs_cleaning':sum(d['needs_cleaning'] is True for d in details),'availability':round(100*operating/known,2) if known and known==len(details) else None,'new_failures':new_failures,'resolved_failures':resolved,'mean_failure_hours':round(sum(durations)/len(durations),2) if durations else None,'planned':planned,'executed':executed,'not_executed':planned-executed,'compliance':round(100*executed/planned,2) if planned else None,'cameras':details,'inspections':[{'schedule_id':r['schedule'].id,'camera_id':r['camera'].id,'code':r['camera'].code,'scheduled_on':r['day'].isoformat(),'result':r['inspection'].result if r['inspection'] and record_day(r['inspection'].performed_at)<=end else 'Não registado','notes':r['inspection'].notes if r['inspection'] and record_day(r['inspection'].performed_at)<=end else ''} for r in checks]}
