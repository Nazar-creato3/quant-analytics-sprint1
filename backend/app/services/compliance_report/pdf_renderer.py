"""Render ComplianceReportDocument to PDF bytes via ReportLab."""
from __future__ import annotations

import io
from typing import Iterable

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

from app.services.compliance_report.types import ComplianceReportDocument


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _paragraphs_for_sections(
    sections: Iterable[tuple[str, str]],
    heading_style: ParagraphStyle,
    body_style: ParagraphStyle,
) -> list:
    flow: list = []
    for title, body in sections:
        if not body:
            continue
        flow.append(Paragraph(_escape(title), heading_style))
        flow.append(Paragraph(_escape(body), body_style))
        flow.append(Spacer(1, 0.15 * cm))
    return flow


def render_compliance_pdf(document: ComplianceReportDocument) -> bytes:
    """Produce a downloadable PDF for the given compliance report."""
    buffer = io.BytesIO()
    pdf = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=2 * cm,
        leftMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
        title=f"Compliance Report {document.deal_intent_id}",
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ComplianceTitle",
        parent=styles["Heading1"],
        fontSize=16,
        textColor=colors.HexColor("#1e293b"),
        spaceAfter=10,
    )
    meta_style = ParagraphStyle(
        "ComplianceMeta",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.HexColor("#475569"),
        spaceAfter=4,
    )
    section_style = ParagraphStyle(
        "ComplianceSection",
        parent=styles["Heading2"],
        fontSize=11,
        textColor=colors.HexColor("#334155"),
        spaceBefore=8,
        spaceAfter=4,
    )
    body_style = ParagraphStyle(
        "ComplianceBody",
        parent=styles["Normal"],
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#0f172a"),
        spaceAfter=6,
    )
    legal_style = ParagraphStyle(
        "ComplianceLegal",
        parent=styles["Italic"],
        fontSize=8,
        textColor=colors.HexColor("#64748b"),
        spaceBefore=12,
    )

    story: list = [
        Paragraph("Отчёт о рекомендации (Compliance)", title_style),
        Paragraph(
            f"ID отчёта: {_escape(document.report_id)} · "
            f"Сформирован: {document.generated_at.strftime('%Y-%m-%d %H:%M UTC')}",
            meta_style,
        ),
        Spacer(1, 0.3 * cm),
        Paragraph("Параметры рекомендации", section_style),
        Paragraph(
            f"<b>Инструмент:</b> {_escape(document.instrument_symbol)}<br/>"
            f"<b>Направление:</b> {_escape(document.direction)} · "
            f"<b>Стратегия:</b> {_escape(document.strategy)} · "
            f"<b>Статус:</b> {_escape(document.status)}<br/>"
            f"<b>Целевая цена:</b> {_escape(document.target_price or '—')}<br/>"
            f"<b>Обоснование:</b> {_escape(document.entry_reason)}",
            body_style,
        ),
        Paragraph("Профиль риска клиента", section_style),
        Paragraph(
            f"<b>Аппетит к риску:</b> {_escape(document.risk_appetite)} · "
            f"<b>Максимальная просадка:</b> {_escape(document.max_drawdown_pct)}%<br/>"
            f"<b>Юрисдикция:</b> {_escape(document.jurisdiction)} · "
            f"<b>Тип счёта:</b> {_escape(document.account_type)}",
            body_style,
        ),
        Paragraph("Объяснение", section_style),
        Paragraph(_escape(document.explainability_headline), body_style),
    ]
    story.extend(
        _paragraphs_for_sections(document.explainability_sections, section_style, body_style)
    )

    if document.narrator_insights:
        story.append(Paragraph("Интерпретация", section_style))
        for insight in document.narrator_insights:
            story.append(Paragraph(f"• {_escape(insight)}", body_style))

    if document.audit_reference:
        story.append(Paragraph("Ссылка на аудит", section_style))
        story.append(Paragraph(_escape(document.audit_reference), body_style))

    story.append(Paragraph(_escape(document.legal_notice), legal_style))

    pdf.build(story)
    return buffer.getvalue()
