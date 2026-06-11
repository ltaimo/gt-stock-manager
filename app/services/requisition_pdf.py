from datetime import datetime
import getpass
from io import BytesIO
import socket

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Image, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.config import get_settings
from app.models.core import Requisition, User


GOLD = colors.HexColor("#F5BF00")
DARK_GREY = colors.HexColor("#595959")
TEXT = colors.HexColor("#222222")
LINE = colors.HexColor("#FFFFFF")


def fmt_date(value: datetime | None) -> str:
    if not value:
        return ""
    return value.strftime("%d/%m/%Y")


def fmt_qty(value) -> str:
    number = float(value or 0)
    return f"{number:g}"


def box_table(rows: list[list], widths: list[float]) -> Table:
    table = Table(rows, colWidths=widths)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), GOLD),
                ("TEXTCOLOR", (0, 0), (-1, -1), TEXT),
                ("FONTNAME", (0, 0), (-1, -1), "Courier"),
                ("FONTNAME", (0, 0), (0, -1), "Courier-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    return table


def host_footer_lines(req: Requisition, generated_by: User | None, client_ip: str | None) -> list[str]:
    user_label = "Sistema"
    if generated_by:
        user_label = f"{generated_by.full_name} ({generated_by.username})"
    return [
        f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}",
        f"Gerado por: {user_label}",
        f"IP de acesso: {client_ip or 'N/D'}",
        f"Servidor: {socket.gethostname()}",
        f"Utilizador do host: {getpass.getuser()}",
        f"Requisição: {req.number}",
    ]


def requisition_to_pdf(req: Requisition, generated_by: User | None = None, client_ip: str | None = None) -> bytes:
    settings = get_settings()
    stream = BytesIO()
    doc = SimpleDocTemplate(
        stream,
        pagesize=A4,
        rightMargin=1.1 * cm,
        leftMargin=1.1 * cm,
        topMargin=0.6 * cm,
        bottomMargin=0.7 * cm,
    )
    styles = getSampleStyleSheet()
    normal = ParagraphStyle("ReqNormal", parent=styles["Normal"], fontName="Courier", fontSize=8, leading=9.5)
    title = ParagraphStyle("ReqTitle", parent=styles["Title"], fontName="Courier-Bold", fontSize=14, leading=16, alignment=1)
    small = ParagraphStyle("ReqSmall", parent=normal, fontSize=7, leading=8.5)

    story = []

    if settings.logo_path.exists():
        logo = Image(str(settings.logo_path), width=6.7 * cm, height=2.5 * cm, kind="proportional")
    else:
        logo = Paragraph("<b>Gestão de<br/>Terminais, SA</b>", styles["Title"])

    number = req.number.replace("REQ-", "").replace("-", "/")
    header_box = box_table(
        [
            [Paragraph("REQUISIÇÃO", title)],
            [Paragraph(f"<b>REQUISIÇÃO nº:</b> {number}", normal)],
            [Paragraph(f"<b>Data:</b> {fmt_date(req.request_date)}", normal)],
        ],
        [9.8 * cm],
    )
    header = Table([[logo, header_box]], colWidths=[9.3 * cm, 9.8 * cm])
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.extend([header, Spacer(1, 1.7 * cm)])

    company_box = box_table(
        [
            ["Localização:", "EN4 - KM 5,5 - R.G - MATOLA"],
            ["E-mail:", "info@gtsa.co.mz"],
            ["Telefone:", "844231830"],
        ],
        [3.1 * cm, 4.4 * cm],
    )
    info_box = box_table(
        [
            ["Por Autorizar:", req.authorization_person or "Gestor de Estoque"],
            ["Requisitante", req.requesting_user.full_name],
            ["Departamento", req.department.name if req.department else ""],
            ["Gestor Operacional", req.operational_manager or ""],
            ["Estado", req.status],
        ],
        [4.5 * cm, 5.7 * cm],
    )
    info = Table([[company_box, "", info_box]], colWidths=[7.5 * cm, 1.4 * cm, 10.2 * cm])
    info.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP")]))
    story.extend([info, Spacer(1, 0.8 * cm)])

    headers = ["Código", "Item", "Pedido", "Aprov.", "Rejeit.", "Estado", "Obs"]
    rows = [headers]
    for item in req.items:
        item_obs = item.review_observation or item.observation or ""
        rows.append(
            [
                item.product.code,
                Paragraph(item.product.name, normal),
                fmt_qty(item.quantity_requested),
                fmt_qty(item.quantity_issued),
                fmt_qty(item.quantity_rejected),
                item.review_status,
                Paragraph(item_obs, small),
            ]
        )

    table = Table(
        rows,
        colWidths=[2.1 * cm, 4.4 * cm, 1.4 * cm, 1.4 * cm, 1.4 * cm, 2.1 * cm, 6.3 * cm],
        repeatRows=1,
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), DARK_GREY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("BACKGROUND", (0, 1), (-1, -1), GOLD),
                ("TEXTCOLOR", (0, 1), (-1, -1), TEXT),
                ("FONTNAME", (0, 0), (-1, 0), "Courier-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "Courier"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("ALIGN", (2, 1), (5, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("GRID", (0, 0), (-1, -1), 0.5, LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(table)

    if req.notes:
        story.extend([Spacer(1, 0.35 * cm), box_table([["Observações:", Paragraph(req.notes, normal)]], [3.2 * cm, 15.9 * cm])])

    footer_lines = host_footer_lines(req, generated_by, client_ip)

    def draw_footer(canvas, _doc):
        canvas.saveState()
        canvas.setStrokeColor(colors.HexColor("#DDDDDD"))
        canvas.setLineWidth(0.4)
        canvas.line(1.1 * cm, 0.55 * cm, A4[0] - 1.1 * cm, 0.55 * cm)
        canvas.setFillColor(colors.HexColor("#666666"))
        canvas.setFont("Courier", 6.5)
        canvas.drawString(1.1 * cm, 0.34 * cm, " | ".join(footer_lines[:3]))
        canvas.drawString(1.1 * cm, 0.18 * cm, " | ".join(footer_lines[3:]))
        canvas.restoreState()

    doc.build(story, onFirstPage=draw_footer, onLaterPages=draw_footer)
    return stream.getvalue()
