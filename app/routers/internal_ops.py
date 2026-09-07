from datetime import datetime, time, timezone
import unicodedata

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import PlainTextResponse, RedirectResponse
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.core import Department, DepartmentDailyReport, InternalOperationOption, InternalOperationRecord, User
from app.routers.common import templates
from app.security import current_user, has_permission, require_permission
from app.services.audit import audit_log
from app.services.department_reports import format_department_report_for_daily, format_reports_for_daily_bundle
from app.services.forms import optional_float, optional_int, required_float, required_text
from app.services.transactions import atomic

router = APIRouter(prefix="/operacoes-internas", tags=["operacoes-internas"])


OPERATION_KINDS = {
    "general": {"label": "Operações gerais", "unit": "un", "icon": "G"},
    "fuel": {"label": "Combustível", "unit": "L", "icon": "F"},
    "water": {"label": "Água", "unit": "L", "icon": "W"},
    "energy": {"label": "Energia", "unit": "kWh", "icon": "E"},
    "equipment": {"label": "Equipamentos", "unit": "un", "icon": "EQ"},
}
OPERATION_TYPES = {
    "general": [
        ("general_purchase", "Compra/consumo geral"),
        ("general_service", "Serviço interno"),
        ("general_record", "Registo administrativo"),
    ],
    "fuel": [
        ("fuel_purchase_storage", "Compra para armazenamento"),
        ("fuel_refuel", "Abastecimento de máquina/viatura"),
    ],
    "water": [("water_purchase", "Compra de água")],
    "energy": [
        ("energy_purchase", "Compra/pagamento de energia"),
        ("energy_reading", "Leitura de energia"),
    ],
    "equipment": [
        ("equipment_purchase", "Compra de equipamento"),
        ("equipment_maintenance", "Manutenção/reparação"),
        ("equipment_assignment", "Atribuição/uso interno"),
    ],
}
PAYMENT_METHODS = ["Cheque", "Transferência", "Numerário", "Outro"]
OPERATION_STATUSES = ["Registered", "Validated", "Cancelled"]
DEPARTMENT_REPORTS = {
    "maintenance": {
        "label": "Departamento de Manutenção",
        "short": "Manutenção",
        "icon": "MN",
        "description": "Atividades, inspeções, equipamentos críticos, paragens, emergências e pendências.",
        "activity_label": "Tarefas executadas / atividades",
        "incident_label": "Paragens, emergências ou assuntos de manutenção",
        "equipment_label": "Equipamentos e utilidades críticas",
        "readings_label": "Leituras / medições",
    },
    "it": {
        "label": "Departamento de Informática",
        "short": "Informática",
        "icon": "IT",
        "description": "Suporte diário, sistemas, equipamentos, acessos, incidentes técnicos e pendências.",
        "activity_label": "Atividades dos ITs / suporte executado",
        "incident_label": "Incidentes técnicos / falhas de sistemas",
        "equipment_label": "Equipamentos, redes e sistemas verificados",
        "readings_label": "Indicadores técnicos / tickets / disponibilidade",
    },
    "security": {
        "label": "Departamento de Proteção e Segurança",
        "short": "Segurança",
        "icon": "SG",
        "description": "Ocorrências, apreensões, efetivo, postos, patrulhas, iluminação e leituras.",
        "activity_label": "Distribuição de postos / patrulhas / atividades",
        "incident_label": "Incidentes, apreensões e outras ocorrências",
        "equipment_label": "Iluminação, segurança física e meios operacionais",
        "readings_label": "Leituras / rondas / presenças",
    },
}
DEPARTMENT_REPORT_STATUSES = ["Draft", "Submitted", "Validated", "Cancelled"]
DEPARTMENT_REPORT_ACCESS_MARKERS = {
    "maintenance": {"manutencao", "maintenance"},
    "it": {"informatica", "it"},
    "security": {"seguranca", "security", "protecao"},
}
DEPARTMENT_REPORT_ADMIN_ROLES = {"SuperAdmin", "Admin"}
DEPARTMENT_REPORT_OPERATIONS_ROLES = {"Gestor Operacional", "Operações"}
QUANTITY_REQUIRED_TYPES = {
    "fuel_purchase_storage",
    "fuel_refuel",
    "water_purchase",
    "equipment_purchase",
    "equipment_assignment",
    "general_purchase",
}
AMOUNT_REQUIRED_TYPES = {
    "fuel_purchase_storage",
    "water_purchase",
    "energy_purchase",
    "equipment_purchase",
    "equipment_maintenance",
    "general_purchase",
    "general_service",
}
PAYMENT_TYPES = {
    "fuel_purchase_storage",
    "water_purchase",
    "energy_purchase",
    "equipment_purchase",
    "equipment_maintenance",
    "general_purchase",
    "general_service",
}
ASSET_REQUIRED_TYPES = {"fuel_refuel", "energy_reading", "equipment_maintenance", "equipment_assignment"}
TYPE_REQUIRED_TYPES = {"fuel_purchase_storage", "fuel_refuel", "equipment_purchase", "equipment_maintenance"}


