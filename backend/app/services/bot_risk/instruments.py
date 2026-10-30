"""Instrument normalization for simplified correlation checks."""
from __future__ import annotations

import re

_QUOTE_SUFFIXES = ("USDT", "USDC", "USD", "BUSD", "EUR", "BTC", "ETH")
_PAIR_RE = re.compile(r"^([A-Z0-9]{1,12})[/\-_]?([A-Z0-9]{1,12})?$")


def normalize_instrument_key(ticker: str) -> str:
    """
    Map tickers to a canonical base asset key.

    Examples:
      BTC/USDT, BTCUSDT, btc-usd -> BTC
      ETH/USD -> ETH
    """
    raw = (ticker or "").strip().upper()
    if not raw:
        return ""

    m = _PAIR_RE.match(raw.replace(" ", ""))
    if m and m.group(2):
        return m.group(1)

    for suffix in _QUOTE_SUFFIXES:
        if raw.endswith(suffix) and len(raw) > len(suffix):
            return raw[: -len(suffix)]

    return raw


def instruments_correlated(a: str, b: str) -> bool:
    """True when two tickers represent the same or equivalent underlying."""
    if not a or not b:
        return False
    ka = normalize_instrument_key(a)
    kb = normalize_instrument_key(b)
    if not ka or not kb:
        return False
    return ka == kb
