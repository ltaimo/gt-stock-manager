import json
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.core import Department, HseRecord, User
from app.routers.common import templates
from app.security import has_permission, require_permission
from app.services.audit import audit_log
from app.services.forms import optional_int, required_text
from app.services.transactions import atomic

router = APIRouter(prefix="/hse", tags=["hse"])


HSE_MODULES = [
    {
        "key": "incidents",
        "title": "Incidentes e investigação",
        "description": "Registo, investigação, classificação e acompanhamento de incidentes e quase-acidentes.",
        "permission": "hse_records_create",
    },
    {
        "key": "risks",
        "title": "Riscos, JSA e ATS",
        "description": "Avaliações de risco, análises de segurança da tarefa, controlos e responsáveis.",
        "permission": "hse_records_create",
    },
    {
        "key": "permits",
        "title": "Permissões de trabalho",
        "description": "Gestão de PTW, aprovação, execução, fecho e histórico de alterações.",
        "permission": "hse_permits_approve",
    },
    {
        "key": "inspections",
        "title": "Inspeções e auditorias",
        "description": "Observações, inspeções planeadas, findings e ligação direta às ações corretivas.",
        "permission": "hse_records_create",
    },
    {
        "key": "actions",
        "title": "Ações corretivas",
        "description": "Tracker de ações, prazos, progresso, validação e encerramento controlado.",
        "permission": "hse_workflow_manage",
    },
    {
        "key": "training",
        "title": "Formação e competência",
        "description": "Registo de formações, validade, alertas de expiração e lacunas de competência.",
        "permission": "hse_records_edit",
    },
    {
        "key": "contractors",
        "title": "Contratados",
        "description": "Aprovação HSE, performance, documentação obrigatória e estado operacional.",
        "permission": "hse_records_edit",
    },
    {
        "key": "equipment",
        "title": "Emergência e equipamentos",
        "description": "Extintores, equipamentos de emergência, inspeções, estado e próxima manutenção.",
        "permission": "hse_records_edit",
    },
    {
        "key": "environment",
        "title": "Ambiente",
        "description": "Aspetos ambientais, controlos operacionais, consumo de recursos e monitorização.",
        "permission": "hse_records_edit",
    },
    {
        "key": "compliance",
        "title": "Conformidade legal",
        "description": "Registo legal, evidências, revisões, auditorias e conformidade do sistema.",
        "permission": "hse_records_close",
    },
]

HSE_STATUSES = ["Open", "In Progress", "Pending Verification", "Closed", "Cancelled"]
HSE_PRIORITIES = ["Low", "Normal", "High", "Critical"]


def module_config(module_key: str) -> dict | None:
    return next((module for module in HSE_MODULES if module["key"] == module_key), None)


def can_use_hse_module(user: User, module: dict | None) -> bool:
    return bool(module and has_permission(user, module["permission"]))


def next_hse_number(db: Session, module: str) -> str:
    prefix = {
        "incidents": "HSE-INC",
        "risks": "HSE-RISK",
        "permits": "HSE-PTW",
        "inspections": "HSE-INS",
        "actions": "HSE-ACT",
        "training": "HSE-TRN",
        "contractors": "HSE-CTR",
        "equipment": "HSE-EQP",
        "environment": "HSE-ENV",
        "compliance": "HSE-CMP",
    }.get(module, "HSE")
    year = datetime.now(timezone.utc).year
    count = db.scalar(select(func.count(HseRecord.id)).where(HseRecord.number.like(f"{prefix}-{year}-%"))) or 0
    return f"{prefix}-{year}-{count + 1:04d}"


def parse_due_date(value: str | None) -> datetime | None:
    cleaned = str(value or "").strip()
    if not cleaned:
        return None
    try:
        return datetime.fromisoformat(cleaned).replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise HTTPException(400, "Informe uma data válida no formato AAAA-MM-DD.") from exc


def hse_context(request: Request, db: Session, user: User, module: str = "", error: str | None = None) -> dict:
    stmt = select(HseRecord).order_by(HseRecord.created_at.desc())
    if module:
        stmt = stmt.where(HseRecord.module == module)
    records = db.scalars(stmt.limit(250)).all()
    modules = [
        {
            **item,
            "enabled": can_use_hse_module(user, item),
            "count": db.scalar(select(func.count(HseRecord.id)).where(HseRecord.module == item["key"])) or 0,
        }
        for item in HSE_MODULES
    ]
    manageable_modules = [item["key"] for item in modules if item["enabled"]]
    selected_config = module_config(module) if module else None
    selected_module_enabled = can_use_hse_module(user, selected_config) if selected_config else False
    return {
        "request": request,
        "user": user,
        "modules": modules,
        "records": records,
        "selected_module": module,
        "selected_module_enabled": selected_module_enabled,
        "manageable_hse_modules": manageable_modules,
        "departments": db.scalars(select(Department).where(Department.is_active == True).order_by(Department.name)).all(),
        "owners": db.scalars(select(User).where(User.is_active == True).order_by(User.full_name)).all(),
        "statuses": HSE_STATUSES,
        "priorities": HSE_PRIORITIES,
        "can_create_hse": has_permission(user, "hse_records_create") and (not module or selected_module_enabled),
        "can_workflow_hse": has_permission(user, "hse_workflow_manage"),
        "can_close_hse": has_permission(user, "hse_records_close"),
        "can_manage_hse_settings": has_permission(user, "hse_settings"),
        "can_view_hse_reports": has_permission(user, "hse_reports"),
        "error": error,
    }


