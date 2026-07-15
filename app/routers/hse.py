from fastapi import APIRouter, Depends, Request

from app.models.core import User
from app.routers.common import templates
from app.security import has_permission, require_permission

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


@router.get("")
def hse_home(request: Request, user: User = Depends(require_permission("hse_view"))):
    modules = [
        {
            **module,
            "enabled": has_permission(user, module["permission"]),
        }
        for module in HSE_MODULES
    ]
    return templates.TemplateResponse(
        request,
        "hse/index.html",
        {
            "request": request,
            "user": user,
            "modules": modules,
            "can_manage_hse_settings": has_permission(user, "hse_settings"),
            "can_view_hse_reports": has_permission(user, "hse_reports"),
        },
    )