def ensure_department_report_storage(db: Session) -> None:
    connection = db.connection()
    id_primary_key = "INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY" if connection.dialect.name == "postgresql" else "INTEGER PRIMARY KEY"
    connection.execute(
        text(
            f"""
            CREATE TABLE IF NOT EXISTS department_daily_reports (
                id {id_primary_key},
                number VARCHAR(40) UNIQUE NOT NULL,
                department_key VARCHAR(30) NOT NULL,
                report_date TIMESTAMP,
                period_start VARCHAR(40),
                period_end VARCHAR(40),
                shift VARCHAR(80),
                prepared_by VARCHAR(160),
                supervisor VARCHAR(160),
                location VARCHAR(160),
                team TEXT,
                activities TEXT,
                incidents TEXT,
                equipment_status TEXT,
                readings TEXT,
                pending_actions TEXT,
                notes TEXT,
                status VARCHAR(40) DEFAULT 'Draft',
                created_by_id INTEGER NOT NULL REFERENCES users(id),
                approved_by_id INTEGER REFERENCES users(id),
                approved_at TIMESTAMP,
                created_at TIMESTAMP,
                updated_at TIMESTAMP
            )
            """
        )
    )
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_department_daily_reports_number ON department_daily_reports (number)"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_department_daily_reports_department_key ON department_daily_reports (department_key)"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_department_daily_reports_report_date ON department_daily_reports (report_date)"))
    connection.execute(text("CREATE INDEX IF NOT EXISTS ix_department_daily_reports_status ON department_daily_reports (status)"))
    db.commit()


def next_operation_number(db: Session, kind: str) -> str:
    prefix = {"general": "OPS", "fuel": "FUEL", "water": "WATER", "energy": "ENERGY", "equipment": "EQUIP"}.get(kind, "OPS")
    year = datetime.now(timezone.utc).year
    count = db.scalar(select(func.count(InternalOperationRecord.id)).where(InternalOperationRecord.number.like(f"{prefix}-{year}-%"))) or 0
    return f"{prefix}-{year}-{count + 1:04d}"


def next_department_report_number(db: Session, department_key: str) -> str:
    prefix = {"maintenance": "MAN", "it": "IT", "security": "SEC"}.get(department_key, "OPS")
    year = datetime.now(timezone.utc).year
    count = db.scalar(select(func.count(DepartmentDailyReport.id)).where(DepartmentDailyReport.number.like(f"{prefix}-DR-{year}-%"))) or 0
    return f"{prefix}-DR-{year}-{count + 1:04d}"


def parse_record_date(value: str | None) -> datetime:
    cleaned = str(value or "").strip()
    if not cleaned:
        return datetime.now(timezone.utc)
    try:
        return datetime.fromisoformat(cleaned).replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise HTTPException(400, "Informe uma data válida no formato AAAA-MM-DD.") from exc


def parse_report_date(value: str | None) -> datetime:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise HTTPException(400, "Informe a data do relatório.")
    try:
        return datetime.fromisoformat(cleaned).replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise HTTPException(400, "Informe uma data válida no formato AAAA-MM-DD.") from exc


def optional_date_start(value: str | None) -> datetime | None:
    cleaned = str(value or "").strip()
    if not cleaned:
        return None
    try:
        return datetime.combine(datetime.fromisoformat(cleaned).date(), time.min).replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise HTTPException(400, "Informe uma data válida no formato AAAA-MM-DD.") from exc


