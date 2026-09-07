from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.core import FinancialDailyImport, User
from app.routers.common import templates
from app.security import require_permission
from app.services.audit import audit_log
from app.services.finance import (
    extract_financial_metrics,
    extract_text_from_financial_file,
    finance_report_rows,
    metrics_as_json,
    monthly_finance_summary,
)
from app.services.exports import rows_to_docx, rows_to_pdf, rows_to_xlsx
from app.services.transactions import atomic

router = APIRouter(prefix="/financeiro", tags=["financeiro"])


def parse_financial_report_date(value: str | None) -> datetime:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise HTTPException(400, "Informe a data do relatório financeiro.")
    try:
        return datetime.fromisoformat(cleaned).replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise HTTPException(400, "Informe uma data válida no formato AAAA-MM-DD.") from exc


@router.get("")
def finance_home(
    request: Request,
    month: str = "",
    error: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("finance_view")),
):
    try:
        summary = monthly_finance_summary(db, month or None)
    except ValueError as exc:
        raise HTTPException(400, "Informe um mês válido no formato AAAA-MM.") from exc
    return templates.TemplateResponse(
        request,
        "finance/index.html",
        {
            "request": request,
            "user": user,
            "summary": summary,
            "month": summary["month"],
            "error": error,
        },
    )


@router.get("/relatorio")
def finance_final_report(
    request: Request,
    month: str = "",
    export: str = "",
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("finance_view")),
):
    try:
        summary = monthly_finance_summary(db, month or None)
    except ValueError as exc:
        raise HTTPException(400, "Informe um mês válido no formato AAAA-MM.") from exc
    headers = ["Indicador", "Mês atual", "Diferença", "Variação %"]
    rows = finance_report_rows(summary)
    title = f"Relatório financeiro consolidado - {summary['month']}"
    filename = f"relatorio-financeiro-{summary['month']}"
    if export == "xlsx":
        return Response(rows_to_xlsx(headers, rows, title), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f'attachment; filename="{filename}.xlsx"'})
    if export == "docx":
        return Response(rows_to_docx(headers, rows, title, user.full_name), media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", headers={"Content-Disposition": f'attachment; filename="{filename}.docx"'})
    return Response(rows_to_pdf(headers, rows, title, user.full_name), media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{filename}.pdf"'})


@router.get("/importacoes/{import_id}/download")
def download_financial_daily_report(
    import_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("finance_view")),
):
    imported = db.get(FinancialDailyImport, import_id)
    if not imported:
        raise HTTPException(404)
    return Response(
        imported.content,
        media_type=imported.content_type or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{imported.original_filename}"'},
    )


@router.post("/importacoes")
async def upload_financial_daily_report(
    request: Request,
    report_date: str = Form(...),
    notes: str | None = Form(None),
    document: UploadFile = File(...),
    db: Session = Depends(get_db),
    user: User = Depends(require_permission("finance_import")),
):
    parsed_date = parse_financial_report_date(report_date)
    filename = document.filename or "relatorio-financeiro"
    content = await document.read()
    if not content:
        return RedirectResponse(f"/financeiro?error={quote('O ficheiro carregado está vazio.')}", status_code=303)
    try:
        extracted_text = extract_text_from_financial_file(filename, content)
    except (ValueError, KeyError) as exc:
        return RedirectResponse(f"/financeiro?error={quote(str(exc))}", status_code=303)
    metrics = extract_financial_metrics(extracted_text)
    period_month = f"{parsed_date.year:04d}-{parsed_date.month:02d}"
    with atomic(db):
        imported = FinancialDailyImport(
            report_date=parsed_date,
            period_month=period_month,
            original_filename=filename,
            content_type=document.content_type or "application/octet-stream",
            content=content,
            extracted_text=extracted_text[:20000],
            extracted_metrics=metrics_as_json(metrics),
            trucks_in=int(metrics["trucks_in"]),
            trucks_out=int(metrics["trucks_out"]),
            revenue_amount=float(metrics["revenue_amount"]),
            notes=(notes or "").strip() or None,
            uploaded_by_id=user.id,
        )
        db.add(imported)
        db.flush()
        audit_log(
            db,
            user,
            "Importou relatório financeiro diário",
            "Financeiro",
            str(imported.id),
            new_value={"date": report_date, "filename": filename, "metrics": metrics},
            request=request,
        )
    return RedirectResponse(f"/financeiro?month={period_month}", status_code=303)
