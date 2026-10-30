"""Single product context for terminal cycle (Prompt 46). No local copies of numbers."""
from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from app.services.portfolio_report.service import assemble
from app.services.risk_engine.service import compute_risk_for_user


def cycle_hrefs(ticker: str) -> dict[str, str]:
    symbol = (ticker or "").strip().upper()
    q = urlencode({"symbol": symbol}) if symbol else ""
    tail = f"?{q}" if q else ""
    return {
        "ticker": symbol,
        "portfolio_impact": f"/account{tail}",
        "pretrade": f"/direct-deals{tail}",
        "maneuvers": f"/act{tail}",
        "risk_events": f"/portfolio-risk{tail}",
    }


def aligned_numbers(*, user_id: str, mode: str = "paper") -> dict[str, Any]:
    """Report and risk engine share var_95 from one compute."""
    risk = compute_risk_for_user(user_id, mode)
    report = assemble(user_id=user_id, mode=mode)
    return {
        "var_95_risk": risk.get("var_95"),
        "var_95_report": (report.get("risk") or {}).get("var_95"),
        "var_95_first_screen": (report.get("first_screen") or {}).get("var_95"),
        "source_risk": "risk_engine",
        "source_report": "portfolio_report",
    }
