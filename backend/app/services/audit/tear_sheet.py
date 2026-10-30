"""HTML tear sheet generation with QuantStats baseline + custom sections."""
from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.services.audit.types import ClosedTradeRecord

logger = get_logger(__name__)

REPORTS_DIR = Path(__file__).resolve().parents[3] / "data" / "position_audits"


def _section(title: str, data: dict[str, Any]) -> str:
    body = html.escape(str(data))
    return f"<section><h2>{html.escape(title)}</h2><pre>{body}</pre></section>"


def _render_custom_sections(admin_metrics: dict[str, Any]) -> str:
    sections = []
    for key, title in (
        ("core_stats", "Core Performance"),
        ("r_multiple", "R-Multiple Analysis"),
        ("factor_attribution", "Factor Attribution"),
        ("pattern_analysis", "Pattern Analysis"),
        ("expiration_analysis", "Expiration Analysis"),
        ("execution_quality", "Execution Quality"),
        ("streak_analysis", "Streak Analysis"),
        ("monte_carlo", "Monte Carlo Bust Probability"),
    ):
        payload = admin_metrics.get(key)
        if payload:
            sections.append(_section(title, payload))
    return "\n".join(sections)


def _quantstats_baseline(trades: list[ClosedTradeRecord]) -> str:
    """Generate QuantStats HTML tear sheet from trade return series."""
    try:
        import pandas as pd
        import quantstats as qs
    except ImportError:
        logger.warning("quantstats_not_installed")
        return "<p>QuantStats not installed — custom sections only.</p>"

    returns = [t.return_pct for t in trades]
    if len(returns) < 2:
        return "<p>Insufficient trades for QuantStats baseline.</p>"

    index = pd.date_range(end=pd.Timestamp.utcnow(), periods=len(returns), freq="B")
    series = pd.Series(returns, index=index, name="Strategy")
    try:
        return qs.reports.html(
            series,
            output=None,
            title="Position Audit Tear Sheet",
            download_filename=None,
        )
    except Exception as exc:
        logger.warning("quantstats_html_failed", error=str(exc))
        return f"<p>QuantStats generation failed: {html.escape(str(exc))}</p>"


def generate_tear_sheet(
    trades: list[ClosedTradeRecord],
    admin_metrics: dict[str, Any],
    *,
    audit_id: str,
) -> Path:
    """Write combined HTML report to disk and return path."""
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    baseline = _quantstats_baseline(trades)
    custom = _render_custom_sections(admin_metrics)
    document = f"""<!DOCTYPE html>
<html lang="ru">
<head>
  <meta charset="utf-8"/>
  <title>Position Audit {html.escape(audit_id)}</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 2rem; background: #0b0f14; color: #e8edf2; }}
    h1, h2 {{ color: #7dd3fc; }}
    section {{ margin: 2rem 0; padding: 1rem; border: 1px solid #1e293b; border-radius: 8px; }}
    pre {{ white-space: pre-wrap; font-size: 0.85rem; }}
  </style>
</head>
<body>
  <h1>Position Audit Report</h1>
  <p>Audit ID: {html.escape(audit_id)} | Trades: {len(trades)}</p>
  <div id="quantstats-baseline">{baseline}</div>
  <div id="custom-sections">{custom}</div>
</body>
</html>"""
    out_path = REPORTS_DIR / f"{audit_id}.html"
    out_path.write_text(document, encoding="utf-8")
    return out_path