def optional_date_end(value: str | None) -> datetime | None:
    cleaned = str(value or "").strip()
    if not cleaned:
        return None
    try:
        return datetime.combine(datetime.fromisoformat(cleaned).date(), time.max).replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise HTTPException(400, "Informe uma data válida no formato AAAA-MM-DD.") from exc


def _fold_text(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(char for char in normalized if not unicodedata.combining(char)).casefold()


def _contains_marker(haystack: str, marker: str) -> bool:
    if marker == "it":
        return any(token == "it" for token in haystack.replace("/", " ").replace("-", " ").split())
    return marker in haystack


def user_department_report_keys(user: User) -> list[str]:
    haystacks = [_fold_text(user.role.name), _fold_text(user.department.name if user.department else "")]
    matched = [
        key
        for key, markers in DEPARTMENT_REPORT_ACCESS_MARKERS.items()
        if any(_contains_marker(haystack, marker) for haystack in haystacks for marker in markers)
    ]
    return [key for key in DEPARTMENT_REPORTS if key in matched]


def can_view_all_department_reports(user: User) -> bool:
    return is_department_reports_admin(user) or user.role.name in DEPARTMENT_REPORT_OPERATIONS_ROLES or has_permission(user, "internal_ops_reports_view_all")


def allowed_department_report_keys(user: User) -> list[str]:
    if can_view_all_department_reports(user):
        return list(DEPARTMENT_REPORTS)
    own_keys = user_department_report_keys(user)
    if own_keys:
        return own_keys
    if has_permission(user, "internal_ops_reports"):
        return list(DEPARTMENT_REPORTS)
    return []


def require_department_report_access(user: User, department_key: str) -> None:
    if department_key not in allowed_department_report_keys(user):
        raise HTTPException(403, "Sem permissão para este departamento.")


def is_department_reports_admin(user: User) -> bool:
    return user.role.name in DEPARTMENT_REPORT_ADMIN_ROLES


def can_view_department_reports(user: User) -> bool:
    return is_department_reports_admin(user) or user.role.name in DEPARTMENT_REPORT_OPERATIONS_ROLES or has_permission(user, "internal_ops_reports")


def can_create_department_report(user: User, department_key: str) -> bool:
    if is_department_reports_admin(user):
        return True
    return has_permission(user, "internal_ops_create") and department_key in user_department_report_keys(user)


def can_create_department_reports(user: User) -> bool:
    return is_department_reports_admin(user) or (has_permission(user, "internal_ops_create") and bool(user_department_report_keys(user)))


def can_approve_department_reports(user: User) -> bool:
    return is_department_reports_admin(user) or has_permission(user, "internal_ops_approve")


def can_copy_department_reports(user: User) -> bool:
    return is_department_reports_admin(user) or user.role.name in DEPARTMENT_REPORT_OPERATIONS_ROLES or has_permission(user, "internal_ops_reports_copy") or has_permission(user, "internal_ops_reports")


def operations_context(request: Request, db: Session, user: User, kind: str = "", error: str | None = None) -> dict:
    can_view_internal_records = has_permission(user, "internal_ops_view")
    can_view_internal_reports = can_view_department_reports(user)
    records = []
    if can_view_internal_records:
        stmt = select(InternalOperationRecord).order_by(InternalOperationRecord.record_date.desc(), InternalOperationRecord.id.desc())
        if kind:
            stmt = stmt.where(InternalOperationRecord.kind == kind)
        records = db.scalars(stmt.limit(250)).all()
    totals = {}
    for item_kind in OPERATION_KINDS:
        if can_view_internal_records:
            totals[item_kind] = {
                "count": db.scalar(select(func.count(InternalOperationRecord.id)).where(InternalOperationRecord.kind == item_kind)) or 0,
                "amount": db.scalar(select(func.coalesce(func.sum(InternalOperationRecord.amount), 0)).where(InternalOperationRecord.kind == item_kind)) or 0,
            }
        else:
            totals[item_kind] = {"count": 0, "amount": 0}
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
        for option_type in ["company", "fuel_type", "equipment_type", "asset", "location", "payment_method"]
    }
    payment_method_options = [option.name for option in operation_options["payment_method"]] or PAYMENT_METHODS
    return {
        "request": request,
        "user": user,
        "records": records,
        "kinds": OPERATION_KINDS,
        "operation_types": OPERATION_TYPES,
        "payment_methods": payment_method_options,
        "payment_types": PAYMENT_TYPES,
        "statuses": OPERATION_STATUSES,
        "department_report_types": DEPARTMENT_REPORTS,
        "totals": totals,
        "operation_options": operation_options,
        "selected_kind": kind,
        "departments": db.scalars(select(Department).where(Department.is_active == True).order_by(Department.name)).all(),
        "can_view_internal_records": can_view_internal_records,
        "can_view_internal_reports": can_view_internal_reports,
        "can_create_internal_ops": has_permission(user, "internal_ops_create"),
        "can_approve_internal_ops": has_permission(user, "internal_ops_approve"),
        "error": error,
    }


