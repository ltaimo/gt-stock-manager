import secrets
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.models.core import ApprovalMatrixRule, Category, Department, InternalOperationOption, Product, Requisition, Role, StockMovement, User
from app.routers.common import templates
from app.security import grant_permissions, require_permission
from app.services.audit import audit_log
from app.services.categorization import normalize_text
from app.services.forms import optional_float, optional_int, required_float, required_text
from app.services.stock_reset import reset_all_stock
from app.services.transactions import atomic

router = APIRouter(prefix="/configuracoes", tags=["configuracoes"])
settings = get_settings()


INTERNAL_OPERATION_KINDS = {
    "": "Todas as operações",
    "fuel": "Combustível",
    "water": "Água",
    "energy": "Energia",
}

INTERNAL_OPERATION_OPTION_TYPES = {
    "company": {
        "label": "Empresas / fornecedores",
        "singular": "Empresa / fornecedor",
        "description": "Entidades usadas em compras de combustível, água, energia e outros consumos.",
        "default_kind": "",
    },
    "fuel_type": {
        "label": "Tipos de combustível",
        "singular": "Tipo de combustível",
        "description": "Ex.: Diesel 50ppm, Gasolina, Óleo ou outro combustível usado nas operações.",
        "default_kind": "fuel",
    },
    "asset": {
        "label": "Viaturas e equipamentos",
        "singular": "Viatura / equipamento",
        "description": "Máquinas, viaturas, empilhadeiras e outros ativos abastecidos.",
        "default_kind": "fuel",
    },
    "location": {
        "label": "Locais e contadores",
        "singular": "Local / contador",
        "description": "Residências, bypass, escritórios, furos, contadores e pontos de consumo.",
        "default_kind": "",
    },
    "payment_method": {
        "label": "Métodos de pagamento",
        "singular": "Método de pagamento",
        "description": "Métodos usados em compras e pagamentos: cheque, transferência, numerário ou outros.",
        "default_kind": "",
    },
}


SETTINGS_SECTIONS = {
    "categories": {
        "label": "Categorias de produto",
        "description": "Organização dos produtos e economato.",
    },
    "departments": {
        "label": "Departamentos",
        "description": "Estrutura usada em utilizadores, requisições, movimentos e relatórios.",
    },
    "internal_ops": {
        "label": "Operações internas",
        "description": "Listas de apoio para combustível, água, energia e consumos internos.",
    },
    "stock_reset": {
        "label": "Reset de stock",
        "description": "Área controlada para levar saldos de stock a zero com código de segurança.",
    },
}


def grouped_internal_options(options: list[InternalOperationOption]) -> dict[str, dict]:
    groups = {}
    for option_type, meta in INTERNAL_OPERATION_OPTION_TYPES.items():
        rows = [option for option in options if option.option_type == option_type]
        groups[option_type] = {
            **meta,
            "option_type": option_type,
            "options": rows,
            "active_count": len([option for option in rows if option.is_active]),
            "inactive_count": len([option for option in rows if not option.is_active]),
        }
    return groups


@router.get("")
def settings_home(
    request: Request,
    section: str = "",
    internal_group: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("settings_manage")),
):
    clean_section = section.strip()
    clean_internal_group = internal_group.strip()
    if clean_section and clean_section not in SETTINGS_SECTIONS:
        raise HTTPException(404)
    if clean_section == "internal_ops" and clean_internal_group and clean_internal_group not in INTERNAL_OPERATION_OPTION_TYPES:
        raise HTTPException(404)
    if clean_section != "internal_ops":
        clean_internal_group = ""
    internal_options = db.scalars(
        select(InternalOperationOption).order_by(
            InternalOperationOption.option_type,
            InternalOperationOption.kind,
            InternalOperationOption.name,
        )
    ).all()
    return templates.TemplateResponse(request, "settings/index.html",
        {
            "request": request,
            "user": user,
            "categories": db.scalars(select(Category).order_by(Category.name)).all(),
            "departments": db.scalars(select(Department).order_by(Department.name)).all(),
            "internal_options": internal_options,
            "internal_option_groups": grouped_internal_options(internal_options),
            "internal_option_types": INTERNAL_OPERATION_OPTION_TYPES,
            "internal_operation_kinds": INTERNAL_OPERATION_KINDS,
            "settings_sections": SETTINGS_SECTIONS,
            "selected_section": clean_section,
            "selected_internal_group": clean_internal_group,
            "reset_message": request.query_params.get("reset_message"),
            "reset_error": request.query_params.get("reset_error"),
            "reset_enabled": bool(settings.reset_stock_security_code),
        },
    )


