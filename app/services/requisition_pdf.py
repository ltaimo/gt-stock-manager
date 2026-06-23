from datetime import datetime
from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from app.models.core import Requisition, User
from app.services.pdf_branding import (
    brand_header,
    branded_footer,
    branded_styles,
    data_table,
    generated_meta,
    label_value_table,
)


def fmt_date(value: datetime | None) -> str:
    if not value:
        return ""
    return value.strftime("%d/%m/%Y")


def fmt_qty(value) -> str:
    number = float(value or 0)
    return f"{number:g}"


def requisition_to_pdf(req: Requisition, generated_by: User | None = None, client_ip: str | None = None) -> bytes:
    stream = BytesIO()
    doc = SimpleDocTemplate(
        stream,
        pagesize=A4,
        rightMargin=1.1 * cm,
        leftMargin=1.1 * cm,
        topMargin=0.8 * cm,
        bottomMargin=1.2 * cm,
    )
    styles, _regular, _bold = branded_styles()
    normal = styles["Normal"]
    small = styles["GTNormalSmall"]
    generated_by_name = generated_by.full_name if generated_by else "Sistema"
    number = req.number.replace("REQ-", "").replace("-", "/")

    story = [
        brand_header(
            "REQUISIÇÃO",
            subtitle=f"Requisição nº: {number}",
            meta=[f"Data: {fmt_date(req.request_date)}", *generated_meta(generated_by_name)],
        ),
        Spacer(1, 0.35 * cm),
    ]

    company_rows = [
        ["Localização", "EN4 - KM 5,5 - R.G - MATOLA"],
        ["E-mail", "info@gtsa.co.mz"],
        ["Telefone", "844231830"],
    ]
    request_rows = [
        ["Por autorizar", req.authorization_person or "Definido pela matriz de aprovações"],
        ["Valor estimado", f"{float(req.estimated_value or 0):.2f} MZN"],
        ["Requisitante", req.requesting_user.full_name],
        ["Departamento", req.department.name if req.department else ""],
        ["Gestor Operacional", req.operational_manager or ""],
        ["Estado", req.status],
    ]
    story.extend(
        [
            label_value_table(company_rows, [3.1 * cm, 6.0 * cm]),
            Spacer(1, 0.2 * cm),
            label_value_table(request_rows, [4.0 * cm, 12.4 * cm]),
            Spacer(1, 0.35 * cm),
        ]
    )

    rows = [["Código", "Item", "Pedido", "Aprov.", "Rejeit.", "Estado", "Obs."]]
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
    story.append(
        data_table(
            rows,
            col_widths=[2.0 * cm, 4.6 * cm, 1.4 * cm, 1.4 * cm, 1.4 * cm, 2.0 * cm, 4.3 * cm],
        )
    )

    if req.notes:
        story.extend([Spacer(1, 0.35 * cm), label_value_table([["Observações", Paragraph(req.notes, normal)]], [3.2 * cm, 13.9 * cm])])
    if client_ip:
        story.extend([Spacer(1, 0.2 * cm), Paragraph(f"IP de acesso: {client_ip}", small)])

    doc.build(story, onFirstPage=lambda c, d: branded_footer(c, d, generated_by_name), onLaterPages=lambda c, d: branded_footer(c, d, generated_by_name))
    return stream.getvalue()
