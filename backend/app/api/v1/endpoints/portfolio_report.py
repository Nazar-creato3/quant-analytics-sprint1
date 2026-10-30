"""Portfolio report API (Prompt 17) and K6 fund HTML / statement."""
from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse, Response

from app.services.fund_report.html import render_fund_html
from app.services.fund_report.statement import parse_demo, parse_statement, statement_live_allowed, unlink_quietly
from app.services.legal.catalog import load_ui_texts
from app.services.portfolio_report.pdf import render_report_pdf
from app.services.portfolio_report.service import assemble, history
from app.services.qa.feature_flags import is_enabled
from app.services.qa.session_user import require_session_user_id

router = APIRouter(prefix="/report", tags=["report"])


@router.get("")
def get_report(
    user_id: str = Depends(require_session_user_id),
    mode: str = Query("paper"),
) -> dict:
    if not is_enabled("qa_report"):
        raise HTTPException(status_code=404, detail="report flag off")
    payload = assemble(user_id=user_id, mode=mode)
    payload["versions"] = history(user_id=user_id, mode=mode)
    return payload


@router.get("/pdf")
def get_report_pdf(
    user_id: str = Depends(require_session_user_id),
    mode: str = Query("paper"),
) -> Response:
    if not is_enabled("qa_report"):
        raise HTTPException(status_code=404, detail="report flag off")
    payload = assemble(user_id=user_id, mode=mode)
    return Response(
        content=render_report_pdf(payload),
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="portfolio-report.pdf"'},
    )


@router.get("/html")
def get_report_html(
    user_id: str = Depends(require_session_user_id),
    mode: str = Query("paper"),
) -> HTMLResponse:
    if not is_enabled("qa_report") or not is_enabled("qa_k6_fund_report"):
        raise HTTPException(status_code=404, detail="report flag off")
    payload = assemble(user_id=user_id, mode=mode)
    texts = (load_ui_texts().get("k6") or {}) if isinstance(load_ui_texts(), dict) else {}
    return HTMLResponse(render_fund_html(payload, {str(k): str(v) for k, v in texts.items()}))


@router.get("/statement/demo.pdf")
def statement_demo_pdf(_user_id: str = Depends(require_session_user_id)) -> Response:
    if not is_enabled("qa_k6_fund_report"):
        raise HTTPException(status_code=404, detail="нет данных")
    from app.services.portfolio_report.pdf import render_lines_pdf

    return Response(
        content=render_lines_pdf(["нет данных"]),
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="statement-demo.pdf"'},
    )


@router.get("/statement/demo")
def statement_demo(_user_id: str = Depends(require_session_user_id)) -> dict:
    if not is_enabled("qa_k6_fund_report"):
        raise HTTPException(status_code=404, detail="нет данных")
    return {
        "mode": "нет данных",
        "live_allowed": statement_live_allowed(),
        "file_kept": False,
        "parsed": {"ok": False, "positions": [], "reason": "нет данных"},
    }


_MAX_STATEMENT_BYTES = 10 * 1024 * 1024


@router.post("/statement")
async def statement_upload(
    file: UploadFile = File(...),
    _session_user: str = Depends(require_session_user_id),
) -> dict:
    if not is_enabled("qa_k6_fund_report"):
        raise HTTPException(status_code=404, detail="k6 flag off")
    suffix = Path(file.filename or "statement.xml").suffix or ".xml"
    if suffix.lower() not in {".xml", ".csv", ".xlsx"}:
        raise HTTPException(status_code=415, detail="Поддерживаются отчёты брокера в XML, CSV или XLSX")
    # A broker statement is well under a few MB; read at most 10 MB so one upload cannot exhaust memory.
    raw = await file.read(_MAX_STATEMENT_BYTES + 1)
    if len(raw) > _MAX_STATEMENT_BYTES:
        raise HTTPException(status_code=413, detail="Файл больше 10 МБ")
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    try:
        tmp.write(raw)
        tmp.close()
        if not statement_live_allowed():
            parsed = parse_demo()
            return {
                "mode": "demo",
                "live_allowed": False,
                "file_kept": False,
                "mail": "waiting_smtp",
                "parsed": parsed,
                "reason": "pdn_gates",
            }
        parsed = parse_statement(raw, filename=file.filename or "statement.xml")
        return {
            "mode": "live",
            "live_allowed": True,
            "file_kept": False,
            "mail": "waiting_smtp",
            "parsed": parsed,
        }
    finally:
        unlink_quietly(tmp.name)
