"""Concentration + Ken French FF exposures + SPY beta. Local cache only."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from app.core.config import settings


@dataclass(frozen=True, slots=True)
class FactorBook:
    hhi: float
    max_name: float
    max_sector: float
    spy_beta: float | None
    ff: dict[str, float]
    n_ff: int
    notes: tuple[str, ...]


def herfindahl(weights: Sequence[float]) -> float:
    w = [abs(float(x)) for x in weights]
    s = sum(w)
    if s <= 0:
        return 0.0
    n = [x / s for x in w]
    return float(sum(x * x for x in n))


def max_sector(weights: Sequence[float], sectors: Sequence[str]) -> float:
    by: dict[str, float] = {}
    for i, w in enumerate(weights):
        sec = str(sectors[i] if i < len(sectors) else "UNK") or "UNK"
        by[sec] = by.get(sec, 0.0) + abs(float(w))
    return max(by.values()) if by else 0.0


def spy_beta(asset: Sequence[float], spy: Sequence[float]) -> float | None:
    """OLS beta vs SPY. Short / flat series → None (GA16-325: never invent 1.0)."""
    n = min(len(asset), len(spy))
    if n < 10:
        return None
    a = np.asarray(asset[-n:], dtype=float)
    m = np.asarray(spy[-n:], dtype=float)
    var = float(np.var(m, ddof=1))
    if var <= 1e-16:
        return None
    cov = float(np.cov(a, m, ddof=1)[0, 1])
    return float(cov / var)


def load_ff_rows(path: Path | None = None) -> list[dict[str, Any]]:
    if path is None:
        root = getattr(settings, "FRED_BULK_DIR", "") or ""
        cand = Path(root) / "current" / "FF_DAILY_FACTORS.json" if root else None
        if cand is None or not cand.is_file():
            for guess in (
                Path("/app/data/fred_bulk/current/FF_DAILY_FACTORS.json"),
                Path("data/fred_bulk/current/FF_DAILY_FACTORS.json"),
            ):
                if guess.is_file():
                    cand = guess
                    break
        path = cand
    if path is None or not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = payload.get("rows") if isinstance(payload, dict) else payload
    return list(rows) if isinstance(rows, list) else []


def _col(row: Mapping[str, Any], *names: str) -> float | None:
    for n in names:
        if n in row and row[n] is not None:
            try:
                return float(row[n])
            except (TypeError, ValueError):
                continue
    return None


def ff_loadings(
    asset_returns: Sequence[float],
    ff_rows: Sequence[Mapping[str, Any]],
) -> dict[str, float]:
    """OLS of asset on Mkt-RF, SMB, HML (Mom if present). FF already in percent or decimal — we scale to decimal."""
    n = min(len(asset_returns), len(ff_rows))
    if n < 20:
        return {}
    y = np.asarray(asset_returns[-n:], dtype=float)
    cols = []
    names = []
    for key, aliases in (
        ("mkt", ("Mkt-RF", "Mkt_RF", "mkt-rf")),
        ("smb", ("SMB", "smb")),
        ("hml", ("HML", "hml")),
        ("mom", ("Mom", "Mom   ", "WML", "momentum")),
    ):
        series = []
        ok = True
        for row in list(ff_rows)[-n:]:
            v = _col(row, *aliases)
            if v is None:
                ok = False
                break
            series.append(v)
        if ok and series:
            arr = np.asarray(series, dtype=float)
            if float(np.median(np.abs(arr))) > 0.5:
                arr = arr / 100.0
            cols.append(arr)
            names.append(key)
    if not cols or any(len(c) != n for c in cols):
        return {}
    X = np.column_stack([np.ones(n)] + [np.asarray(c, dtype=float) for c in cols])
    try:
        beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    except np.linalg.LinAlgError:
        return {}
    out = {"alpha": round(float(beta[0]), 6)}
    for i, name in enumerate(names):
        out[name] = round(float(beta[i + 1]), 6)
    return out


def factor_book(
    weights: Sequence[float],
    symbols: Sequence[str],
    *,
    sectors: Sequence[str] = (),
    hist: Mapping[str, Sequence[float]] | None = None,
    spy: Sequence[float] | None = None,
    ff_rows: Sequence[Mapping[str, Any]] | None = None,
) -> FactorBook:
    notes: list[str] = []
    hhi = herfindahl(weights)
    mx = max((abs(float(x)) for x in weights), default=0.0)
    msec = max_sector(weights, sectors) if sectors else mx
    # book vs SPY: weighted average name beta (only from computable series)
    spy_b: float | None = None
    spy_w = 0.0
    spy_acc = 0.0
    ff_acc: dict[str, float] = {}
    n_ff = 0
    rows = list(ff_rows) if ff_rows is not None else load_ff_rows()
    if hist and spy:
        for i, sym in enumerate(symbols):
            w = float(weights[i]) if i < len(weights) else 0.0
            series = list(hist.get(sym) or [])
            b = spy_beta(series, spy)
            if b is not None:
                spy_acc += abs(w) * b
                spy_w += abs(w)
            ld = ff_loadings(series, rows)
            if ld:
                n_ff += 1
                for k, v in ld.items():
                    if k == "alpha":
                        continue
                    ff_acc[k] = ff_acc.get(k, 0.0) + abs(w) * v
        if spy_w > 0:
            spy_b = spy_acc
            notes.append("spy_hist")
        else:
            notes.append("spy_beta_unavailable")
    else:
        notes.append("spy_beta_unavailable")
    if n_ff:
        notes.append("ff_ken_french")
    else:
        notes.append("ff_unavailable")
    return FactorBook(
        hhi=round(hhi, 6),
        max_name=round(mx, 6),
        max_sector=round(msec, 6),
        spy_beta=round(spy_b, 6) if spy_b is not None else None,
        ff={k: round(v, 6) for k, v in ff_acc.items()},
        n_ff=n_ff,
        notes=tuple(notes),
    )