@router.get("")
def operations_home(
    request: Request,
    kind: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
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
    allowed_operation_types = [value for value, _label in OPERATION_TYPES[kind]]
    clean_operation_type = (operation_type or "").strip() or allowed_operation_types[0]
    if clean_operation_type not in set(allowed_operation_types):
        raise HTTPException(400, "Escolha uma operação válida.")
    parsed_department_id = optional_int(department_id, "Departamento")
    department = db.get(Department, parsed_department_id) if parsed_department_id else (user.department if user.department_id else None)
    if parsed_department_id and not department:
        raise HTTPException(400, "O departamento selecionado não existe.")
    parsed_quantity = optional_float(quantity, "Quantidade", 0) or 0
    parsed_amount = optional_float(amount, "Valor", 0) or 0
    parsed_odometer = optional_float(odometer_reading, "Leitura do odómetro") if str(odometer_reading or "").strip() else None
    parsed_meter = optional_float(meter_reading, "Leitura do contador") if str(meter_reading or "").strip() else None
    if parsed_quantity < 0 or parsed_amount < 0:
        raise HTTPException(400, "Quantidade e valor não podem ser negativos.")
    if clean_operation_type in QUANTITY_REQUIRED_TYPES and parsed_quantity <= 0:
        raise HTTPException(400, "A quantidade deve ser superior a zero nesta operação.")
    if clean_operation_type in AMOUNT_REQUIRED_TYPES and parsed_amount <= 0:
        raise HTTPException(400, "O valor deve ser superior a zero nesta operação.")
    if clean_operation_type in PAYMENT_TYPES and not (payment_method or "").strip():
        raise HTTPException(400, "Escolha o método de pagamento desta operação.")
    if parsed_odometer is not None and parsed_odometer < 0:
        raise HTTPException(400, "A leitura do odómetro não pode ser negativa.")
    if parsed_meter is not None and parsed_meter < 0:
        raise HTTPException(400, "A leitura do contador não pode ser negativa.")
    if clean_operation_type in TYPE_REQUIRED_TYPES and not (fuel_type or "").strip():
        raise HTTPException(400, "Informe o tipo/categoria da operação.")
    if clean_operation_type in ASSET_REQUIRED_TYPES:
        if not (asset_name or "").strip():
            raise HTTPException(400, "Informe o ativo, equipamento, local ou contador.")
    if clean_operation_type == "fuel_refuel":
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
        audit_log(db, user, "Criou operação interna", "Operações Internas", record.number, new_value={"kind": kind, "operation_type": clean_operation_type, "amount": parsed_amount}, request=request)
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


def department_reports_context(
    request: Request,
    db: Session,
    user: User,
    department_key: str = "",
    error: str | None = None,
    date_from: str = "",
    date_to: str = "",
    status: str = "",
    responsible: str = "",
    q: str = "",
    prepare_date: str = "",
) -> dict:
    ensure_department_report_storage(db)
    can_create_reports = bool(department_key and can_create_department_report(user, department_key))
    can_view_reports = can_view_department_reports(user)
    allowed_report_keys = allowed_department_report_keys(user)
    visible_report_keys = allowed_report_keys if allowed_report_keys else list(DEPARTMENT_REPORTS)
    start = optional_date_start(date_from)
    end = optional_date_end(date_to)
    reports = []
    if can_view_reports:
        stmt = select(DepartmentDailyReport).order_by(DepartmentDailyReport.report_date.desc(), DepartmentDailyReport.id.desc())
        if department_key:
            stmt = stmt.where(DepartmentDailyReport.department_key == department_key)
        else:
            stmt = stmt.where(DepartmentDailyReport.department_key.in_(allowed_report_keys))
        if start:
            stmt = stmt.where(DepartmentDailyReport.report_date >= start)
        if end:
            stmt = stmt.where(DepartmentDailyReport.report_date <= end)
        if status:
            stmt = stmt.where(DepartmentDailyReport.status == status)
        if responsible:
            stmt = stmt.where(DepartmentDailyReport.prepared_by.ilike(f"%{responsible}%"))
        if q:
            like = f"%{q}%"
            stmt = stmt.where(
                DepartmentDailyReport.activities.ilike(like)
                | DepartmentDailyReport.incidents.ilike(like)
                | DepartmentDailyReport.equipment_status.ilike(like)
                | DepartmentDailyReport.readings.ilike(like)
                | DepartmentDailyReport.pending_actions.ilike(like)
                | DepartmentDailyReport.notes.ilike(like)
            )
        reports = db.scalars(stmt.limit(250)).all()
    totals = {
        key: db.scalar(select(func.count(DepartmentDailyReport.id)).where(DepartmentDailyReport.department_key == key)) or 0
        for key in visible_report_keys
    }
    report_types = {key: DEPARTMENT_REPORTS[key] for key in visible_report_keys}
    prepared_date = (prepare_date or date_from or datetime.now(timezone.utc).strftime("%Y-%m-%d")).strip()
    prepare_start = optional_date_start(prepared_date)
    prepare_end = optional_date_end(prepared_date)
    prepared_reports = []
    if can_view_reports and prepare_start and prepare_end:
        prepared_reports = db.scalars(
            select(DepartmentDailyReport)
            .where(
                DepartmentDailyReport.department_key.in_(allowed_report_keys),
                DepartmentDailyReport.report_date >= prepare_start,
                DepartmentDailyReport.report_date <= prepare_end,
            )
            .order_by(DepartmentDailyReport.department_key, DepartmentDailyReport.id.desc())
        ).all()
    prepared_by_department = {}
    for report in prepared_reports:
        prepared_by_department.setdefault(report.department_key, report)
    prepare_items = []
    for key, item in report_types.items():
        report = prepared_by_department.get(key)
        prepare_items.append(
            {
                "key": key,
                "label": item["short"],
                "report": report,
                "status": report.status if report else "Pending",
                "copy_text": format_department_report_for_daily(report) if report else "",
            }
        )
    missing_labels = [item["label"] for item in prepare_items if not item["report"]]
    bundle_text = format_reports_for_daily_bundle([item["report"] for item in prepare_items if item["report"]], missing_labels)
    return {
        "request": request,
        "user": user,
        "reports": reports,
        "report_types": report_types,
        "statuses": DEPARTMENT_REPORT_STATUSES,
        "selected_department": department_key,
        "filters": {"date_from": date_from, "date_to": date_to, "status": status, "responsible": responsible, "q": q},
        "today": datetime.now(timezone.utc),
        "totals": totals,
        "can_create_internal_ops": can_create_reports,
        "can_approve_internal_ops": can_approve_department_reports(user),
        "can_view_internal_reports": can_view_reports,
        "has_department_report_data_access": bool(allowed_report_keys),
        "can_copy_department_reports": can_copy_department_reports(user),
        "prepare_date": prepared_date,
        "prepare_items": prepare_items,
        "prepare_bundle_text": bundle_text,
        "error": error,
    }


@router.get("/relatorios-departamentais")
def department_reports_home(
    request: Request,
    department: str = "",
    date_from: str = "",
    date_to: str = "",
    status: str = "",
    responsible: str = "",
    q: str = "",
    prepare_date: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    if department and department not in DEPARTMENT_REPORTS:
        raise HTTPException(404)
    allowed_report_keys = allowed_department_report_keys(user)
    if department and allowed_report_keys:
        require_department_report_access(user, department)
    elif department and not allowed_report_keys:
        department = ""
    elif allowed_report_keys:
        department = allowed_report_keys[0]
    return templates.TemplateResponse(
        request,
        "internal_ops/department_reports.html",
        department_reports_context(request, db, user, department, date_from=date_from, date_to=date_to, status=status, responsible=responsible, q=q, prepare_date=prepare_date),
    )


@router.post("/relatorios-departamentais")
def create_department_report(
    request: Request,
    department_key: str = Form(...),
    report_date: str = Form(...),
    period_start: str | None = Form(None),
    period_end: str | None = Form(None),
    shift: str | None = Form(None),
    prepared_by: str | None = Form(None),
    supervisor: str | None = Form(None),
    location: str | None = Form(None),
    team: str | None = Form(None),
    activities: str | None = Form(None),
    incidents: str | None = Form(None),
    equipment_status: str | None = Form(None),
    readings: str | None = Form(None),
    pending_actions: str | None = Form(None),
    notes: str | None = Form(None),
    status: str = Form("Submitted"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    ensure_department_report_storage(db)
    if department_key not in DEPARTMENT_REPORTS:
        raise HTTPException(400, "Escolha um departamento válido para o relatório.")
    if not can_create_department_report(user, department_key):
        raise HTTPException(403, "O seu perfil não possui permissão para criar relatório deste departamento.")
    require_department_report_access(user, department_key)
    if status not in {"Draft", "Submitted"}:
        raise HTTPException(400, "Escolha um estado inicial válido.")
    if not any(str(value or "").strip() for value in [activities, incidents, equipment_status, readings, pending_actions, notes]):
        raise HTTPException(400, "Preencha pelo menos uma secção operacional do relatório.")
    with atomic(db):
        report = DepartmentDailyReport(
            number=next_department_report_number(db, department_key),
            department_key=department_key,
            report_date=parse_report_date(report_date),
            period_start=(period_start or "").strip() or None,
            period_end=(period_end or "").strip() or None,
            shift=(shift or "").strip() or None,
            prepared_by=(prepared_by or "").strip() or user.full_name,
            supervisor=(supervisor or "").strip() or None,
            location=(location or "").strip() or None,
            team=(team or "").strip() or None,
            activities=(activities or "").strip() or None,
            incidents=(incidents or "").strip() or None,
            equipment_status=(equipment_status or "").strip() or None,
            readings=(readings or "").strip() or None,
            pending_actions=(pending_actions or "").strip() or None,
            notes=(notes or "").strip() or None,
            status=status,
            created_by_id=user.id,
        )
        db.add(report)
        db.flush()
        audit_log(db, user, "Criou relatório diário departamental", "Operações Internas", report.number, new_value={"department": department_key, "status": status}, request=request)
    return RedirectResponse(f"/operacoes-internas/relatorios-departamentais?department={department_key}", status_code=303)


@router.get("/relatorios-departamentais/{report_id}/texto")
def department_report_clipboard_text(
    report_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    ensure_department_report_storage(db)
    report = db.get(DepartmentDailyReport, report_id)
    if not report:
        raise HTTPException(404)
    require_department_report_access(user, report.department_key)
    if not can_copy_department_reports(user):
        raise HTTPException(403, "O seu perfil não possui permissão para copiar relatórios departamentais.")
    return PlainTextResponse(format_department_report_for_daily(report))


@router.post("/relatorios-departamentais/{report_id}/validar")
def validate_department_report(
    report_id: int,
    request: Request,
    status: str = Form("Validated"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
):
    ensure_department_report_storage(db)
    if not can_approve_department_reports(user):
        raise HTTPException(403)
    report = db.get(DepartmentDailyReport, report_id)
    if not report:
        raise HTTPException(404)
    require_department_report_access(user, report.department_key)
    if status not in DEPARTMENT_REPORT_STATUSES:
        raise HTTPException(400, "Escolha um estado válido.")
    old_status = report.status
    with atomic(db):
        report.status = status
        if status == "Validated":
            report.approved_by_id = user.id
            report.approved_at = datetime.now(timezone.utc)
        audit_log(db, user, "Validou relatório diário departamental", "Operações Internas", report.number, old_value={"status": old_status}, new_value={"status": status}, request=request)
    return RedirectResponse(f"/operacoes-internas/relatorios-departamentais?department={report.department_key}", status_code=303)
