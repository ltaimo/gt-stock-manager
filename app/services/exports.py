import csv
from datetime import datetime
from io import BytesIO, StringIO
from pathlib import Path
from typing import Iterable

from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet

from app.config import get_settings


def rows_to_csv(headers: list[str], rows: Iterable[Iterable]) -> str:
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(headers)
    writer.writerows(rows)
    return output.getvalue()


def rows_to_xlsx(headers: list[str], rows: Iterable[Iterable], title: str = "Relatório") -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = title[:31]
    ws.append(["Sistema de Gestão de Stock", "Gestão de Terminais, SA"])
    ws.append([title, f"Gerado em {datetime.now().strftime('%Y-%m-%d %H:%M')}"])
    ws.append([])
    ws.append(headers)
    for row in rows:
        ws.append(list(row))
    for cell in ws[4]:
        cell.font = cell.font.copy(bold=True)
    for column in ws.columns:
        width = min(max(len(str(cell.value or "")) for cell in column) + 2, 42)
        ws.column_dimensions[column[0].column_letter].width = width
    stream = BytesIO()
    wb.save(stream)
    return stream.getvalue()


def rows_to_pdf(headers: list[str], rows: Iterable[Iterable], title: str = "Relatório", generated_by: str = "") -> bytes:
    settings = get_settings()
    stream = BytesIO()
    doc = SimpleDocTemplate(
        stream,
        pagesize=landscape(A4),
        rightMargin=1 * cm,
        leftMargin=1 * cm,
        topMargin=1 * cm,
        bottomMargin=1.4 * cm,
    )
    styles = getSampleStyleSheet()
    story = []
    header_cells = []
    if settings.logo_path.exists():
        header_cells.append(Image(str(settings.logo_path), width=3.2 * cm, height=1.5 * cm, kind="proportional"))
    else:
        header_cells.append(Paragraph("<b>GT</b>", styles["Title"]))
    meta = f"{settings.app_subtitle}<br/>Gerado em {datetime.now().strftime('%Y-%m-%d %H:%M')}"
    if generated_by:
        meta += f"<br/>Gerado por: {generated_by}"
    header_cells.append(Paragraph(f"<b>{title}</b><br/>{meta}", styles["Normal"]))
    header_table = Table([header_cells], colWidths=[4 * cm, 22 * cm])
    header_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    story.extend([header_table, Spacer(1, 0.35 * cm)])

    data = [headers] + [[str(value or "") for value in row] for row in rows]
    table = Table(data, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#D6A619")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#2D3033")),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#E3E6EA")),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F7F8FA")]),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 0.4 * cm))
    story.append(Paragraph("<font color='#8A9098' size='8'>Designed by Layton Taimo</font>", styles["Normal"]))
    doc.build(story)
    return stream.getvalue()
