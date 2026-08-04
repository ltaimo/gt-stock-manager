from __future__ import annotations

import re
import unicodedata

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.core import AccessRequest, User


def _slug_token(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]", "", ascii_value.lower())


def username_from_full_name(full_name: str) -> str:
    tokens = [_slug_token(part) for part in str(full_name or "").split()]
    tokens = [token for token in tokens if token]
    if not tokens:
        return "utilizador"
    if len(tokens) == 1:
        return tokens[0][:80]
    return f"{tokens[0][0]}{tokens[-1]}"[:80]


def unique_username_from_full_name(db: Session, full_name: str, *, access_request_id: int | None = None) -> str:
    base = username_from_full_name(full_name)
    existing_users = set(db.scalars(select(User.username)).all())
    pending_suggestions = set(
        db.scalars(
            select(AccessRequest.username_suggestion).where(
                AccessRequest.status == "Pending",
                AccessRequest.id != access_request_id,
            )
        ).all()
    )
    unavailable = {value.casefold() for value in existing_users | pending_suggestions if value}
    candidate = base
    suffix = 2
    while candidate.casefold() in unavailable:
        suffix_text = str(suffix)
        candidate = f"{base[:80 - len(suffix_text)]}{suffix_text}"
        suffix += 1
    return candidate