@router.post("/categorias")
def add_category(
    request: Request,
    name: str | None = Form(None),
    name_en: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("settings_manage")),
):
    clean_name = required_text(name, "Nome da categoria", 120)
    clean_name_en = required_text(name_en, "Nome da categoria em inglês", 120) if str(name_en or "").strip() else None
    normalized = normalize_text(clean_name)
    existing = db.scalar(select(Category).where(Category.normalized_name == normalized))
    with atomic(db):
        if existing:
            existing.name = clean_name.title()
            existing.name_en = clean_name_en
            existing.is_active = True
            category = existing
        else:
            category = Category(name=clean_name.title(), name_en=clean_name_en, normalized_name=normalized, is_active=True)
            db.add(category)
            db.flush()
        audit_log(db, user, "Guardou categoria de produto", "Configurações", category.id, new_value={"name": category.name, "name_en": category.name_en}, request=request)
    return RedirectResponse("/configuracoes?section=categories", status_code=303)


@router.post("/categorias/{category_id}/remover")
def remove_category(category_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_permission("settings_manage"))):
    category = db.get(Category, category_id)
    if not category:
        raise HTTPException(404)
    in_use = db.scalar(select(Product.id).where(Product.category_id == category.id).limit(1))
    with atomic(db):
        old = {"name": category.name, "active": category.is_active}
        if in_use:
            category.is_active = False
            action = "Desativou categoria de produto"
        else:
            action = "Removeu categoria de produto"
            db.delete(category)
        audit_log(db, user, action, "Configurações", category_id, old_value=old, request=request)
    return RedirectResponse("/configuracoes?section=categories", status_code=303)


@router.post("/operacoes-internas/opcoes")
def add_internal_operation_option(
    request: Request,
    option_type: str | None = Form(None),
    name: str | None = Form(None),
    kind: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("settings_manage")),
):
    clean_type = required_text(option_type, "Tipo de configuracao", 40)
    if clean_type not in INTERNAL_OPERATION_OPTION_TYPES:
        raise HTTPException(400, "Escolha um tipo de configuracao valido.")
    clean_name = required_text(name, "Nome", 160)
    clean_kind = (kind or "").strip() or None
    if clean_kind and clean_kind not in {"fuel", "water", "energy"}:
        raise HTTPException(400, "Escolha um modulo de operacao interna valido.")
    existing = db.scalar(
        select(InternalOperationOption).where(
            InternalOperationOption.option_type == clean_type,
            InternalOperationOption.name.ilike(clean_name),
        )
    )
    with atomic(db):
        if existing:
            existing.name = clean_name
            existing.kind = clean_kind
            existing.is_active = True
            option = existing
        else:
            option = InternalOperationOption(option_type=clean_type, name=clean_name, kind=clean_kind, is_active=True)
            db.add(option)
            db.flush()
        audit_log(db, user, "Guardou configuracao de operacao interna", "Configuracoes", option.id, new_value={"type": option.option_type, "name": option.name, "kind": option.kind}, request=request)
    return RedirectResponse(f"/configuracoes?section=internal_ops&internal_group={clean_type}", status_code=303)


@router.post("/operacoes-internas/opcoes/{option_id}/remover")
def remove_internal_operation_option(option_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_permission("settings_manage"))):
    option = db.get(InternalOperationOption, option_id)
    if not option:
        raise HTTPException(404)
    with atomic(db):
        old = {"type": option.option_type, "name": option.name, "active": option.is_active}
        option.is_active = False
        audit_log(db, user, "Desativou configuracao de operacao interna", "Configuracoes", option_id, old_value=old, request=request)
    return RedirectResponse(f"/configuracoes?section=internal_ops&internal_group={option.option_type}", status_code=303)


@router.post("/operacoes-internas/opcoes/{option_id}/ativar")
def activate_internal_operation_option(option_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_permission("settings_manage"))):
    option = db.get(InternalOperationOption, option_id)
    if not option:
        raise HTTPException(404)
    with atomic(db):
        old = {"type": option.option_type, "name": option.name, "active": option.is_active}
        option.is_active = True
        audit_log(db, user, "Ativou configuracao de operacao interna", "Configuracoes", option_id, old_value=old, request=request)
    return RedirectResponse(f"/configuracoes?section=internal_ops&internal_group={option.option_type}", status_code=303)


@router.post("/departamentos")
def add_department(
    request: Request,
    name: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("settings_manage")),
):
    clean_name = required_text(name, "Nome do departamento", 120)
    existing = db.scalar(select(Department).where(Department.name.ilike(clean_name)))
    with atomic(db):
        if existing:
            existing.name = clean_name.title()
            existing.is_active = True
            department = existing
        else:
            department = Department(name=clean_name.title(), is_active=True)
            db.add(department)
            db.flush()
        audit_log(db, user, "Guardou departamento", "Configurações", department.id, new_value={"name": department.name}, request=request)
    return RedirectResponse("/configuracoes?section=departments", status_code=303)


