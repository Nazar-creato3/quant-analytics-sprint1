"""PDF export of one maneuver's journal (Prompt 39).

ReportLab when installed; otherwise a one-page PDF with the same lines.
This file is the fixation draft. It is not a lawyer-approved advice form.
"""
from __future__ import annotations

import json
from typing import Any


def export_journal_pdf(rows: list[dict[str, Any]], maneuver_id: str) -> bytes | None:
    picked = [row for row in rows if _mentions(row, maneuver_id)]
    if not picked:
        return None
    lines = [
        "Журнал манёвра",
        f"Идентификатор: {maneuver_id}",
        "Черновик фиксации. Форма рекомендации советника не утверждена (OQ-18-1).",
    ]
    for row in picked:
        lines.append(f"{row.get('at')} · {row.get('name')} · {row.get('hash')}")
        shown = str(row.get("shown_text") or "")
        if shown:
            lines.append(shown)
        versions = row.get("model_versions") or {}
        if versions:
            lines.append("версии: " + json.dumps(versions, ensure_ascii=False, sort_keys=True, default=str))
    try:
        return _reportlab_pdf(lines)
    except ImportError:
        return _minimal_pdf("\n".join(lines))


def _mentions(row: dict[str, Any], maneuver_id: str) -> bool:
    payload = row.get("payload") or {}
    if isinstance(payload, dict):
        maneuver = payload.get("maneuver")
        if isinstance(maneuver, dict) and str(maneuver.get("id") or "") == maneuver_id:
            return True
        if str(payload.get("maneuver_id") or "") == maneuver_id:
            return True
    return maneuver_id in json.dumps(payload, ensure_ascii=False, default=str)


def _reportlab_pdf(lines: list[str]) -> bytes:
    import io

    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, title="Журнал манёвра")
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
    stream = f"BT /F1 11 Tf 50 780 Td ({safe[:1500]}) Tj ET".encode("latin-1", "replace")
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
    out.extend(
        f"trailer << /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(out)
