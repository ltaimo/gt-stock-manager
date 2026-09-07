from __future__ import annotations

from datetime import datetime

from app.models.core import DepartmentDailyReport


DEPARTMENT_COPY_PERMISSION = "internal_ops_reports_copy"


def clean_lines(value: object) -> list[str]:
    text = "" if value is None else str(value)
    return [line.strip() for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n") if line.strip()]


def first_line(value: object, fallback: str = "Nao informado") -> str:
    lines = clean_lines(value)
    return lines[0] if lines else fallback


def bullet_block(value: object, empty: str = "Nao informado") -> list[str]:
    lines = clean_lines(value)
    if not lines:
        return [empty]
    return [line if line.startswith(("-", "*")) else f"- {line}" for line in lines]


def plain_block(value: object, empty: str = "Nao informado") -> list[str]:
    lines = clean_lines(value)
    return lines or [empty]


def report_date_text(report: DepartmentDailyReport) -> str:
    value = report.report_date
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    return str(value or "")


def report_period_text(report: DepartmentDailyReport) -> str:
    if report.period_start or report.period_end:
        return f"{report.period_start or ''} - {report.period_end or ''}".strip(" -")
    return report.shift or "Nao informado"


def section(title: str, lines: list[str]) -> list[str]:
    return ["", title, *lines]


def format_security_report(report: DepartmentDailyReport) -> str:
    lines = [
        "DEPARTAMENTO DE PROTECAO E SEGURANCA (DPS)",
        "",
        f"Data: {report_date_text(report)}",
        f"Periodo: {report_period_text(report)}",
        f"Responsavel: {report.prepared_by or report.created_by.full_name}",
    ]
    lines += section("INCIDENTES", plain_block(report.incidents))
    lines += section("APREENSOES", plain_block(report.equipment_status))
    lines += section("OUTRAS INFORMACOES", plain_block(report.notes))
    lines += section("INFORMACAO SOBRE STAFF DA SEGURANCA", plain_block(report.team))
    lines += section("DISTRIBUICAO DE POSTOS / PATRULHAS", plain_block(report.activities))
    lines += section("ILUMINACAO E LEITURAS", plain_block(report.readings))
    lines += section("PENDENCIAS", plain_block(report.pending_actions))
    return normalize_clipboard_text(lines)


def format_maintenance_report(report: DepartmentDailyReport) -> str:
    lines = [
        "RELATORIO DIARIO DE MANUTENCAO",
        "",
        f"Data da Manutencao: {report_date_text(report)}",
        f"Duracao da Manutencao: {report_period_text(report)}",
        f"Inspecoes conduzidas por: {report.supervisor or report.prepared_by or report.created_by.full_name}",
    ]
    lines += section("EQUIPE DE SERVICO", bullet_block(report.team))
    lines += section("EQUIPAMENTOS INSPECIONADOS", bullet_block(report.equipment_status))
    lines += section("TRABALHOS EXECUTADOS", bullet_block(report.activities))
    lines += section("PARAGENS E EMERGENCIAS", bullet_block(report.incidents))
    lines += section("UTILIDADE / EQUIPAMENTOS CRITICOS", plain_block(report.readings))
    lines += section("NOTAS ADICIONAIS", bullet_block(report.notes))
    lines += section("PENDENCIAS", bullet_block(report.pending_actions))
    return normalize_clipboard_text(lines)


def format_it_report(report: DepartmentDailyReport) -> str:
    lines = [
        "DEPARTAMENTO DE INFORMATICA / IT",
        "",
        f"Data: {report_date_text(report)}",
        f"Periodo: {report_period_text(report)}",
        f"Responsavel: {report.prepared_by or report.created_by.full_name}",
    ]
    lines += section("ATIVIDADES DOS ITS / SUPORTE EXECUTADO", bullet_block(report.activities))
    lines += section("INCIDENTES TECNICOS / FALHAS DE SISTEMAS", bullet_block(report.incidents))
    lines += section("EQUIPAMENTOS, REDES E SISTEMAS VERIFICADOS", bullet_block(report.equipment_status))
    lines += section("INDICADORES TECNICOS / DISPONIBILIDADE", plain_block(report.readings))
    lines += section("PENDENCIAS", bullet_block(report.pending_actions))
    lines += section("OBSERVACOES", plain_block(report.notes))
    return normalize_clipboard_text(lines)


def normalize_clipboard_text(lines: list[str]) -> str:
    output: list[str] = []
    previous_blank = False
    for line in lines:
        text = str(line).rstrip()
        blank = text == ""
        if blank and previous_blank:
            continue
        output.append(text)
        previous_blank = blank
    return "\n".join(output).strip() + "\n"


def format_department_report_for_daily(report: DepartmentDailyReport) -> str:
    if report.department_key == "security":
        return format_security_report(report)
    if report.department_key == "maintenance":
        return format_maintenance_report(report)
    if report.department_key == "it":
        return format_it_report(report)
    return normalize_clipboard_text(
        [
            "RELATORIO DEPARTAMENTAL",
            "",
            f"Data: {report_date_text(report)}",
            f"Departamento: {report.department_key}",
            f"Responsavel: {report.prepared_by or report.created_by.full_name}",
            "",
            "ATIVIDADES",
            *plain_block(report.activities),
            "",
            "OCORRENCIAS",
            *plain_block(report.incidents),
        ]
    )


def daily_report_separator(title: str) -> str:
    rule = "=" * 40
    return f"{rule}\n{title}\n{rule}"


def format_reports_for_daily_bundle(reports: list[DepartmentDailyReport], missing_labels: list[str] | None = None) -> str:
    titles = {
        "security": "DEPARTAMENTO DE PROTECAO E SEGURANCA",
        "maintenance": "RELATORIO DIARIO DE MANUTENCAO",
        "it": "DEPARTAMENTO DE INFORMATICA",
    }
    blocks = []
    for report in reports:
        blocks.append(f"{daily_report_separator(titles.get(report.department_key, report.department_key.upper()))}\n\n{format_department_report_for_daily(report).strip()}")
    for label in missing_labels or []:
        blocks.append(f"{daily_report_separator(label.upper())}\n\n{label} - Relatorio ainda nao submetido")
    return "\n\n".join(blocks).strip() + "\n"
