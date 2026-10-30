"""Parse T-Bank-like XLSX/XML/CSV, then delete the file. Live parse after PdN gates."""
from __future__ import annotations

import csv
import io
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from app.services.legal.catalog import rkn_notice_filed
from app.services.qa.feature_flags import is_enabled

DEMO_XML = """<?xml version="1.0" encoding="utf-8"?>
<broker_report broker="tbank" period="demo">
  <item ticker="SBER" qty="10" amount="2800" date="2026-01-15"/>
  <item ticker="GAZP" qty="20" amount="2600" date="2026-01-16"/>
  <item ticker="LKOH" qty="2" amount="14000" date="2026-01-17"/>
</broker_report>
"""


def statement_live_allowed() -> bool:
    """Real files only after rkn.notice. QA_E2E_DEMO still uses the demo fixture."""
    if not is_enabled("qa_k6_fund_report"):
        return False
    return rkn_notice_filed()


def parse_statement(raw: bytes, *, filename: str = "statement.xml") -> dict[str, Any]:
    name = (filename or "").lower()
    try:
        if name.endswith(".xml") or raw.lstrip().startswith(b"<"):
            rows = _parse_xml(raw)
        elif name.endswith(".csv"):
            rows = _parse_csv(raw)
        elif name.endswith(".xlsx"):
            rows = _parse_xlsx(raw)
        else:
            raise ValueError("unsupported_format")
    except Exception as exc:
        return {"ok": False, "reason": "нет данных", "detail": str(exc)[:200], "positions": []}
    if not rows:
        return {"ok": False, "reason": "нет данных", "positions": []}
    return {"ok": True, "broker": "tbank", "positions": rows, "n": len(rows)}


def parse_demo() -> dict[str, Any]:
    return parse_statement(DEMO_XML.encode("utf-8"), filename="demo.xml")


def unlink_quietly(path: str | Path) -> None:
    try:
        Path(path).unlink(missing_ok=True)
    except OSError:
        pass


def _parse_xml(raw: bytes) -> list[dict[str, str]]:
    root = ET.fromstring(raw)
    rows: list[dict[str, str]] = []
    for item in root.findall(".//item"):
        ticker = (item.get("ticker") or item.get("figi") or "").upper()
        if not ticker:
            continue
        rows.append(
            {
                "ticker": ticker,
                "qty": item.get("qty") or "0",
                "amount": item.get("amount") or "0",
                "date": item.get("date") or "",
            }
        )
    return rows


def _parse_csv(raw: bytes) -> list[dict[str, str]]:
    text = raw.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    rows: list[dict[str, str]] = []
    for rec in reader:
        key = {str(k).strip().lower(): v for k, v in rec.items() if k}
        ticker = str(key.get("ticker") or key.get("код") or "").upper()
        if not ticker:
            continue
        rows.append(
            {
                "ticker": ticker,
                "qty": str(key.get("qty") or key.get("количество") or "0"),
                "amount": str(key.get("amount") or key.get("сумма") or "0"),
                "date": str(key.get("date") or key.get("дата") or ""),
            }
        )
    return rows


def _parse_xlsx(raw: bytes) -> list[dict[str, str]]:
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    sheet = wb.active
    rows_iter = sheet.iter_rows(values_only=True)
    header = [str(c or "").strip().lower() for c in next(rows_iter, [])]
    idx = {name: i for i, name in enumerate(header)}
    ticker_i = idx.get("ticker", idx.get("код", 0))
    qty_i = idx.get("qty", idx.get("количество", 1))
    amount_i = idx.get("amount", idx.get("сумма", 2))
    date_i = idx.get("date", idx.get("дата", 3))
    out: list[dict[str, str]] = []
    for rec in rows_iter:
        ticker = str(rec[ticker_i] if ticker_i < len(rec) else "").upper()
        if not ticker or ticker == "TICKER":
            continue
        out.append(
            {
                "ticker": ticker,
                "qty": str(rec[qty_i] if qty_i < len(rec) else "0"),
                "amount": str(rec[amount_i] if amount_i < len(rec) else "0"),
                "date": str(rec[date_i] if date_i < len(rec) else ""),
            }
        )
    wb.close()
    return out
