"""Freqtrade pattern → RobotPlan levels (no GPL import).

Maps minimal_roi / stoploss / trailing_* dicts into our level JSON.
Used as the P3 bridge: strategy params → Robot Core, not a Freqtrade runtime.
"""
from __future__ import annotations

from typing import Any


def _f(v: Any) -> float | None:
    try:
        if v is None:
            return None
        x = float(v)
        if x != x:  # NaN
            return None
        return x
    except (TypeError, ValueError):
        return None


def levels_from_freqtrade_params(
    *,
    entry: float,
    side: str = "long",
    minimal_roi: dict[str, float] | None = None,
    stoploss: float = -0.08,
    trailing_stop: bool = True,
    trailing_stop_positive: float | None = 0.015,
    trailing_stop_positive_offset: float | None = None,
    add_zone_pct: float | None = 0.025,
) -> list[dict[str, Any]]:
    """Build RobotPlan levels from Freqtrade-style risk params.

    ``minimal_roi`` keys are minutes-as-string (ignored for price levels; used
    only to order the ladder). Values are fractional ROI (0.04 = +4%).
    """
    side_n = "short" if str(side).lower() in {"short", "sell"} else "long"
    entry_px = float(entry)
    if entry_px <= 0:
        raise ValueError("entry must be positive")

    levels: list[dict[str, Any]] = []
    levels.append(
        {
            "id": "entry",
            "kind": "entry",
            "side": "sell" if side_n == "short" else "buy",
            "price": entry_px,
            "size_pct": 100.0,
            "status": "filled",
            "fill_price": entry_px,
            "source": "freqtrade_bridge",
        }
    )

    if add_zone_pct and add_zone_pct > 0:
        if side_n == "long":
            add_px = round(entry_px * (1.0 - float(add_zone_pct)), 6)
            add_side = "buy"
        else:
            add_px = round(entry_px * (1.0 + float(add_zone_pct)), 6)
            add_side = "sell"
        levels.append(
            {
                "id": "add_1",
                "kind": "add",
                "side": add_side,
                "price": add_px,
                "size_pct": 50.0,
                "status": "watching",
                "source": "freqtrade_bridge",
            }
        )

    roi = dict(minimal_roi or {"0": 0.02})
    # Sort by minutes ascending: earliest/highest ROI first is FT convention
    # (key "0" = immediate). We emit TP ladder from highest ROI → lowest.
    steps: list[tuple[int, float]] = []
    for k, v in roi.items():
        mins = int(float(k))
        r = _f(v)
        if r is None or r <= 0:
            continue
        steps.append((mins, r))
    steps.sort(key=lambda x: x[0])  # time order
    # Prefer profit ladder: largest ROI first as tp_1
    profit_steps = sorted(steps, key=lambda x: -x[1])
    n = len(profit_steps) or 1
    share = round(100.0 / n, 2)
    for i, (mins, r) in enumerate(profit_steps):
        if side_n == "long":
            tp_px = round(entry_px * (1.0 + r), 6)
            tp_side = "sell"
        else:
            tp_px = round(entry_px * (1.0 - r), 6)
            tp_side = "buy"
        levels.append(
            {
                "id": f"tp_{i + 1}",
                "kind": "tp",
                "side": tp_side,
                "price": tp_px,
                "size_pct": share if i < n - 1 else round(100.0 - share * (n - 1), 2),
                "status": "watching",
                "roi": r,
                "roi_minutes": mins,
                "source": "freqtrade_bridge",
            }
        )

    sl_frac = _f(stoploss)
    if sl_frac is not None and sl_frac < 0:
        if side_n == "long":
            sl_px = round(entry_px * (1.0 + sl_frac), 6)
            sl_side = "sell"
        else:
            sl_px = round(entry_px * (1.0 - sl_frac), 6)
            sl_side = "buy"
        levels.append(
            {
                "id": "sl",
                "kind": "sl",
                "side": sl_side,
                "price": sl_px,
                "size_pct": 100.0,
                "status": "watching",
                "stoploss": sl_frac,
                "source": "freqtrade_bridge",
            }
        )

    if trailing_stop:
        trail_pct = (_f(trailing_stop_positive) or 0.015) * 100.0
        activate = None
        offset = _f(trailing_stop_positive_offset)
        if offset and offset > 0:
            activate = (
                round(entry_px * (1.0 + offset), 6)
                if side_n == "long"
                else round(entry_px * (1.0 - offset), 6)
            )
        elif profit_steps:
            # Arm after first (highest) ROI level
            r0 = profit_steps[0][1]
            activate = (
                round(entry_px * (1.0 + r0), 6)
                if side_n == "long"
                else round(entry_px * (1.0 - r0), 6)
            )
        levels.append(
            {
                "id": "trail",
                "kind": "trail",
                "side": "buy" if side_n == "short" else "sell",
                "price": None,
                "trail_pct": trail_pct,
                "activate_at": activate,
                "peak_price": None,
                "size_pct": share,
                "status": "pending",
                "source": "freqtrade_bridge",
            }
        )

    return levels


# Defaults mirrored from infra/freqtrade ApexSignalBridge (patterns only).
APEX_SIGNAL_BRIDGE_DEFAULTS: dict[str, Any] = {
    "stoploss": -0.08,
    "minimal_roi": {"0": 0.02, "60": 0.01, "120": 0},
    "trailing_stop": True,
    "trailing_stop_positive": 0.015,
}


def levels_from_apex_signal_bridge(*, entry: float, side: str = "long") -> list[dict[str, Any]]:
    return levels_from_freqtrade_params(
        entry=entry,
        side=side,
        minimal_roi={k: v for k, v in APEX_SIGNAL_BRIDGE_DEFAULTS["minimal_roi"].items() if v},
        stoploss=float(APEX_SIGNAL_BRIDGE_DEFAULTS["stoploss"]),
        trailing_stop=True,
        trailing_stop_positive=float(APEX_SIGNAL_BRIDGE_DEFAULTS["trailing_stop_positive"]),
    )
