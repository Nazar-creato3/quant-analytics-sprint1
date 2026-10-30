"""Server PDF from the same assemble() payload (Prompt 20).

Uses ReportLab when installed; otherwise a minimal PDF so CI/local
without the extra wheel still prove the same numbers are printed.
"""
from __future__ import annotations

from typing import Any


def render_report_pdf(payload: dict[str, Any]) -> bytes:
    first = payload.get("first_screen") or {}
    lines = [
        str(payload.get("headline") or "Отчёт"),
        str(payload.get("disclaimer") or ""),
        f"TWR: {_val(first.get('twr'))}",
        f"MWR: {_val(first.get('mwr'))}",
        f"VaR 95: {_val(first.get('var_95'))}",
        f"HHI: {_val(first.get('hhi'))}",
        f"as_of {_val(first.get('as_of') or payload.get('as_of'))}",
    ]
    fund = payload.get("fund") or {}
    if fund.get("data_status") not in {None, "off"}:
        lines.extend(
            [
                f"CAGR: {_val(fund.get('cagr'))}",
                f"max_dd: {_val(fund.get('max_dd'))}",
                f"Sharpe: {_val(fund.get('sharpe'))}",
                f"ENB: {_val((fund.get('attribution') or {}).get('enb'))}",
            ]
        )
    return render_lines_pdf(lines)


def render_lines_pdf(lines: list[str]) -> bytes:
    try:
        return _reportlab_pdf(lines)
    except Exception:
        return _minimal_pdf("\n".join(lines))


def _val(value: Any) -> str:
    if value in (None, ""):
        return "нет данных"
    return str(value)


def _reportlab_pdf(lines: list[str]) -> bytes:
    import io

    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title="Отчёт о портфеле")
    styles = getSampleStyleSheet()
    story = []
    for i, line in enumerate(lines):
        style = styles["Title"] if i == 0 else styles["Normal"]
        story.append(Paragraph(_esc(line), style))
        story.append(Spacer(1, 0.15 * cm))
    doc.build(story)
    return buf.getvalue()


def _esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _minimal_pdf(text: str) -> bytes:
    safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = f"BT /F1 11 Tf 50 750 Td ({safe[:1200]}) Tj ET".encode("latin-1", "replace")
    objects = [
        b"1 0 obj << /Type /Catalog /Pages 2 0 R >> endobj\n",
        b"2 0 obj << /Type /Pages /Kids [3 0 R] /Count 1 >> endobj\n",
        b"3 0 obj << /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >> endobj\n",
        b"4 0 obj << /Length " + str(len(stream)).encode() + b" >> stream\n" + stream + b"\nendstream endobj\n",
        b"5 0 obj << /Type /Font /Subtype /Type1 /BaseFont /Helvetica >> endobj\n",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for obj in objects:
        offsets.append(len(out))
        out.extend(obj)
    xref = len(out)
    out.extend(f"xref\n0 {len(objects)+1}\n".encode())
    out.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.extend(f"{off:010d} 00000 n \n".encode())
    out.extend(f"trailer << /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(out)
