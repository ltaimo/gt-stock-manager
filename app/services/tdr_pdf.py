from datetime import datetime
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.models.core import ProcurementCase, User


def _register_fonts() -> tuple[str, str]:
    regular = "Helvetica"
    bold = "Helvetica-Bold"
    try:
        pdfmetrics.registerFont(TTFont("GTArial", r"C:\Windows\Fonts\arial.ttf"))
        pdfmetrics.registerFont(TTFont("GTArialBold", r"C:\Windows\Fonts\arialbd.ttf"))
        regular = "GTArial"
        bold = "GTArialBold"
    except Exception:
        pass
    return regular, bold


def _text(value: str | None) -> str:
    return (value or "").replace("\n", "<br/>")


def _yes_no(value: bool | None) -> str:
    if value is True:
        return "Sim"
    if value is False:
        return "Não"
    return "Pendente"


def terms_of_reference_to_pdf(case: ProcurementCase, generated_by: User | None = None) -> bytes:
    regular_font, bold_font = _register_fonts()
    stream = BytesIO()
    doc = SimpleDocTemplate(
        stream,
        pagesize=A4,
        rightMargin=1.4 * cm,
        leftMargin=1.4 * cm,
        topMargin=1.0 * cm,
        bottomMargin=1.0 * cm,
    )
    styles = getSampleStyleSheet()
    for style_name in ("Normal", "Title", "Heading2", "Heading3"):
        styles[style_name].fontName = regular_font
    styles.add(
        ParagraphStyle(
            name="CenteredTitle",
            parent=styles["Title"],
            alignment=TA_CENTER,
            fontName=bold_font,
            fontSize=15,
            leading=18,
            spaceAfter=8,
        )
    )
    styles.add(ParagraphStyle(name="Section", parent=styles["Heading2"], fontName=bold_font, fontSize=11, leading=14, spaceBefore=10, spaceAfter=5))
    normal = styles["Normal"]

    tdr_number = case.tdr_number or f"TdR-{case.requisition.number}"
    story = [
        Paragraph("<b>TERMO DE REFERÊNCIA</b><br/>TERM OF REFERENCE", styles["CenteredTitle"]),
        Paragraph(f"<b>TdR No.:</b> {tdr_number}", normal),
        Paragraph(f"<b>Job title:</b> {case.job_title or case.description[:120]}", normal),
        Spacer(1, 0.25 * cm),
    ]

    summary_rows = [
        ["Requisitante", case.requisition.requesting_user.full_name],
        ["Departamento", case.requisition.department.name if case.requisition.department else ""],
        ["Tipo", case.item_type or "Bem"],
        ["Data", case.requisition.request_date.strftime("%d/%m/%Y")],
        ["Budget/TdR estimado", f"{float(case.estimated_budget or 0):.2f} MZN"],
        ["Valor PO/cotação", f"{float(case.po_value or 0):.2f} MZN" if case.po_value else "Pendente"],
        ["Modalidade", case.modality or "Por classificar"],
        ["Aprovação por valor", case.approval_route or "Por definir na matriz"],
        ["Estado TdR", case.tor_status or "Pendente"],
    ]
    summary = Table(summary_rows, colWidths=[5.2 * cm, 11.2 * cm])
    summary.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F5BF00")),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#DDDDDD")),
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTNAME", (1, 0), (-1, -1), regular_font),
                ("FONTNAME", (0, 0), (0, -1), bold_font),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("PADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.extend([summary, Spacer(1, 0.25 * cm)])

    sections = [
        ("1. ÂMBITO", case.description),
        ("2. CONDIÇÕES DE OFERTA", "Pretende-se para o concurso público fornecer/contratar: " + (case.description or "")),
        ("3. INFORMAÇÕES A SER APRESENTADA", "Perfil da empresa, denominação social, endereço completo, correio eletrónico, telefone, estrutura de gestão, certidão de registo comercial, alvará/documento equivalente e NUIT."),
        ("4. REQUISITOS", case.technical_requirements or "Cumprir com os requisitos técnicos definidos pelo departamento requisitante e todas as regras estabelecidas pela GTSA."),
        ("5. PRESTAÇÃO DE SERVIÇOS / FORNECIMENTO", "A empresa deve dispor de meios, equipamentos e equipa necessários para realizar as actividades. Deve apresentar metodologia, garantia quando aplicável e certificado de qualidade no fornecimento de material."),
        ("6. EPI NECESSÁRIO", case.hse_requirements or "Uniforme, botas com biqueira de aço, colete refletor, capacete com jugular, crachá de identificação e EPI adequado à actividade."),
        ("7. DOCUMENTOS REQUISITOS", "Documentação SSA/HSE após reunião de mobilização/Kick-off, seguro de acidentes de trabalho, lista de colaboradores, lista de equipamentos/ferramentas, atestados médicos e avaliação de risco da actividade."),
        ("8. CONDIÇÕES FINANCEIRAS", "A política da GTSA prevê pagamentos após entrega do trabalho/fornecimento, em até 30 dias a contar da submissão da factura e após confirmação do good service. Pagamento antecipado exige garantia bancária do valor em causa."),
    ]
    for title, body in sections:
        story.append(Paragraph(f"<b>{title}</b>", styles["Section"]))
        story.append(Paragraph(_text(body), normal))

    approval_rows = [
        ["Designation", "Title", "Name", "Position"],
        ["Requested by", "", case.requisition.requesting_user.full_name, case.requisition.requesting_user.role.name],
        ["Reviewed by", "HSE", "", case.hse_documents_status],
        ["Approved by", "HOD / Chefe do Departamento", case.hod_approved_by.full_name if case.hod_approved_by else "", "HOD"],
        ["Approved by", "Terminal Ops Manager", "", ""],
        ["Approved by", "Terminal Manager", case.terminal_manager_approved_by.full_name if case.terminal_manager_approved_by else "", "Terminal Manager"],
        ["Approved by value", case.approval_route or "", "", "Matriz de aprovações"],
    ]
    approvals = Table(approval_rows, colWidths=[3.7 * cm, 5 * cm, 4.2 * cm, 3.6 * cm])
    approvals.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F5BF00")),
                ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#999999")),
                ("FONTNAME", (0, 0), (-1, 0), bold_font),
                ("FONTNAME", (0, 1), (-1, -1), regular_font),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("PADDING", (0, 0), (-1, -1), 5),
            ]
        )
    )
    story.append(KeepTogether([Paragraph("<b>9. APROVAÇÕES</b>", styles["Section"]), approvals]))
    story.extend(
        [
            Spacer(1, 0.35 * cm),
            Paragraph(f"Gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')}", normal),
            Paragraph(f"Gerado por: {generated_by.full_name if generated_by else 'Sistema'}", normal),
        ]
    )
    doc.build(story)
    return stream.getvalue()
