"""Numeric formatting helpers — explanations must cite exact input values."""
from __future__ import annotations


def fmt_num(value: float, *, decimals: int = 2) -> str:
    """Format a float for inclusion in explanation text."""
    return f"{value:.{decimals}f}"


def fmt_pct(value: float, *, decimals: int = 1) -> str:
    """Format a ratio as percentage (0.4 -> 40.0%)."""
    return f"{value * 100:.{decimals}f}%"


def fmt_pct_change(before: float, after: float, *, decimals: int = 1) -> str:
    """Relative change between two values, e.g. 0.5 -> 0.7 gives +40.0%."""
    if before == 0:
        if after == 0:
            return "0.0%"
        return f"+{fmt_pct(after, decimals=decimals)}"
    delta = (after - before) / abs(before)
    sign = "+" if delta >= 0 else ""
    return f"{sign}{fmt_pct(delta, decimals=decimals)}"


def fmt_regime_label(regime: str) -> str:
    return regime.replace("_", " ")