@router.get("")
def hse_home(
    request: Request,
    module: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("hse_view")),
):
    if module and not module_config(module):
        raise HTTPException(404)
    return templates.TemplateResponse(
        request,
        "hse/index.html",
        hse_context(request, db, user, module),
    )


@router.post("/registos")
def create_hse_record(
    request: Request,
    module: str = Form(...),
    title: str = Form(...),
    description: str | None = Form(None),
    location: str | None = Form(None),
    priority: str = Form("Normal"),
    owner_id: str | None = Form(None),
    department_id: str | None = Form(None),
    due_date: str | None = Form(None),
    notes: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("hse_records_create")),
):
    config = module_config(module)
    if not config:
        raise HTTPException(400, "Escolha uma área HSE/HST válida.")
    if not can_use_hse_module(user, config):
        raise HTTPException(403, "Este perfil não tem permissão para registar nesta área HSE/HST.")
    if priority not in HSE_PRIORITIES:
        raise HTTPException(400, "Escolha uma prioridade válida.")
    parsed_owner_id = optional_int(owner_id, "Responsável")
    parsed_department_id = optional_int(department_id, "Departamento")
    owner = db.get(User, parsed_owner_id) if parsed_owner_id else None
    department = db.get(Department, parsed_department_id) if parsed_department_id else None
    if parsed_owner_id and not owner:
        raise HTTPException(400, "O responsável selecionado não existe.")
    if parsed_department_id and not department:
        raise HTTPException(400, "O departamento selecionado não existe.")

    with atomic(db):
        record = HseRecord(
            number=next_hse_number(db, module),
            module=module,
            title=required_text(title, "Título", 220),
            description=(description or "").strip() or None,
            location=(location or "").strip() or None,
            priority=priority,
            owner_id=owner.id if owner else None,
            department_id=department.id if department else None,
            due_date=parse_due_date(due_date),
            notes=(notes or "").strip() or None,
            created_by_id=user.id,
            workflow_history=json.dumps(
                [{"at": datetime.now(timezone.utc).isoformat(), "by": user.full_name, "status": "Open", "note": "Registo criado"}],
                ensure_ascii=False,
            ),
        )
        db.add(record)
        db.flush()
        audit_log(db, user, "Criou registo HSE/HST", "HSE/HST", record.number, new_value={"module": module, "title": record.title}, request=request)
    return RedirectResponse(f"/hse?module={module}", status_code=303)


@router.post("/registos/{record_id}/estado")
def update_hse_status(
    record_id: int,
    request: Request,
    status: str = Form(...),
    progress: int = Form(0),
    update_note: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("hse_workflow_manage")),
):
    record = db.get(HseRecord, record_id)
    if not record:
        raise HTTPException(404)
    config = module_config(record.module)
    if config and not can_use_hse_module(user, config):
        raise HTTPException(403, "Este perfil não tem permissão para atualizar esta área HSE/HST.")
    if status not in HSE_STATUSES:
        raise HTTPException(400, "Escolha um estado HSE/HST válido.")
    if status == "Closed" and not has_permission(user, "hse_records_close"):
        raise HTTPException(403, "Este perfil não pode encerrar registos HSE/HST.")
    clean_note = required_text(update_note, "Nota de atualização", 500)
    progress = max(0, min(100, int(progress or 0)))
    old_value = {"status": record.status, "progress": record.progress}
    history = json.loads(record.workflow_history or "[]")
    history.append({"at": datetime.now(timezone.utc).isoformat(), "by": user.full_name, "status": status, "progress": progress, "note": clean_note})
    with atomic(db):
        record.status = status
        record.progress = progress
        record.workflow_history = json.dumps(history, ensure_ascii=False)
        if status == "Closed":
            record.closed_at = datetime.now(timezone.utc)
            record.closed_by_id = user.id
        audit_log(db, user, "Atualizou workflow HSE/HST", "HSE/HST", record.number, old_value=old_value, new_value={"status": status, "progress": progress}, request=request)
    return RedirectResponse(f"/hse?module={record.module}", status_code=303)
