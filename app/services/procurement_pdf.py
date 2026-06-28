from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from app.i18n import language_for, localized_name, translate_text, translate_value
from app.models.core import ProcurementCase, User
from app.services.pdf_branding import brand_header, branded_footer, branded_styles, data_table, generated_meta, label_value_table


def procurement_form_to_pdf(case: ProcurementCase, generated_by: User | None = None) -> bytes:
    language = language_for(generated_by)
    text = lambda value: translate_text(value, language)
    value = lambda item: translate_value(item, language)
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
    generated_name = generated_by.full_name if generated_by else text("Sistema")
    is_replenishment = case.requisition.req_type == "REPOSICAO"
    story = [
        brand_header(
            text("Pedido de Reposição de Stock") if is_replenishment else text("Formulário de Requisição Non-Stock"),
            subtitle=f"{text('Nº')}: {case.requisition.number}",
            meta=generated_meta(generated_name, language),
        ),
        Spacer(1, 0.4 * cm),
    ]
    rows = [
        [text("Requisitante"), case.requisition.requesting_user.full_name],
        [text("Departamento"), case.requisition.department.name if case.requisition.department else ""],
        [text("Data"), case.requisition.request_date.strftime("%d/%m/%Y")],
        [text("Tipo"), value(case.item_type or "Bem")],
        [text("Prioridade"), value(case.priority)],
        [text("Centro de custo"), case.cost_center or ""],
        [text("Budget estimado"), f"{float(case.estimated_budget or 0):.2f} MZN"],
        [text("Valor PO/cotação"), f"{float(case.po_value or 0):.2f} MZN" if case.po_value else value("Pending")],
        [text("Budget confirmado"), text("Sim") if case.budget_confirmed else text("Não") if case.budget_confirmed is False else value("Pending")],
        [text("Modalidade"), case.modality or ""],
        [text("Aprovação final"), case.approval_route or ""],
        [text("Estado"), value(case.status)],
        [text("Fornecedor selecionado"), case.selected_supplier or ""],
        ["PO", case.po_number or ""],
    ]
    story.extend([label_value_table(rows, [5 * cm, 12 * cm]), Spacer(1, 0.5 * cm)])
    if is_replenishment:
        item_rows = [[text(label) for label in ["Código / produto", "Qtd.", "Preço unit.", "Total", "Recebido"]]]
        for item in case.requisition.items:
            item_rows.append(
                [
                    Paragraph(f"<b>{item.product.code}</b><br/>{localized_name(item.product, generated_by)}", styles["Normal"]),
                    f"{float(item.quantity_requested or 0):g} {item.product.unit}",
                    f"{float(item.estimated_unit_price or 0):.2f}",
                    f"{float(item.quantity_requested or 0) * float(item.estimated_unit_price or 0):.2f}",
                    f"{float(item.quantity_received or 0):g}",
                ]
            )
        story.extend(
            [
                Paragraph(f"<b>{text('Produtos a adquirir')}</b>", styles["Heading3"]),
                data_table(item_rows, col_widths=[7.4 * cm, 2.2 * cm, 2.6 * cm, 2.6 * cm, 2.2 * cm]),
                Spacer(1, 0.5 * cm),
            ]
        )
    story.append(Paragraph(f"<b>{text('Descrição / escopo')}</b>", styles["Heading3"]))
    story.append(Paragraph((case.description or "").replace("\n", "<br/>"), styles["Normal"]))
    if case.justification:
        story.extend([Spacer(1, 0.3 * cm), Paragraph(f"<b>{text('Justificação')}</b>", styles["Heading3"]), Paragraph(case.justification.replace("\n", "<br/>"), styles["Normal"])])
    if case.comments:
        story.extend([Spacer(1, 0.3 * cm), Paragraph(f"<b>{text('Comentários')}</b>", styles["Heading3"]), Paragraph(case.comments.replace("\n", "<br/>"), styles["Normal"])])
    doc.build(
        story,
        onFirstPage=lambda canvas, d: branded_footer(canvas, d, generated_name, language),
        onLaterPages=lambda canvas, d: branded_footer(canvas, d, generated_name, language),
    )
    return stream.getvalue()
