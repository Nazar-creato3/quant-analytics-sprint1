"""BotRiskGuard as a second gate on maneuvers — does not replace RiskEngine size."""
from __future__ import annotations

from typing import Any, Iterable

from app.core.logging import get_logger
from app.services.bot_risk.guard import BotRiskGuard, get_bot_risk_guard
from app.services.bot_risk.portfolio import build_portfolio_snapshot
from app.services.bot_risk.types import BotRef, PortfolioSnapshot

logger = get_logger(__name__)


def _finite_qty(raw: Any) -> float | None:
    if raw in (None, ""):
        return None
    try:
        qty = float(raw)
    except (TypeError, ValueError):
        return None
    if qty != qty:
        return None
    return max(0.0, qty)


def _item_qty(item: Any) -> float:
    """Shares already sized for this maneuver. Missing size is zero, never a fake 1."""
    risk = getattr(item, "risk", None)
    if risk is not None:
        qty = _finite_qty(getattr(risk, "position_size_shares", None))
        if qty is not None:
            return qty
    if isinstance(item, dict):
        for key in ("position_size_shares", "position_qty", "qty"):
            qty = _finite_qty(item.get(key))
            if qty is not None:
                return qty
        return 0.0
    for name in ("position_size_shares", "position_qty", "qty"):
        qty = _finite_qty(getattr(item, name, None))
        if qty is not None:
            return qty
    return 0.0


def maneuver_as_bot_ref(ticker: str, *, slot_id: str, usd: float = 0.0, qty: float = 0.0) -> BotRef:
    """Synthetic ref so check_correlation sees already-picked maneuvers."""
    return BotRef(
        bot_id=slot_id,
        bot_type="maneuver",
        data={
            "is_active": True,
            "is_paused": False,
            "config": {"ticker": str(ticker).upper(), "total_capital": float(usd or 0.0)},
            "runtime": {"position_qty": max(0.0, float(qty or 0.0))},
            "total_pnl": 0.0,
        },
    )


def snapshot_with_selected(
    base: PortfolioSnapshot | None,
    selected: Iterable[Any],
) -> PortfolioSnapshot:
    refs = list(base.bots) if base is not None else []
    for i, item in enumerate(selected):
        ticker = getattr(item, "ticker", None) or (item.get("ticker") if isinstance(item, dict) else None)
        if not ticker:
            continue
        usd = 0.0
        risk = getattr(item, "risk", None)
        if risk is not None:
            usd = float(getattr(risk, "position_size_usd", 0.0) or 0.0)
        refs.append(
            maneuver_as_bot_ref(
                str(ticker),
                slot_id=f"maneuver-{i}-{ticker}",
                usd=usd,
                qty=_item_qty(item),
            )
        )
    peak = float(base.peak_pnl) if base is not None else 0.0
    return build_portfolio_snapshot(refs, peak_pnl=peak)


def gate_maneuver(
    ticker: str,
    *,
    snapshot: PortfolioSnapshot | None,
    selected: Iterable[Any] = (),
    guard: BotRiskGuard | None = None,
) -> tuple[bool, str]:
    """Correlation + circuit breaker. Does not resize. Does not halt bots."""
    g = guard or get_bot_risk_guard()
    snap = snapshot_with_selected(snapshot, selected)
    cb = g.evaluate_circuit_breaker(snap)
    if cb.tripped:
        logger.info("maneuver_bot_risk_circuit", ticker=ticker, reason=cb.reason)
        return False, cb.reason or "bot_risk_circuit_breaker"
    corr = g.check_correlation(ticker=ticker, snapshot=snap, exclude_bot_id=None)
    if not corr.allowed:
        logger.info("maneuver_bot_risk_corr", ticker=ticker, reason=corr.reason)
        return False, corr.reason
    return True, corr.reason
