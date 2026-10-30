"""Apply desk operators to a live risk result without rewriting the engine."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.quant_desk.microstructure import book_gate
from app.services.quant_desk.microstructure_features import roll_size_mult
from app.services.quant_desk.vol_target import vol_target_scale


@dataclass(frozen=True, slots=True)
class DeskOverlay:
    allow: bool
    size_mult: float
    reasons: tuple[str, ...]


def desk_overlay(
    *,
    equity_usd: float,
    price: float,
    atr: float,
    current_usd: float,
    direction: str,
    realized_ann_vol: float | None = None,
    bid: float | None = None,
    ask: float | None = None,
    bid_sz: float | None = None,
    ask_sz: float | None = None,
    atr_pct: float | None = None,
    live_leverage: float = 1.0,
    macro_tilt: float | None = None,
    spread_zscore: float | None = None,
) -> DeskOverlay:
    gate = book_gate(
        bid=bid,
        ask=ask,
        bid_sz=bid_sz,
        ask_sz=ask_sz,
        direction=direction,
        atr_pct=atr_pct if atr_pct is not None else (atr / price if price else None),
        live_leverage=live_leverage,
    )
    if not gate.allow:
        return DeskOverlay(False, 0.0, (gate.reason,))
    vt = vol_target_scale(
        current_usd=current_usd,
        equity_usd=equity_usd,
        price=price,
        atr=atr,
        realized_ann_vol=realized_ann_vol,
    )
    reasons = [gate.reason, "vol_target"]
    if macro_tilt is not None:
        # Risk-off (negative tilt) cuts long size; risk-on modestly lifts it.
        adj = 1.0 + 0.15 * max(-1.0, min(1.0, float(macro_tilt)))
        if direction == "short":
            adj = 1.0 - 0.15 * max(-1.0, min(1.0, float(macro_tilt)))
        vt *= max(0.7, min(1.15, adj))
        reasons.append("macro_tilt")
    roll_m = roll_size_mult(spread_zscore)
    if roll_m < 1.0:
        reasons.append("roll_spread_z")
    return DeskOverlay(True, max(0.4, min(1.2, vt * gate.size_mult * roll_m)), tuple(reasons))


def apply_to_risk(risk: Any, overlay: DeskOverlay) -> Any:
    if not overlay.allow:
        risk.is_tradeable = False
        risk.reason = overlay.reasons[0] if overlay.reasons else "desk_block"
        return risk
    m = overlay.size_mult
    if abs(m - 1.0) < 1e-6:
        return risk
    risk.position_size_usd = round(float(risk.position_size_usd) * m, 2)
    risk.position_size_shares = round(float(risk.position_size_shares) * m, 4)
    risk.risk_amount_usd = round(float(risk.risk_amount_usd) * m, 2)
    return risk
