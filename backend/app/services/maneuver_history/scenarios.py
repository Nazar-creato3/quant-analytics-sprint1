"""Synthetic profiles, golden starting books, and seeded price paths.

Crisis windows are reported from the committed golden dates only.
No market archive is downloaded and no crisis price is filled in.
"""
from __future__ import annotations

import hashlib
import json
import math
from datetime import date
from decimal import Decimal
from pathlib import Path

import numpy as np

from app.services.investment_profile.service import BAND_LIMITS
from app.services.maneuver_history.paths import golden_dir

START = date(2023, 12, 1)
SESSION_COUNT = 120
VOL = 0.01
# Golden books are one share. The maneuver lot is 1, so a one-share gap rounds to
# zero. Scaling the share count leaves weights unchanged and lets a lot trade.
STARTING_QTY_SCALE = Decimal("100")
CRISIS_WINDOWS = {
    "2008": (date(2008, 1, 1), date(2008, 12, 31)),
    "2014": (date(2014, 1, 1), date(2014, 12, 31)),
    "2020": (date(2020, 1, 1), date(2020, 12, 31)),
    "2022": (date(2022, 1, 1), date(2022, 12, 31)),
}
# Position caps are synthetic questionnaire answers. VaR, ES, and drawdown
# limits come from BAND_LIMITS. Expected return is left empty on purpose.
_POSITION_CAP = {"conservative": "0.40", "moderate": "0.60", "aggressive": "1.00"}


def synthetic_profiles() -> dict[str, dict[str, str]]:
    profiles: dict[str, dict[str, str]] = {}
    for band, cap in _POSITION_CAP.items():
        profiles[band] = {
            "horizon": "3y",
            "risk_tolerance": band,
            "max_position_pct": cap,
            "max_crisis_loss_pct": BAND_LIMITS[band]["max_drawdown"],
            "expected_return": "",
        }
    return profiles


def _dates_in(directory: Path) -> list[date]:
    found: list[date] = []
    for path in sorted(directory.glob("p*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        rows = list(document.get("quotes") or []) + list(document.get("operations") or [])
        for row in rows:
            raw = row.get("as_of")
            if not raw:
                continue
            found.append(date.fromisoformat(str(raw)[:10]))
    return found


def crisis_window_status(directory: Path | None = None) -> dict[str, str]:
    """«нет данных» when no committed golden date falls inside the window."""
    found = _dates_in(golden_dir() if directory is None else directory)
    status: dict[str, str] = {}
    for name, (start, end) in CRISIS_WINDOWS.items():
        hit = any(start <= day <= end for day in found)
        status[name] = "есть даты в эталонах" if hit else "нет данных"
    return status


def load_goldens(directory: Path | None = None) -> list[dict]:
    root = golden_dir() if directory is None else directory
    books: list[dict] = []
    for path in sorted(root.glob("p*.json")):
        document = json.loads(path.read_text(encoding="utf-8"))
        qty: dict[str, Decimal] = {}
        for op in document.get("operations") or []:
            symbol = str(op.get("symbol") or "").upper()
            kind = op.get("kind")
            if not symbol:
                continue
            if kind == "buy":
                qty[symbol] = qty.get(symbol, Decimal("0")) + Decimal(str(op["qty"]))
            elif kind == "split" and symbol in qty:
                qty[symbol] = qty[symbol] * Decimal(str(op["factor"]))
        anchors: dict[str, Decimal] = {}
        for quote in document.get("quotes") or []:
            symbol = str(quote.get("symbol") or "").upper()
            if symbol and quote.get("price") not in (None, ""):
                anchors[symbol] = Decimal(str(quote["price"]))
        scaled = {symbol: amount * STARTING_QTY_SCALE for symbol, amount in qty.items() if amount > 0}
        unpriced = sorted(symbol for symbol in scaled if symbol not in anchors)
        books.append(
            {
                "id": str(document.get("id") or path.stem),
                "qty": {symbol: amount for symbol, amount in scaled.items() if symbol in anchors},
                "anchors": anchors,
                "unpriced": unpriced,
            }
        )
    return books


def _mix(seed: int, ticker: str) -> int:
    digest = hashlib.sha256(f"{seed}:{ticker}".encode()).digest()
    return int.from_bytes(digest[:8], "little")


def price_path(anchor: Decimal, count: int, seed: int, ticker: str) -> list[Decimal]:
    """Seeded geometric path. The first price is the golden anchor, not a drawn shock."""
    if count < 1:
        return []
    rng = np.random.default_rng(_mix(seed, ticker))
    shocks = rng.normal(0.0, VOL, size=max(0, count - 1))
    prices = [anchor]
    level = float(anchor)
    drift = 0.5 * VOL * VOL
    for shock in shocks:
        level *= math.exp(float(shock) - drift)
        prices.append(Decimal(format(level, ".8f")))
    return prices


def paths_for(book: dict, sessions: int, seed: int) -> dict[str, list[Decimal]]:
    paths: dict[str, list[Decimal]] = {}
    for ticker, anchor in sorted(book["anchors"].items()):
        if ticker not in book["qty"]:
            continue
        paths[ticker] = price_path(anchor, sessions, seed, f"{book['id']}:{ticker}")
    return paths
