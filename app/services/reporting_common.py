import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from fastapi import HTTPException
from sqlalchemy import select
from app.models.core import User
from app.models.reporting import OperationalReportSettings
from app.security import has_permission

DEPARTMENTS = {'security': 'Segurança / DPS', 'maintenance': 'Manutenção', 'it': 'Informática / IT', 'consolidated': 'Gestão operacional'}
PERIODS = {'daily': 'Diário', 'weekly': 'Semanal', 'monthly': 'Mensal', 'inspection': 'Inspeção CCTV'}
STATES = {'Draft': 'Rascunho', 'Generated': 'Gerado', 'In Review': 'Em revisão', 'Submitted': 'Submetido'}
PRIORITIES = ['Normal', 'Alta', 'Crítica']
CATEGORIES = {'incident':'Incidente', 'maintenance':'Intervenção de manutenção', 'equipment':'Equipamento', 'energy':'Energia / combustível', 'movement':'Movimento / apreensão', 'metric':'Indicador', 'information':'Informação geral'}
# Label, unit, aggregation. A meter is a reading, never a quantity to sum.
METRICS = {
 'vehicles_in': ('Entradas de viaturas', 'viaturas', 'sum'),
 'vehicles_out': ('Saídas de viaturas', 'viaturas', 'sum'),
 'vehicles_total': ('Movimento de viaturas', 'viaturas', 'sum'),
 'vehicles_parked': ('Viaturas em parque', 'viaturas', 'last'),
 'seized_vehicles': ('Viaturas apreendidas', 'viaturas', 'last'),
 'revenue': ('Receita', 'MZN', 'sum'),
 'fuel_litres': ('Abastecimento de combustível', 'litros', 'sum'),
 'energy_kwh': ('Consumo de energia', 'kWh', 'sum'),
 'meter_kwh': ('Leitura do contador', 'kWh', 'reading'),
 'engine_hours': ('Leitura de horas do equipamento', 'horas', 'reading'),
 'diesel_level': ('Nível de diesel', '%', 'last'),
 'outage_minutes': ('Duração de cortes de energia', 'minutos', 'sum'),
 'tickets_resolved': ('Tickets resolvidos', 'tickets', 'sum'),
}

def dumps(value):
    return json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)

def display_number(value, unit=''):
    value=Decimal(str(value))
    places=2 if unit=='MZN' else max(0,-value.normalize().as_tuple().exponent)
    return f'{value:,.{places}f}'.replace(',','_').replace('.',',').replace('_','.')

def display_time(value):
    if not value:return 'Por submeter'
    stamp=datetime.fromisoformat(str(value))
    if stamp.tzinfo is None:stamp=stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone(timedelta(hours=2))).strftime('%d/%m/%Y %H:%M')+' · Maputo'

def date_ranges(values):
    dates=sorted({parsed_date(v) for v in values})
    if not dates:return ''
    ranges=[];first=last=dates[0]
    for day in dates[1:]:
        if day==last+timedelta(days=1):last=day;continue
        ranges.append((first,last));first=last=day
    ranges.append((first,last))
    return ', '.join(first.strftime('%d/%m') if first==last else first.strftime('%d/%m')+' a '+last.strftime('%d/%m') for first,last in ranges)

def parsed_date(value):
    try: return date.fromisoformat(str(value))
    except (TypeError, ValueError): raise HTTPException(400, 'Data inválida.')

def utc_day(value):
    return datetime.combine(value, datetime.min.time(), timezone.utc)

def record_day(value):
    stamp=datetime.fromisoformat(str(value))
    if stamp.tzinfo is None:stamp=stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone(timedelta(hours=2))).date()

def number(value):
    try:
        raw = str(value).strip().replace(' ', '')
        if ',' in raw: raw = raw.replace('.', '').replace(',', '.')
        result = Decimal(raw)
        if not result.is_finite() or result < 0 or result > Decimal('9999999999999'):
            raise ValueError()
        return result
    except (InvalidOperation, TypeError, ValueError): raise HTTPException(400, 'Indique um valor numérico válido, igual ou superior a zero.')

def text_value(value, limit=10000):
    value = str(value or '').strip()
    if len(value) > limit: raise HTTPException(400, f'Texto demasiado longo (máximo {limit} caracteres).')
    return value

def metric_value(key, value):
    result=number(value)
    unit=METRICS[key][1]
    if unit in {'viaturas','tickets'} and result!=result.to_integral_value():
        raise HTTPException(400,'As contagens devem ser números inteiros.')
    if unit=='%' and result>100:raise HTTPException(400,'A percentagem deve estar entre 0 e 100.')
    precision=Decimal('0.01') if unit=='MZN' else Decimal('0.0001')
    if result!=result.quantize(precision):raise HTTPException(400,'O valor tem demasiadas casas decimais para este indicador.')
    return result

def owner_id(db, value):
    if not value: return None
    try: user = db.get(User, int(value))
    except (ValueError, TypeError): raise HTTPException(400, 'Responsável inválido.')
    if not user or not user.is_active: raise HTTPException(400, 'Responsável inválido.')
    return user.id

def policy(db):
    return db.get(OperationalReportSettings, 1) or OperationalReportSettings(id=1, week_start=0, allow_partial=False)

def period_window(period, anchor, week_start=0):
    anchor = parsed_date(anchor)
    if period == 'daily': return anchor, anchor
    if period in {'weekly', 'inspection'}:
        start = anchor - timedelta(days=(anchor.weekday()-week_start)%7)
        return start, start+timedelta(days=6)
    if period == 'monthly':
        start=anchor.replace(day=1)
        end=(start.replace(day=28)+timedelta(days=4)).replace(day=1)-timedelta(days=1)
        return start,end
    raise HTTPException(400, 'Período inválido.')

def can_manage(user): return has_permission(user, 'operational_reports_manage')

def can_view(user, department):
    from app.routers.internal_ops import allowed_department_report_keys
    return (can_manage(user) or has_permission(user, 'operational_reports_receive') or department in allowed_department_report_keys(user)) if department != 'consolidated' else (can_manage(user) or has_permission(user, 'operational_reports_receive'))

def can_generate(user, department):
    from app.routers.internal_ops import can_create_department_report
    return can_manage(user) if department == 'consolidated' else can_create_department_report(user, department)

def require_access(user, department, write=False):
    if department not in DEPARTMENTS or not (can_generate(user, department) if write else can_view(user, department)):
        raise HTTPException(403, 'O seu perfil não permite esta operação neste departamento.')

def notify_reporting(db, actor, title, message, record_id, department=False):
    from app.services.notifications import notify_user
    for target in db.scalars(select(User).where(User.is_active == True)).all():
        if target.id != actor.id and has_permission(target, 'operational_reports_manage' if department else 'operational_reports_receive'):
            notify_user(db, target, title, message, 'RelatoriosOperacionais', str(record_id), email=False)
