from datetime import datetime
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.models.core import ProcurementCase, User


def procurement_form_to_pdf(case: ProcurementCase, generated_by: User | None = None) -> bytes:
    stream = BytesIO()
    doc = SimpleDocTemplate(stream, pagesize=A4, rightMargin=1.2 * cm, leftMargin=1.2 * cm, topMargin=1 * cm, bottomMargin=1 * cm)
    styles = getSampleStyleSheet()
    story = [
        Paragraph("<b>GT - Formulário de Requisição Non-Stock</b>", styles["Title"]),
        Paragraph(f"Nº: {case.requisition.number}", styles["Heading2"]),
        Spacer(1, 0.4 * cm),
    ]
    rows = [
        ["Requisitante", case.requisition.requesting_user.full_name],
        ["Departamento", case.requisition.department.name if case.requisition.department else ""],
        ["Data", case.requisition.request_date.strftime("%d/%m/%Y")],
        ["Prioridade", case.priority],
        ["Centro de custo", case.cost_center or ""],
        ["Budget estimado", f"{float(case.estimated_budget or 0):.2f} MZN"],
        ["Budget confirmado", "Sim" if case.budget_confirmed else "Não" if case.budget_confirmed is False else "Pendente"],
        ["Modalidade", case.modality or ""],
        ["Aprovação final", case.approval_route or ""],
        ["Estado", case.status],
        ["Fornecedor selecionado", case.selected_supplier or ""],
        ["PO", case.po_number or ""],
    ]
    table = Table(rows, colWidths=[5 * cm, 12 * cm])
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F5BF00")),
                ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#DDDDDD")),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("PADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    story.extend([table, Spacer(1, 0.5 * cm)])
    story.append(Paragraph("<b>Descrição / escopo</b>", styles["Heading3"]))
    story.append(Paragraph((case.description or "").replace("\n", "<br/>"), styles["Normal"]))
    if case.justification:
        story.extend([Spacer(1, 0.3 * cm), Paragraph("<b>Justificação</b>", styles["Heading3"]), Paragraph(case.justification.replace("\n", "<br/>"), styles["Normal"])])
    if case.comments:
        story.extend([Spacer(1, 0.3 * cm), Paragraph("<b>Comentários</b>", styles["Heading3"]), Paragraph(case.comments.replace("\n", "<br/>"), styles["Normal"])])
    story.extend(
        [
            Spacer(1, 0.7 * cm),
            Paragraph(f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')}", styles["Normal"]),
            Paragraph(f"Gerado por: {generated_by.full_name if generated_by else 'Sistema'}", styles["Normal"]),
        ]
    )
    doc.build(story)
    return stream.getvalue()
