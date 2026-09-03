from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone
import io
import json
import re
import unicodedata
import zipfile
from xml.etree import ElementTree

from pypdf import PdfReader
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.core import FinancialDailyImport, InternalOperationRecord, ProcurementCase, Requisition


APPROVED_STOCK_STATUSES = {"Approved", "Issued", "Emitido Parcialmente"}
PROCUREMENT_FINANCIAL_STATUSES = {
    "Approved for PO",
    "PO Issued",
    "Received",
    "Completed",
    "Closed",
}


@dataclass(frozen=True)
class MonthWindow:
    key: str
    start: datetime
    end: datetime


def parse_month(month: str | None = None) -> MonthWindow:
    cleaned = str(month or "").strip()
    if cleaned:
        date_value = datetime.strptime(cleaned, "%Y-%m")
    else:
        date_value = datetime.now(timezone.utc)
    start = datetime(date_value.year, date_value.month, 1, tzinfo=timezone.utc)
    if date_value.month == 12:
        next_start = datetime(date_value.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        next_start = datetime(date_value.year, date_value.month + 1, 1, tzinfo=timezone.utc)
    return MonthWindow(key=f"{date_value.year:04d}-{date_value.month:02d}", start=start, end=next_start)


def previous_month(month: MonthWindow) -> MonthWindow:
    year, month_number = [int(part) for part in month.key.split("-")]
    if month_number == 1:
        return parse_month(f"{year - 1}-12")
    return parse_month(f"{year}-{month_number - 1:02d}")


def percent_change(current: float, previous: float) -> float:
    if previous == 0:
        return 100.0 if current > 0 else 0.0
    return round(((current - previous) / previous) * 100, 2)


def _value(value) -> float:
    return round(float(value or 0), 2)


def _stock_requisition_total(db: Session, window: MonthWindow) -> float:
    return _value(
        db.scalar(
            select(func.coalesce(func.sum(Requisition.estimated_value), 0)).where(
                Requisition.req_type.notin_(["NS", "REPOSICAO"]),
                Requisition.status.in_(APPROVED_STOCK_STATUSES),
                Requisition.request_date >= window.start,
                Requisition.request_date < window.end,
            )
        )
    )


def _procurement_total(db: Session, window: MonthWindow) -> float:
    cases = db.scalars(
        select(ProcurementCase)
        .join(ProcurementCase.requisition)
        .where(
            Requisition.req_type.in_(["NS", "REPOSICAO"]),
            ProcurementCase.status.in_(PROCUREMENT_FINANCIAL_STATUSES),
            ProcurementCase.created_at >= window.start,
            ProcurementCase.created_at < window.end,
        )
    ).all()
    return round(sum(_value(case.po_value or case.bid_selected_amount or case.estimated_budget) for case in cases), 2)


def _internal_ops_total(db: Session, window: MonthWindow) -> float:
    return _value(
        db.scalar(
            select(func.coalesce(func.sum(InternalOperationRecord.amount), 0)).where(
                InternalOperationRecord.status != "Cancelled",
                InternalOperationRecord.record_date >= window.start,
                InternalOperationRecord.record_date < window.end,
            )
        )
    )


def _daily_import_totals(db: Session, window: MonthWindow) -> dict[str, float | int]:
    rows = db.scalars(
        select(FinancialDailyImport)
        .where(FinancialDailyImport.report_date >= window.start, FinancialDailyImport.report_date < window.end)
        .order_by(FinancialDailyImport.report_date.desc(), FinancialDailyImport.id.desc())
    ).all()
    return {
        "count": len(rows),
        "trucks_in": sum(int(row.trucks_in or 0) for row in rows),
        "trucks_out": sum(int(row.trucks_out or 0) for row in rows),
        "revenue_amount": round(sum(_value(row.revenue_amount) for row in rows), 2),
        "rows": rows,
    }


def monthly_finance_summary(db: Session, month: str | None = None) -> dict:
    current_window = parse_month(month)
    previous_window = previous_month(current_window)
    current_imports = _daily_import_totals(db, current_window)
    previous_imports = _daily_import_totals(db, previous_window)

    current = {
        "stock_requisitions": _stock_requisition_total(db, current_window),
        "procurement": _procurement_total(db, current_window),
        "internal_ops": _internal_ops_total(db, current_window),
        "daily_revenue": current_imports["revenue_amount"],
        "trucks_in": current_imports["trucks_in"],
        "trucks_out": current_imports["trucks_out"],
        "imports_count": current_imports["count"],
    }
    previous = {
        "stock_requisitions": _stock_requisition_total(db, previous_window),
        "procurement": _procurement_total(db, previous_window),
        "internal_ops": _internal_ops_total(db, previous_window),
        "daily_revenue": previous_imports["revenue_amount"],
        "trucks_in": previous_imports["trucks_in"],
        "trucks_out": previous_imports["trucks_out"],
        "imports_count": previous_imports["count"],
    }
    current["total_spend"] = round(current["stock_requisitions"] + current["procurement"] + current["internal_ops"], 2)
    previous["total_spend"] = round(previous["stock_requisitions"] + previous["procurement"] + previous["internal_ops"], 2)
    usage_ratio = (current["total_spend"] / current["daily_revenue"] * 100) if current["daily_revenue"] else 0
    return {
        "month": current_window.key,
        "previous_month": previous_window.key,
        "current": current,
        "previous": previous,
        "variance": {key: round(current[key] - previous[key], 2) for key in current},
        "percent_change": {key: percent_change(current[key], previous[key]) for key in current},
        "usage_ratio": round(usage_ratio, 2),
        "daily_imports": current_imports["rows"],
    }


def extract_text_from_financial_file(filename: str, content: bytes) -> str:
    lowered = filename.casefold()
    if lowered.endswith(".docx"):
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            xml = archive.read("word/document.xml")
        root = ElementTree.fromstring(xml)
        namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        return "\n".join(node.text or "" for node in root.findall(".//w:t", namespace)).strip()
    if lowered.endswith(".pdf"):
        reader = PdfReader(io.BytesIO(content))
        return "\n".join(page.extract_text() or "" for page in reader.pages).strip()
    raise ValueError("Formato não suportado. Use PDF ou Word (.docx).")


def _nearby_number(pattern: str, text: str) -> int:
    match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
    return int(match.group(1)) if match else 0


def _fold_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    return "".join(char for char in normalized if not unicodedata.combining(char))


def _money_amount(text: str) -> float:
    match = re.search(r"(?:receita|revenue|fatur[aã]?[cç][aã]o|valor)\D{0,40}(\d[\d\s.,]*)", text, flags=re.IGNORECASE)
    if not match:
        return 0
    raw = match.group(1).replace(" ", "")
    if "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".")
    else:
        raw = raw.replace(",", ".")
    try:
        return round(float(raw), 2)
    except ValueError:
        return 0


def extract_financial_metrics(text: str) -> dict[str, float | int]:
    normalized = _fold_text(" ".join(text.split()))
    return {
        "trucks_in": _nearby_number(r"(?:caminhoes|camioes|trucks?)\D{0,35}(?:entraram|entrad[ao]s?|in)\D{0,20}(\d+)", normalized),
        "trucks_out": _nearby_number(r"(?:caminhoes|camioes|trucks?)\D{0,35}(?:sairam|said[ao]s?|out)\D{0,20}(\d+)", normalized),
        "revenue_amount": _money_amount(normalized),
    }


def metrics_as_json(metrics: dict[str, float | int]) -> str:
    return json.dumps(metrics, ensure_ascii=False, sort_keys=True)
