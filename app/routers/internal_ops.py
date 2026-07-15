from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.core import Department, InternalOperationOption, InternalOperationRecord, User
from app.routers.common import templates
from app.security import has_permission, require_permission
from app.services.audit import audit_log
from app.services.forms import optional_float, optional_int, required_float, required_text
from app.services.transactions import atomic

router = APIRouter(prefix="/operacoes-internas", tags=["operacoes-internas"])


OPERATION_KINDS = {
    "fuel": {"label": "Combustível", "unit": "L"},
    "water": {"label": "Água", "unit": "L"},
    "energy": {"label": "Energia", "unit": "kWh"},
}
OPERATION_TYPES = {
    "fuel": [
        ("fuel_purchase_storage", "Compra para armazenamento"),
        ("fuel_refuel", "Abastecimento de máquina/viatura"),
    ],
    "water": [("water_purchase", "Compra de água")],
    "energy": [
        ("energy_purchase", "Compra/pagamento de energia"),
        ("energy_reading", "Leitura de energia"),
    ],
}
PAYMENT_METHODS = ["Cheque", "Transferência", "Numerário", "Outro"]
OPERATION_STATUSES = ["Registered", "Validated", "Cancelled"]


def next_operation_number(db: Session, kind: str) -> str:
    prefix = {"fuel": "FUEL", "water": "WATER", "energy": "ENERGY"}.get(kind, "OPS")
    year = datetime.now(timezone.utc).year
    count = db.scalar(select(func.count(InternalOperationRecord.id)).where(InternalOperationRecord.number.like(f"{prefix}-{year}-%"))) or 0
    return f"{prefix}-{year}-{count + 1:04d}"


def parse_record_date(value: str | None) -> datetime:
    cleaned = str(value or "").strip()
    if not cleaned:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(cleaned).replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise HTTPException(400, "Informe uma data válida no formato AAAA-MM-DD.") from exc


def operations_context(request: Request, db: Session, user: User, kind: str = "", error: str | None = None) -> dict:
    stmt = select(InternalOperationRecord).order_by(InternalOperationRecord.record_date.desc(), InternalOperationRecord.id.desc())
    if kind:
        stmt = stmt.where(InternalOperationRecord.kind == kind)
    records = db.scalars(stmt.limit(250)).all()
    totals = {
        item_kind: {
            "count": db.scalar(select(func.count(InternalOperationRecord.id)).where(InternalOperationRecord.kind == item_kind)) or 0,
            "amount": db.scalar(select(func.coalesce(func.sum(InternalOperationRecord.amount), 0)).where(InternalOperationRecord.kind == item_kind)) or 0,
        }
        for item_kind in OPERATION_KINDS
    }
    option_rows = db.scalars(
        select(InternalOperationOption)
        .where(InternalOperationOption.is_active == True)
        .order_by(InternalOperationOption.option_type, InternalOperationOption.name)
    ).all()
    operation_options = {
        option_type: [
            option
            for option in option_rows
            if option.option_type == option_type and (not option.kind or not kind or option.kind == kind)
        ]
        for option_type in ["company", "fuel_type", "asset"]
    }
    return {
        "request": request,
        "user": user,
        "records": records,
        "kinds": OPERATION_KINDS,
        "operation_types": OPERATION_TYPES,
        "payment_methods": PAYMENT_METHODS,
        "statuses": OPERATION_STATUSES,
        "totals": totals,
        "operation_options": operation_options,
        "selected_kind": kind,
        "departments": db.scalars(select(Department).where(Department.is_active == True).order_by(Department.name)).all(),
        "can_create_internal_ops": has_permission(user, "internal_ops_create"),
        "can_approve_internal_ops": has_permission(user, "internal_ops_approve"),
        "error": error,
    }


@router.get("")
def operations_home(
    request: Request,
    kind: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("internal_ops_view")),
):
    if kind and kind not in OPERATION_KINDS:
        raise HTTPException(404)
    return templates.TemplateResponse(request, "internal_ops/index.html", operations_context(request, db, user, kind))


