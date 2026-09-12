from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select

from app.models.core import DepartmentDailyReport
from app.services.department_presentation import SECTIONS


FIELDS = ('period_start', 'period_end', 'shift', 'prepared_by', 'supervisor', 'location',
          'team', 'activities', 'incidents', 'equipment_status', 'readings', 'pending_actions', 'notes')


def draft_version(report):
    value = report.updated_at
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def draft_number(department, key):
    try:
        token = UUID(key).hex
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(400, 'Rascunho inválido.')
    return {'maintenance': 'MAN', 'security': 'SEG', 'it': 'INF'}[department] + '-DR-' + token


def editable_draft(db, user, department, report_id=None, number=None):
    query = select(DepartmentDailyReport).with_for_update()
    query = query.where(DepartmentDailyReport.id == report_id) if report_id else query.where(DepartmentDailyReport.number == number)
    report = db.scalar(query)
    if report_id and not report:
        raise HTTPException(404)
    if report:
        from app.services.report_access import require_record
        require_record(db, user, report, 'daily')
        if report.created_by_id != user.id or report.department_key != department:
            raise HTTPException(403)
        if report.status != 'Draft':
            raise HTTPException(409, 'Este relatório já foi submetido. Abra um novo relatório.')
    return report


def draft_form_values(report):
    import json
    from app.services.department_tables import load_tables
    values = {field: getattr(report, field) or '' for field in FIELDS}
    values['structured_tables'] = json.dumps(load_tables(report), ensure_ascii=False)
    values.update(report_date=report.report_date.strftime('%Y-%m-%d'), status='Draft', draft_id=str(report.id), draft_version=draft_version(report))
    for field, _, subtitles in SECTIONS[report.department_key]:
        if not subtitles:
            continue
        text = values[field]
        lines = text.splitlines()
        current = field
        blocks = {field: []}
        markers = {title + ':': f'{field}__{i}' for i, title in enumerate(subtitles)}
        for line in lines:
            if line in markers:
                current = markers[line]
                blocks.setdefault(current, [])
            else:
                blocks[current].append(line)
        values.update({key: '\n'.join(lines).strip() for key, lines in blocks.items()})
    return values
