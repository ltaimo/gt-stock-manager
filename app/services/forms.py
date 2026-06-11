import math
import re

from email_validator import EmailNotValidError, validate_email
from fastapi import HTTPException


FIELD_LABELS = {
    "action_type": "Acção",
    "approved_quantity": "Quantidade aprovada",
    "category_id": "Categoria",
    "confirmation": "Confirmação",
    "date_from": "Data inicial",
    "date_to": "Data final",
    "department_id": "Departamento",
    "decision": "Decisão",
    "email": "Email",
    "file": "Ficheiro",
    "full_name": "Nome completo",
    "item_id": "Item",
    "minimum_stock": "Stock mínimo",
    "name": "Nome",
    "operational_manager_id": "Gestor operacional",
    "password": "Senha",
    "product_id": "Produto",
    "quantity": "Quantidade",
    "requesting_user_id": "Requisitante",
    "role_id": "Perfil",
    "security_code": "Código de segurança",
    "username": "Utilizador",
}


def field_label(field_name: str) -> str:
    return FIELD_LABELS.get(field_name, field_name.replace("_", " ").capitalize())


def optional_int(value: str | None, field_name: str) -> int | None:
    cleaned = str(value or "").strip()
    if not cleaned:
        return None
    try:
        return int(cleaned)
    except ValueError as exc:
        raise HTTPException(400, f"{field_name} inválido.") from exc


def required_int(value: str | None, field_name: str) -> int:
    parsed = optional_int(value, field_name)
    if parsed is None:
        raise HTTPException(400, f"{field_name} é obrigatório.")
    return parsed


def optional_float(value: str | None, field_name: str, default: float | None = None) -> float | None:
    cleaned = str(value or "").strip().replace(",", ".")
    if not cleaned:
        return default
    try:
        parsed = float(cleaned)
    except ValueError as exc:
        raise HTTPException(400, f"{field_name} deve ser um número válido.") from exc
    if not math.isfinite(parsed):
        raise HTTPException(400, f"{field_name} deve ser um número finito.")
    return parsed


def required_float(value: str | None, field_name: str) -> float:
    parsed = optional_float(value, field_name)
    if parsed is None:
        raise HTTPException(400, f"{field_name} é obrigatória.")
    return parsed


def required_text(value: str | None, field_name: str, max_length: int | None = None) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise HTTPException(400, f"{field_name} não pode ficar vazio.")
    if max_length and len(cleaned) > max_length:
        raise HTTPException(400, f"{field_name} não pode exceder {max_length} caracteres.")
    return cleaned


def optional_email(value: str | None) -> str | None:
    cleaned = str(value or "").strip()
    if not cleaned:
        return None
    if len(cleaned) > 160:
        raise HTTPException(400, "Email não pode exceder 160 caracteres.")
    if re.fullmatch(r"[^@\s]+@[^@\s]+\.local", cleaned, flags=re.IGNORECASE):
        return cleaned.lower()
    try:
        return validate_email(cleaned, check_deliverability=False).normalized
    except EmailNotValidError as exc:
        raise HTTPException(400, "Informe um email válido.") from exc


def parse_int_list(values: list[str], field_name: str) -> list[int]:
    if not values:
        raise HTTPException(400, f"Adicione pelo menos um {field_name.lower()}.")
    return [required_int(value, field_name) for value in values]


def parse_float_list(values: list[str], field_name: str) -> list[float]:
    if not values:
        raise HTTPException(400, f"Adicione pelo menos uma {field_name.lower()}.")
    return [required_float(value, field_name) for value in values]
