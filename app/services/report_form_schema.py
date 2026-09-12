from copy import deepcopy
import json
from sqlalchemy import select
from app.models.reporting import ReportFormSchema, DepartmentReportTables
from app.services.department_tables import TABLES

OPTIONS = {
    'Empresa': ['GT/SA', 'G4S'],
    'Posto / patrulha': ['Entrada', 'Saída', 'Parque', 'Patrulha diurna', 'Patrulha nocturna'],
    'Turno / horário': ['Diurno', 'Nocturno'],
    'Situação': ['Presente', 'Falta', 'Férias', 'Dispensa'],
    'Estado': ['Operacional', 'Com anomalia', 'Fora de serviço', 'Em manutenção', 'Concluído', 'Pendente'],
    'Equipamento / bomba': ['Bomba do furo 1', 'Bomba do furo 2', 'Bomba de incêndio 1', 'Bomba de incêndio 2'],
    'Equipamento': ['Gerador New Way', 'Gerador Baudouin', 'Bombas de água'],
    'Teste de álcool': ['Negativo', 'Positivo', 'Não realizado'],
    'Cargo / função': ['Vigilante', 'Supervisor', 'Chefe de turno'],
    'Movimento': ['Entrada', 'Saída'],
}


def current_schema(db, department):
    row=db.scalar(select(ReportFormSchema).where(ReportFormSchema.department_key==department))
    if row:return {**json.loads(row.payload), 'revision':row.revision}
    tables=deepcopy(TABLES[department])
    for table in tables:table['choices']=[OPTIONS.get(label,[]) for label in table['columns']]
    return {'revision':0,'tables':tables,'shift':['Diurno','Nocturno'],'location':[]}


def schema_for_report(db, department, report=None):
    stored=db.get(DepartmentReportTables,report.id) if report and report.id else None
    if report and report.id:
        payload=json.loads(stored.payload) if stored else {}
        if '_schema' in payload:return payload['_schema']
        # Old drafts keep their original columns, even after a configuration change.
        return {'revision':-1,'tables':deepcopy(TABLES[department]),'shift':[],'location':[]}
    return current_schema(db,department)
