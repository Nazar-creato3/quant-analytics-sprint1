"""Portfolio aggregation across Grid, DCA, and Momentum bots."""
from __future__ import annotations

from typing import Any

from app.services.bot_risk.instruments import normalize_instrument_key
from app.services.bot_risk.types import BotRef, PortfolioSnapshot


def _bot_capital(data: dict[str, Any]) -> float:
    cfg = data.get("config") or {}
    for key in ("total_capital", "capital_allocated"):
        val = cfg.get(key)
        if val is not None:
            try:
                return max(0.0, float(val))
            except (TypeError, ValueError):
                pass
    return 0.0


def _bot_pnl(data: dict[str, Any]) -> float:
    try:
        return float(data.get("total_pnl", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _bot_ticker(data: dict[str, Any]) -> str:
    cfg = data.get("config") or {}
    return str(cfg.get("ticker") or cfg.get("symbol") or "").upper()


def _bot_has_exposure(data: dict[str, Any], bot_type: str) -> bool:
    if bot_type == "grid":
        for level in data.get("levels") or []:
            if level.get("status") == "filled" and level.get("side") == "buy":
                return True
        dca = data.get("dca_state") or {}
        return float(dca.get("total_qty") or 0.0) > 0
    runtime = data.get("runtime") or {}
    return float(runtime.get("position_qty") or 0.0) > 0


def bot_is_active(data: dict[str, Any]) -> bool:
    return bool(data.get("is_active", True)) and not data.get("risk_halt")


def build_bot_refs(
    *,
    grid: dict[str, dict[str, Any]] | None = None,
    dca: dict[str, dict[str, Any]] | None = None,
    momentum: dict[str, dict[str, Any]] | None = None,
) -> list[BotRef]:
    refs: list[BotRef] = []
    for bot_id, data in (grid or {}).items():
        refs.append(BotRef(bot_id=bot_id, bot_type="grid", data=data))
    for bot_id, data in (dca or {}).items():
        refs.append(BotRef(bot_id=bot_id, bot_type="dca", data=data))
    for bot_id, data in (momentum or {}).items():
        refs.append(BotRef(bot_id=bot_id, bot_type="momentum", data=data))
    return refs


def compute_drawdown_pct(
    *,
    total_pnl: float,
    allocated_usd: float,
    peak_pnl: float,
) -> float:
    if allocated_usd <= 0:
        return 0.0
    peak = max(peak_pnl, total_pnl)
    if peak > total_pnl:
        return max(0.0, (peak - total_pnl) / allocated_usd * 100.0)
    if total_pnl < 0:
        return abs(total_pnl) / allocated_usd * 100.0
    return 0.0


def build_portfolio_snapshot(
    refs: list[BotRef],
    *,
    peak_pnl: float = 0.0,
) -> PortfolioSnapshot:
    active = [r for r in refs if bot_is_active(r.data) and not r.data.get("is_paused")]
    allocated = sum(_bot_capital(r.data) for r in active)
    total_pnl = sum(_bot_pnl(r.data) for r in active)
    peak = max(float(peak_pnl), total_pnl)
    dd = compute_drawdown_pct(
        total_pnl=total_pnl,
        allocated_usd=allocated,
        peak_pnl=peak,
    )
    return PortfolioSnapshot(
        bots=refs,
        allocated_usd=allocated,
        total_pnl=total_pnl,
        peak_pnl=peak,
        drawdown_pct=dd,
    )


def list_exposed_instruments(
    refs: list[BotRef],
    *,
    exclude_bot_id: str | None = None,
) -> list[tuple[str, str, str]]:
    """Return (bot_id, bot_type, instrument_key) for bots with open exposure."""
    out: list[tuple[str, str, str]] = []
    for ref in refs:
        if exclude_bot_id and ref.bot_id == exclude_bot_id:
            continue
        if not bot_is_active(ref.data) or ref.data.get("is_paused"):
            continue
        if not _bot_has_exposure(ref.data, ref.bot_type):
            continue
        ticker = _bot_ticker(ref.data)
        key = normalize_instrument_key(ticker)
        if key:
            out.append((ref.bot_id, ref.bot_type, key))
    return out
