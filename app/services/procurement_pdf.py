from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from app.models.core import ProcurementCase, User
from app.services.pdf_branding import brand_header, branded_footer, branded_styles, data_table, generated_meta, label_value_table


def procurement_form_to_pdf(case: ProcurementCase, generated_by: User | None = None) -> bytes:
    stream = BytesIO()
    doc = SimpleDocTemplate(
        stream,
        pagesize=A4,
        rightMargin=1.2 * cm,
        leftMargin=1.2 * cm,
        topMargin=1 * cm,
        bottomMargin=1.4 * cm,
    )
    styles, _regular, _bold = branded_styles()
    generated_name = generated_by.full_name if generated_by else "Sistema"
    is_replenishment = case.requisition.req_type == "REPOSICAO"
    story = [
        brand_header(
            "Pedido de Reposição de Stock" if is_replenishment else "Formulário de Requisição Non-Stock",
            subtitle=f"Nº: {case.requisition.number}",
            meta=generated_meta(generated_name),
        ),
        Spacer(1, 0.4 * cm),
    ]
    rows = [
        ["Requisitante", case.requisition.requesting_user.full_name],
        ["Departamento", case.requisition.department.name if case.requisition.department else ""],
        ["Data", case.requisition.request_date.strftime("%d/%m/%Y")],
        ["Tipo", case.item_type or "Bem"],
        ["Prioridade", case.priority],
        ["Centro de custo", case.cost_center or ""],
        ["Budget estimado", f"{float(case.estimated_budget or 0):.2f} MZN"],
        ["Valor PO/cotação", f"{float(case.po_value or 0):.2f} MZN" if case.po_value else "Pendente"],
        ["Budget confirmado", "Sim" if case.budget_confirmed else "Não" if case.budget_confirmed is False else "Pendente"],
        ["Modalidade", case.modality or ""],
        ["Aprovação final", case.approval_route or ""],
        ["Estado", case.status],
        ["Fornecedor selecionado", case.selected_supplier or ""],
        ["PO", case.po_number or ""],
    ]
    story.extend([label_value_table(rows, [5 * cm, 12 * cm]), Spacer(1, 0.5 * cm)])
    if is_replenishment:
        item_rows = [["Código / produto", "Qtd.", "Preço unit.", "Total", "Recebido"]]
        for item in case.requisition.items:
            item_rows.append(
                [
                    Paragraph(f"<b>{item.product.code}</b><br/>{item.product.name}", styles["Normal"]),
                    f"{float(item.quantity_requested or 0):g} {item.product.unit}",
                    f"{float(item.estimated_unit_price or 0):.2f}",
                    f"{float(item.quantity_requested or 0) * float(item.estimated_unit_price or 0):.2f}",
                    f"{float(item.quantity_received or 0):g}",
                ]
            )
        story.extend(
            [
                Paragraph("<b>Produtos a adquirir</b>", styles["Heading3"]),
                data_table(item_rows, col_widths=[7.4 * cm, 2.2 * cm, 2.6 * cm, 2.6 * cm, 2.2 * cm]),
                Spacer(1, 0.5 * cm),
            ]
        )
    story.append(Paragraph("<b>Descrição / escopo</b>", styles["Heading3"]))
    story.append(Paragraph((case.description or "").replace("\n", "<br/>"), styles["Normal"]))
    if case.justification:
        story.extend([Spacer(1, 0.3 * cm), Paragraph("<b>Justificação</b>", styles["Heading3"]), Paragraph(case.justification.replace("\n", "<br/>"), styles["Normal"])])
    if case.comments:
        story.extend([Spacer(1, 0.3 * cm), Paragraph("<b>Comentários</b>", styles["Heading3"]), Paragraph(case.comments.replace("\n", "<br/>"), styles["Normal"])])
    doc.build(
        story,
        onFirstPage=lambda canvas, d: branded_footer(canvas, d, generated_name),
        onLaterPages=lambda canvas, d: branded_footer(canvas, d, generated_name),
    )
    return stream.getvalue()
