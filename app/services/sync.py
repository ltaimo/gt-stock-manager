from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, DateTime, Integer, Numeric, insert, select
from sqlalchemy.engine import Connection

from app.config import get_settings
from app.database import Base, engine


EXCLUDED_TABLES = {"sqlite_sequence"}


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _coerce_value(column, value: Any) -> Any:
    if value is None:
        return None
    column_type = column.type
    if isinstance(column_type, DateTime):
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
    if isinstance(column_type, Numeric):
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))
    if isinstance(column_type, Boolean):
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "sim"}
        return bool(value)
    if isinstance(column_type, Integer):
        return int(value)
    return value


def create_snapshot() -> dict[str, Any]:
    tables = []
    with engine.connect() as connection:
        for table in Base.metadata.sorted_tables:
            if table.name in EXCLUDED_TABLES:
                continue
            stmt = select(table)
            primary_keys = list(table.primary_key.columns)
            if primary_keys:
                stmt = stmt.order_by(*primary_keys)
            rows = []
            for row in connection.execute(stmt).mappings().all():
                rows.append({key: _json_value(value) for key, value in row.items()})
            tables.append(
                {
                    "name": table.name,
                    "columns": [column.name for column in table.columns],
                    "rows": rows,
                    "count": len(rows),
                }
            )
    return {
        "format": "gtims-full-snapshot-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "app_version": get_settings().app_version,
        "tables": tables,
    }


def _payload_tables(payload: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    if payload.get("format") != "gtims-full-snapshot-v1":
        raise ValueError("Formato de snapshot invalido.")
    tables = {}
    for table_payload in payload.get("tables", []):
        name = table_payload.get("name")
        if not name:
            raise ValueError("Snapshot contem uma tabela sem nome.")
        tables[name] = table_payload.get("rows", [])
    return tables


def _delete_existing_rows(connection: Connection, table_names: set[str]) -> None:
    for table in reversed(Base.metadata.sorted_tables):
        if table.name in table_names:
            connection.execute(table.delete())


def _insert_snapshot_rows(connection: Connection, tables: dict[str, list[dict[str, Any]]]) -> dict[str, int]:
    known_tables = {table.name: table for table in Base.metadata.sorted_tables}
    unknown = sorted(set(tables) - set(known_tables))
    if unknown:
        raise ValueError(f"Snapshot contem tabelas desconhecidas: {', '.join(unknown)}")

    counts = {}
    for table in Base.metadata.sorted_tables:
        rows = tables.get(table.name)
        if rows is None:
            continue
        columns = {column.name: column for column in table.columns}
        prepared_rows = []
        for row in rows:
            prepared_rows.append(
                {
                    column_name: _coerce_value(columns[column_name], value)
                    for column_name, value in row.items()
                    if column_name in columns
                }
            )
        if prepared_rows:
            connection.execute(insert(table), prepared_rows)
        counts[table.name] = len(prepared_rows)
    return counts


def apply_snapshot(payload: dict[str, Any]) -> dict[str, int]:
    tables = _payload_tables(payload)
    with engine.begin() as connection:
        _delete_existing_rows(connection, set(tables))
        return _insert_snapshot_rows(connection, tables)


def push_snapshot_to_target(target_url: str, token: str, timeout: int = 45) -> dict[str, Any]:
    if not target_url:
        raise ValueError("SYNC_TARGET_URL nao esta configurado.")
    if not token:
        raise ValueError("SYNC_TOKEN nao esta configurado.")

    snapshot = create_snapshot()
    data = json.dumps(snapshot, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        f"{target_url.rstrip('/')}/api/sync/mirror",
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "X-GTIMS-Sync-Token": token,
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
            return json.loads(body) if body else {"status": "ok"}
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Falha HTTP {exc.code} ao sincronizar: {detail}") from exc


def fetch_snapshot_from_target(target_url: str, token: str, timeout: int = 45) -> dict[str, Any]:
    if not target_url:
        raise ValueError("SYNC_TARGET_URL nao esta configurado.")
    if not token:
        raise ValueError("SYNC_TOKEN nao esta configurado.")

    request = urllib.request.Request(
        f"{target_url.rstrip('/')}/api/sync/snapshot",
        method="GET",
        headers={"X-GTIMS-Sync-Token": token},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Falha HTTP {exc.code} ao obter snapshot: {detail}") from exc
