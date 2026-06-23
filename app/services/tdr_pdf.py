from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer

from app.models.core import ProcurementCase, User
from app.services.pdf_branding import (
    brand_header,
    branded_footer,
    branded_styles,
    data_table,
    generated_meta,
    label_value_table,
)


def _text(value: str | None) -> str:
    return (value or "").replace("\n", "<br/>")


def terms_of_reference_to_pdf(case: ProcurementCase, generated_by: User | None = None) -> bytes:
    stream = BytesIO()
    doc = SimpleDocTemplate(
        stream,
        pagesize=A4,
        rightMargin=1.4 * cm,
        leftMargin=1.4 * cm,
        topMargin=1.0 * cm,
        bottomMargin=1.2 * cm,
    )
    styles, _regular, _bold = branded_styles()
    normal = styles["Normal"]
    section = styles["GTSection"]
    generated_by_name = generated_by.full_name if generated_by else "Sistema"

    tdr_number = case.tdr_number or f"TdR-{case.requisition.number}"
    story = [
        brand_header(
            "TERMO DE REFERÊNCIA / TERM OF REFERENCE",
            subtitle=f"TdR No.: {tdr_number}",
            meta=generated_meta(generated_by_name),
        ),
        Spacer(1, 0.35 * cm),
        Paragraph(f"<b>Job title:</b> {case.job_title or case.description[:120]}", normal),
        Spacer(1, 0.2 * cm),
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
    story.extend([label_value_table(summary_rows, [5.2 * cm, 11.2 * cm]), Spacer(1, 0.25 * cm)])

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
        story.append(Paragraph(f"<b>{title}</b>", section))
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
    approvals = data_table(approval_rows, col_widths=[3.7 * cm, 5.0 * cm, 4.2 * cm, 3.6 * cm])
    story.append(KeepTogether([Paragraph("<b>9. APROVAÇÕES</b>", section), approvals]))

    doc.build(story, onFirstPage=lambda c, d: branded_footer(c, d, generated_by_name), onLaterPages=lambda c, d: branded_footer(c, d, generated_by_name))
    return stream.getvalue()
