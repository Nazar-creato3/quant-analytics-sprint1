"""Foucault / Hasbrouck / Cartea: do not pay a toxic or empty book."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BookGate:
    allow: bool
    size_mult: float
    reason: str


def relative_spread(bid: float | None, ask: float | None) -> float | None:
    if bid is None or ask is None or bid <= 0 or ask <= 0 or ask < bid:
        return None
    mid = 0.5 * (bid + ask)
    if mid <= 0:
        return None
    return (ask - bid) / mid


def imbalance(bid_sz: float | None, ask_sz: float | None) -> float | None:
    if bid_sz is None or ask_sz is None:
        return None
    tot = bid_sz + ask_sz
    if tot <= 0:
        return None
    return (bid_sz - ask_sz) / tot


def margin_buffer(*, leverage: float, maintenance: float) -> float:
    """Novotny: onset is the buffer, not leverage alone. Price drop before forced sale."""
    lev = max(1.0, float(leverage))
    maint = min(0.99, max(0.01, float(maintenance)))
    return max(0.0, 1.0 - maint) / lev


def book_gate(
    *,
    bid: float | None = None,
    ask: float | None = None,
    bid_sz: float | None = None,
    ask_sz: float | None = None,
    direction: str = "long",
    max_spread: float = 0.004,
    atr_pct: float | None = None,
    live_leverage: float = 1.0,
    maintenance: float = 0.25,
) -> BookGate:
    spr = relative_spread(bid, ask)
    have_quoted_spread = spr is not None
    if have_quoted_spread and spr > max_spread:
        return BookGate(False, 0.0, "wide_spread")
    imb = imbalance(bid_sz, ask_sz)
    size = 1.0
    if imb is not None:
        if direction == "long" and imb < -0.45:
            size *= 0.7
        if direction == "short" and imb > 0.45:
            size *= 0.7
    buf = margin_buffer(leverage=live_leverage, maintenance=maintenance)
    if buf < 0.08:
        return BookGate(False, 0.0, "thin_margin_buffer")
    # Quoted book: tighten size near the spread cap.
    if have_quoted_spread and spr is not None and spr > max_spread * 0.6:
        size *= 0.85
    # No L2 book (daily pipeline): ATR is volatility, not a quoted spread.
    # Never veto the whole book from ATR%; only shade size on wild names.
    elif not have_quoted_spread and atr_pct is not None and atr_pct > 0:
        proxy = min(0.05, atr_pct * 0.15)
        if proxy > max_spread:
            size *= 0.7
        elif proxy > max_spread * 0.6:
            size *= 0.85
    return BookGate(True, max(0.4, min(1.15, size)), "ok")
