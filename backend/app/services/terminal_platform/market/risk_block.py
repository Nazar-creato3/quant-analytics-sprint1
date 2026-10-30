"""Terminal Risk panel — derived from live watchlist quotes (never mock)."""
from __future__ import annotations

from typing import Any, Optional

from app.services.terminal_platform.market.schemas import RiskHighBetaRow, RiskSummaryBlock, WatchlistEnrichedRow


def build_risk_summary(
    watchlist: list[WatchlistEnrichedRow],
    *,
    indices: Optional[list[Any]] = None,
) -> RiskSummaryBlock:
    """Score + high-beta movers from watchlist change% and prices."""
    rows = [w for w in watchlist if w.status == "ok" and w.last is not None]
    moves = [w.change_pct for w in rows if w.change_pct is not None]
    if not moves:
        return RiskSummaryBlock(
            score=None,
            label="No data",
            var_pct=None,
            high_beta=[],
            reason="Need watchlist quotes with change% to estimate risk",
        )

    abs_moves = [abs(float(m)) for m in moves]
    avg = sum(abs_moves) / len(abs_moves)
    score = max(10.0, min(90.0, round(30.0 + avg * 12.0, 1)))
    label = "Elevated" if score >= 65 else "Moderate" if score >= 40 else "Calm"

    ranked = sorted(
        rows,
        key=lambda w: abs(w.change_pct or 0.0),
        reverse=True,
    )[:5]

    high_beta = [
        RiskHighBetaRow(
            symbol=str(w.display or w.symbol),
            price=w.last,
            beta=None,
            change_pct=w.change_pct,
            note="from live quote" if w.change_pct is not None else "insufficient data",
        )
        for w in ranked
    ]

    return RiskSummaryBlock(
        score=score,
        label=label,
        var_pct=round(avg * 0.8, 2),
        high_beta=high_beta,
        reason=None,
    )
