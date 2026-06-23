import csv
from datetime import datetime
from io import BytesIO, StringIO
from typing import Iterable

from openpyxl import Workbook
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
from xml.sax.saxutils import escape

from app.services.pdf_branding import INK, brand_header, branded_footer, branded_styles, data_table, generated_meta


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
    stream = BytesIO()
    doc = SimpleDocTemplate(
        stream,
        pagesize=landscape(A4),
        rightMargin=1 * cm,
        leftMargin=1 * cm,
        topMargin=1 * cm,
        bottomMargin=1.4 * cm,
    )
    story = [brand_header(title, meta=generated_meta(generated_by), width=26 * cm), Spacer(1, 0.35 * cm)]
    styles, _regular, bold = branded_styles()
    cell_style = styles["GTNormalSmall"]
    header_style = cell_style.clone("GTReportHeader")
    header_style.fontName = bold
    header_style.textColor = INK
    rows_list = [[Paragraph(escape(str(value or "")), header_style) for value in headers]]
    rows_list.extend([[Paragraph(escape(str(value or "")), cell_style) for value in row] for row in rows])
    col_count = max(len(headers), 1)
    weights = []
    for header in headers:
        lowered = header.lower()
        if any(term in lowered for term in ("produto", "descr", "item", "observ", "coment", "fornecedor")):
            weights.append(2.2)
        else:
            weights.append(1.0)
    total_weight = sum(weights) or col_count
    story.append(data_table(rows_list, col_widths=[(26 * cm) * weight / total_weight for weight in weights]))
    doc.build(
        story,
        onFirstPage=lambda canvas, d: branded_footer(canvas, d, generated_by),
        onLaterPages=lambda canvas, d: branded_footer(canvas, d, generated_by),
    )
    return stream.getvalue()
