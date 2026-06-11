from fastapi import HTTPException


def optional_int(value: str | None, field_name: str) -> int | None:
    cleaned = (value or "").strip()
    if not cleaned:
        return None
    try:
        return int(cleaned)
    except ValueError as exc:
        raise HTTPException(400, f"{field_name} inválido.") from exc