@router.post("/departamentos/{department_id}/remover")
def remove_department(department_id: int, request: Request, db: Session = Depends(get_db), user: User = Depends(require_permission("settings_manage"))):
    department = db.get(Department, department_id)
    if not department:
        raise HTTPException(404)
    in_use = (
        db.scalar(select(User.id).where(User.department_id == department.id).limit(1))
        or db.scalar(select(StockMovement.id).where(StockMovement.department_id == department.id).limit(1))
        or db.scalar(select(Requisition.id).where(Requisition.department_id == department.id).limit(1))
    )
    with atomic(db):
        old = {"name": department.name, "active": department.is_active}
        if in_use:
            department.is_active = False
            action = "Desativou departamento"
        else:
            action = "Removeu departamento"
            db.delete(department)
        audit_log(db, user, action, "Configurações", department_id, old_value=old, request=request)
    return RedirectResponse("/configuracoes?section=departments", status_code=303)


@router.get("/matriz")
def matrix(request: Request, db: Session = Depends(get_db), user: User = Depends(require_permission("procurement_settings"))):
    rules = db.scalars(select(ApprovalMatrixRule).order_by(ApprovalMatrixRule.sort_order, ApprovalMatrixRule.min_value)).all()
    roles = db.scalars(select(Role).order_by(Role.name)).all()
    role_user_counts = dict(
        db.execute(
            select(User.role_id, func.count(User.id))
            .where(User.is_active == True)
            .group_by(User.role_id)
        ).all()
    )
    return templates.TemplateResponse(
        request,
        "settings/matrix.html",
        {
            "request": request,
            "user": user,
            "rules": rules,
            "roles": roles,
            "role_user_counts": role_user_counts,
            "error": None,
        },
    )


@router.post("/matriz")
def save_matrix(
    request: Request,
    rule_id: list[str] = Form([]),
    min_value: list[str] = Form([]),
    max_value: list[str] = Form([]),
    modality: list[str] = Form([]),
    final_approval: list[str] = Form([]),
    approver_role_id: list[str] = Form([]),
    is_active: list[str] = Form([]),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("procurement_settings")),
):
    active_ids = {int(value) for value in is_active if str(value).strip().isdigit()}
    if not (len(rule_id) == len(min_value) == len(max_value) == len(modality) == len(final_approval) == len(approver_role_id)):
        raise HTTPException(400, "A matriz enviada está incompleta.")
    with atomic(db):
        for idx, raw_id in enumerate(rule_id):
            parsed_id = optional_int(raw_id, "Regra")
            row_values = [min_value[idx], max_value[idx], modality[idx], final_approval[idx]]
            if not parsed_id and not any(str(value or "").strip() for value in row_values):
                continue
            min_amount = required_float(min_value[idx], "Valor minimo")
            max_amount = optional_float(max_value[idx], "Valor maximo")
            if min_amount < 0 or (max_amount is not None and max_amount < min_amount):
                raise HTTPException(400, "Intervalo de valor inválido na matriz.")
            rule = db.get(ApprovalMatrixRule, parsed_id) if parsed_id else ApprovalMatrixRule()
            if not rule:
                raise HTTPException(404)
            rule.min_value = min_amount
            rule.max_value = max_amount
            rule.modality = required_text(modality[idx], "Modalidade", 80)
            parsed_role_id = optional_int(approver_role_id[idx], "Perfil aprovador")
            approver_role = db.get(Role, parsed_role_id) if parsed_role_id else None
            if approver_role:
                grant_permissions(
                    approver_role,
                    {"requisitions_all", "requisitions_review", "procurement_value_approve"},
                )
            rule.approver_role_id = approver_role.id if approver_role else None
            rule.final_approval = approver_role.name if approver_role else required_text(final_approval[idx], "Aprovação final", 160)
            rule.sort_order = idx
            rule.is_active = bool(parsed_id and parsed_id in active_ids) or not parsed_id
            db.add(rule)
        audit_log(db, user, "Atualizou matriz de aprovação", "Configurações", request=request)
    return RedirectResponse("/configuracoes/matriz", status_code=303)


@router.post("/stock/reset")
def reset_stock(
    request: Request,
    security_code: str = Form(...),
    confirmation: str = Form(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("stock_reset")),
):
    configured_code = settings.reset_stock_security_code
    if not configured_code:
        message = quote("O código de segurança para o reset de stock não está configurado.")
        return RedirectResponse(f"/configuracoes?section=stock_reset&reset_error={message}", status_code=303)
    if confirmation.strip().upper() != "RESETAR STOCK":
        message = quote('Escreva exatamente "RESETAR STOCK" para confirmar.')
        return RedirectResponse(f"/configuracoes?section=stock_reset&reset_error={message}", status_code=303)
    if not secrets.compare_digest(security_code.strip(), configured_code):
        message = quote("Código de segurança inválido.")
        return RedirectResponse(f"/configuracoes?section=stock_reset&reset_error={message}", status_code=303)

    with atomic(db):
        result = reset_all_stock(db, user)
        audit_log(db, user, "Resetou todo o stock", "Stock", "RESET-STOCK", new_value=result, request=request)

    message = quote(
        f"Stock resetado com sucesso. Produtos afetados: {result['products_affected']}; "
        f"quantidade removida: {result['quantity_removed']:g}."
    )
    return RedirectResponse(f"/configuracoes?section=stock_reset&reset_message={message}", status_code=303)
