from io import BytesIO

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.platypus import KeepTogether, Paragraph, SimpleDocTemplate, Spacer

from app.i18n import language_for, translate_text, translate_value
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
    language = language_for(generated_by)
    text = lambda value: translate_text(value, language)
    value = lambda item: translate_value(item, language)
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
    generated_by_name = generated_by.full_name if generated_by else text("Sistema")

    tdr_number = case.tdr_number or f"TdR-{case.requisition.number}"
    story = [
        brand_header(
            "TERM OF REFERENCE" if language == "en" else "TERMO DE REFERÊNCIA",
            subtitle=f"{'ToR No.' if language == 'en' else 'TdR n.º'}: {tdr_number}",
            meta=generated_meta(generated_by_name, language),
        ),
        Spacer(1, 0.35 * cm),
        Paragraph(f"<b>{'Job title' if language == 'en' else 'Título do trabalho'}:</b> {case.job_title or case.description[:120]}", normal),
        Spacer(1, 0.2 * cm),
    ]

    summary_rows = [
        [text("Requisitante"), case.requisition.requesting_user.full_name],
        [text("Departamento"), case.requisition.department.name if case.requisition.department else ""],
        [text("Tipo"), value(case.item_type or "Bem")],
        [text("Data"), case.requisition.request_date.strftime("%d/%m/%Y")],
        [text("Budget/TdR estimado"), f"{float(case.estimated_budget or 0):.2f} MZN"],
        [text("Valor PO/cotação"), f"{float(case.po_value or 0):.2f} MZN" if case.po_value else value("Pending")],
        [text("Modalidade"), case.modality or text("Por classificar")],
        [text("Aprovação por valor"), case.approval_route or text("Por definir na matriz")],
        [text("Estado TdR"), value(case.tor_status or "Pending")],
    ]
    story.extend([label_value_table(summary_rows, [5.2 * cm, 11.2 * cm]), Spacer(1, 0.25 * cm)])

    if language == "en":
        sections = [
            ("1. SCOPE", case.description),
            ("2. TENDER CONDITIONS", "The public tender is intended to supply/contract: " + (case.description or "")),
            ("3. INFORMATION TO BE PROVIDED", "Company profile, registered name, full address, email, telephone, management structure, commercial registration certificate, licence or equivalent document, and tax number."),
            ("4. REQUIREMENTS", case.technical_requirements or "Comply with the technical requirements defined by the requesting department and all GTSA rules."),
            ("5. SERVICE DELIVERY / SUPPLY", "The company must have the resources, equipment and team required to perform the work. It must provide a methodology, a warranty where applicable, and a quality certificate for supplied materials."),
            ("6. REQUIRED PPE", case.hse_requirements or "Uniform, steel-toe boots, reflective vest, helmet with chin strap, identification badge, and PPE appropriate to the activity."),
            ("7. REQUIRED DOCUMENTS", "HSE documentation after the mobilisation/kick-off meeting, occupational accident insurance, staff list, equipment/tool list, medical fitness certificates, and activity risk assessment."),
            ("8. FINANCIAL CONDITIONS", "GTSA policy provides for payment after delivery of the work or supply, within 30 days of invoice submission and confirmation of satisfactory service. Advance payment requires a bank guarantee for the amount concerned."),
        ]
    else:
        sections = [
            ("1. ÂMBITO", case.description),
            ("2. CONDIÇÕES DA PROPOSTA", "Pretende-se fornecer/contratar por concurso público: " + (case.description or "")),
            ("3. INFORMAÇÕES A APRESENTAR", "Perfil da empresa, denominação social, endereço completo, correio eletrónico, telefone, estrutura de gestão, certidão de registo comercial, alvará ou documento equivalente e NUIT."),
            ("4. REQUISITOS", case.technical_requirements or "Cumprir os requisitos técnicos definidos pelo departamento requisitante e todas as regras estabelecidas pela GTSA."),
            ("5. PRESTAÇÃO DE SERVIÇOS / FORNECIMENTO", "A empresa deve dispor dos meios, equipamentos e da equipa necessários para executar as atividades. Deve apresentar metodologia, garantia, quando aplicável, e certificado de qualidade dos materiais fornecidos."),
            ("6. EPI NECESSÁRIO", case.hse_requirements or "Uniforme, botas com biqueira de aço, colete refletor, capacete com jugular, crachá de identificação e EPI adequado à atividade."),
            ("7. DOCUMENTOS NECESSÁRIOS", "Documentação SSA/HSE após a reunião de mobilização/kick-off, seguro de acidentes de trabalho, lista de colaboradores, lista de equipamentos e ferramentas, atestados médicos e avaliação de risco da atividade."),
            ("8. CONDIÇÕES FINANCEIRAS", "A política da GTSA prevê o pagamento após a entrega do trabalho ou fornecimento, no prazo máximo de 30 dias após a submissão da fatura e a confirmação da boa execução. O pagamento antecipado exige uma garantia bancária do respetivo valor."),
        ]
    for title, body in sections:
        story.append(Paragraph(f"<b>{title}</b>", section))
        story.append(Paragraph(_text(body), normal))

    approval_rows = (
        [
            ["Designation", "Title", "Name", "Position"],
            ["Requested by", "", case.requisition.requesting_user.full_name, case.requisition.requesting_user.role.name],
            ["Reviewed by", "HSE", "", value(case.hse_documents_status)],
            ["Approved by", "Head of Department", case.hod_approved_by.full_name if case.hod_approved_by else "", "HOD"],
            ["Approved by", "Terminal Operations Manager", "", ""],
            ["Approved by", "Terminal Manager", case.terminal_manager_approved_by.full_name if case.terminal_manager_approved_by else "", "Terminal Manager"],
            ["Approved by value", case.approval_route or "", "", "Approval matrix"],
        ]
        if language == "en"
        else [
            ["Designação", "Título", "Nome", "Função"],
            ["Solicitado por", "", case.requisition.requesting_user.full_name, case.requisition.requesting_user.role.name],
            ["Revisto por", "HSE", "", value(case.hse_documents_status)],
            ["Aprovado por", "Chefe do Departamento", case.hod_approved_by.full_name if case.hod_approved_by else "", "HOD"],
            ["Aprovado por", "Gestor Operacional do Terminal", "", ""],
            ["Aprovado por", "Diretor do Terminal", case.terminal_manager_approved_by.full_name if case.terminal_manager_approved_by else "", "Diretor do Terminal"],
            ["Aprovado por valor", case.approval_route or "", "", "Matriz de aprovações"],
        ]
    )
    approvals = data_table(approval_rows, col_widths=[3.7 * cm, 5.0 * cm, 4.2 * cm, 3.6 * cm])
    story.append(KeepTogether([Paragraph(f"<b>{'9. APPROVALS' if language == 'en' else '9. APROVAÇÕES'}</b>", section), approvals]))

    doc.build(story, onFirstPage=lambda c, d: branded_footer(c, d, generated_by_name, language), onLaterPages=lambda c, d: branded_footer(c, d, generated_by_name, language))
    return stream.getvalue()
