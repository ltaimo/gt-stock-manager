"""Versioned table shapes; cells remain literal observations, never inferred metrics."""
import json
from fastapi import HTTPException
from sqlalchemy.orm import object_session
from app.models.reporting import DepartmentReportTables


def spec(key, section, title, columns):
    return dict(key=key, section=section, title=title, columns=columns)


TABLES = {
    'security': [
        spec('parade', 'team', 'Presenças na parada conjunta', ['N.º', 'Nome do vigilante', 'Empresa', 'Hora da parada', 'Cargo / função', 'Teste de álcool', 'Carro / viatura']),
        spec('staff', 'team', 'Faltas, férias e efetivo', ['Nome', 'Empresa', 'Situação', 'Período', 'Observações']),
        spec('posts', 'activities', 'Distribuição de postos e patrulhas', ['Posto / patrulha', 'Vigilante', 'Empresa', 'Turno / horário', 'Observações']),
        spec('seizures', 'equipment_status', 'Movimentos de apreensões', ['Movimento', 'Viatura / mercadoria', 'Referência / matrícula', 'Quantidade', 'Destino / origem', 'Observações']),
        spec('security_readings', 'readings', 'Iluminação, geradores e leituras', ['Local / equipamento', 'Data / hora', 'Estado', 'Leitura', 'Unidade', 'Observações']),
        spec('security_incidents', 'incidents', 'Registo de incidentes', ['Hora', 'Local', 'Ocorrência', 'Medida tomada', 'Responsável']),
    ],
    'maintenance': [
        spec('maintenance_team', 'team', 'Equipa e duração da manutenção', ['Nome', 'Função', 'Horário / duração', 'Observações']),
        spec('equipment', 'equipment_status', 'Equipamentos inspecionados', ['Equipamento', 'Local', 'Inspecionado por', 'Estado', 'Observações']),
        spec('tasks', 'activities', 'Tarefas planificadas e trabalhos executados', ['Equipamento / local', 'Tarefa planificada', 'Trabalho executado', 'Responsável', 'Duração', 'Estado']),
        spec('emergencies', 'incidents', 'Paragens e emergências', ['Equipamento', 'Início', 'Fim / duração', 'Avaria', 'Intervenção', 'Estado']),
        spec('utilities', 'readings', 'Utilidades e equipamentos críticos', ['Equipamento / bomba', 'Estado', 'Leitura', 'Unidade', 'Observações']),
    ],
    'it': [
        spec('it_work', 'activities', 'Intervenções e suporte', ['Equipamento / sistema', 'Pedido / ticket', 'Intervenção', 'Responsável', 'Estado']),
        spec('it_checks', 'equipment_status', 'Equipamentos e sistemas verificados', ['Equipamento / sistema', 'Local', 'Estado', 'Observações']),
    ],
}


def parse_tables(raw, department, schema=None):
    if len(raw or '') > 600000:
        raise HTTPException(400, 'Tabelas demasiado extensas. Divida o relatório por turno.')
    try:
        data = json.loads(raw or '{}')
        if not isinstance(data, dict): raise ValueError()
        known = {s['key']: s for s in (schema['tables'] if schema else TABLES[department])}
        if set(data) - set(known): raise ValueError()
        clean = {}
        total = 0
        for key, table in data.items():
            if not isinstance(table, dict) or set(table) - {'rows', 'note'}: raise ValueError()
            rows = table.get('rows', [])
            note = table.get('note', '')
            if not isinstance(rows, list) or len(rows) > 150 or not isinstance(note, str) or len(note) > 1000: raise ValueError()
            filtered = []
            for row in rows:
                if not isinstance(row, list) or len(row) != len(known[key]['columns']): raise ValueError()
                if any(not isinstance(cell, str) or len(cell) > 1000 for cell in row): raise ValueError()
                row = [cell.strip() for cell in row]
                if any(row): filtered.append(row)
            total += len(filtered)
            if total > 400: raise ValueError()
            if filtered or note.strip(): clean[key] = {'rows': filtered, 'note': note.strip()}
        return clean
    except (ValueError, TypeError, KeyError):
        raise HTTPException(400, 'Tabela inválida. Use até 150 linhas por tabela, 400 no relatório e 1000 caracteres por célula.')


def load_tables(report):
    db = object_session(report)
    row = db.get(DepartmentReportTables, report.id) if db and report.id else None
    return {k:v for k,v in json.loads(row.payload).items() if k != '_schema'} if row else {}


def save_tables(db, report, data, schema=None):
    row = db.get(DepartmentReportTables, report.id)
    if row is None:
        row = DepartmentReportTables(report_id=report.id)
        db.add(row)
    row.payload = json.dumps({**data, **({'_schema':schema} if schema else {})}, ensure_ascii=False)
    db.flush()


def present_tables(report):
    from app.services.report_form_schema import schema_for_report
    data = load_tables(report)
    db=object_session(report)
    specs=schema_for_report(db,report.department_key,report)['tables'] if db else TABLES[report.department_key]
    return [{**s, **data[s['key']]} for s in specs if s['key'] in data]