@router.post("/registos")
def create_operation_record(
    request: Request,
    kind: str = Form(...),
    operation_type: str | None = Form(None),
    record_date: str | None = Form(None),
    description: str = Form(...),
    supplier: str | None = Form(None),
    fuel_type: str | None = Form(None),
    asset_name: str | None = Form(None),
    odometer_reading: str | None = Form(None),
    meter_reading: str | None = Form(None),
    quantity: str | None = Form(None),
    unit: str | None = Form(None),
    amount: str | None = Form(None),
    payment_method: str | None = Form(None),
    location: str | None = Form(None),
    department_id: str | None = Form(None),
    responsible_person: str | None = Form(None),
    reference_number: str | None = Form(None),
    notes: str | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("internal_ops_create")),
):
    if kind not in OPERATION_KINDS:
        raise HTTPException(400, "Escolha um tipo de operação interna válido.")
    allowed_operation_types = {value for value, _label in OPERATION_TYPES[kind]}
    clean_operation_type = (operation_type or "").strip() or next(iter(allowed_operation_types))
    if clean_operation_type not in allowed_operation_types:
        raise HTTPException(400, "Escolha uma operação válida.")
    parsed_department_id = optional_int(department_id, "Departamento")
    department = db.get(Department, parsed_department_id) if parsed_department_id else None
    if parsed_department_id and not department:
        raise HTTPException(400, "O departamento selecionado não existe.")
    parsed_quantity = optional_float(quantity, "Quantidade", 0) or 0
    parsed_amount = optional_float(amount, "Valor", 0) or 0
    parsed_odometer = optional_float(odometer_reading, "Leitura do odómetro") if str(odometer_reading or "").strip() else None
    parsed_meter = optional_float(meter_reading, "Leitura do contador") if str(meter_reading or "").strip() else None
    if parsed_quantity < 0 or parsed_amount < 0:
        raise HTTPException(400, "Quantidade e valor não podem ser negativos.")
    if parsed_odometer is not None and parsed_odometer < 0:
        raise HTTPException(400, "A leitura do odómetro não pode ser negativa.")
    if parsed_meter is not None and parsed_meter < 0:
        raise HTTPException(400, "A leitura do contador não pode ser negativa.")
    if clean_operation_type == "fuel_refuel":
        if not (asset_name or "").strip():
            raise HTTPException(400, "Informe a máquina, viatura ou ativo abastecido.")
        if parsed_odometer is None:
            raise HTTPException(400, "A leitura do odómetro é obrigatória no abastecimento.")
    if clean_operation_type == "energy_reading" and parsed_meter is None:
        raise HTTPException(400, "A leitura do contador é obrigatória na leitura de energia.")
    with atomic(db):
        record = InternalOperationRecord(
            number=next_operation_number(db, kind),
            kind=kind,
            operation_type=clean_operation_type,
            record_date=parse_record_date(record_date),
            description=required_text(description, "Descrição", 220),
            supplier=(supplier or "").strip() or None,
            fuel_type=(fuel_type or "").strip() or None,
            asset_name=(asset_name or "").strip() or None,
            odometer_reading=parsed_odometer,
            meter_reading=parsed_meter,
            quantity=parsed_quantity,
            unit=OPERATION_KINDS[kind]["unit"],
            amount=parsed_amount,
            payment_method=(payment_method or "").strip() or None,
            location=(location or "").strip() or None,
            department_id=department.id if department else None,
            responsible_person=(responsible_person or "").strip() or None,
            reference_number=(reference_number or "").strip() or None,
            notes=(notes or "").strip() or None,
            created_by_id=user.id,
        )
        db.add(record)
        db.flush()
        audit_log(db, user, "Criou operação interna", "Operações Internas", record.number, new_value={"kind": kind, "amount": parsed_amount}, request=request)
    return RedirectResponse(f"/operacoes-internas?kind={kind}", status_code=303)


@router.post("/registos/{record_id}/validar")
def validate_operation_record(
    record_id: int,
    request: Request,
    status: str = Form("Validated"),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("internal_ops_approve")),
):
    record = db.get(InternalOperationRecord, record_id)
    if not record:
        raise HTTPException(404)
    if status not in OPERATION_STATUSES:
        raise HTTPException(400, "Escolha um estado válido.")
    old_status = record.status
    with atomic(db):
        record.status = status
        if status == "Validated":
            record.approved_by_id = user.id
            record.approved_at = datetime.now(timezone.utc)
        audit_log(db, user, "Validou operação interna", "Operações Internas", record.number, old_value={"status": old_status}, new_value={"status": status}, request=request)
    return RedirectResponse(f"/operacoes-internas?kind={record.kind}", status_code=303)
