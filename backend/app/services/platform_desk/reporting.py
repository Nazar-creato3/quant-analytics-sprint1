"""Client reporting: tear metrics (QuantStats if present), Brinson-lite, Euler RC."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

from app.core.config import settings


def _book_dir() -> Path:
    raw = getattr(settings, "DAILY_BOOK_DIR", "") or ""
    return Path(raw) if raw.strip() else Path("/app/data/daily_books")


def tear_metrics(returns: Sequence[float]) -> dict[str, Any]:
    """Own metrics always. QuantStats extras when the package is installed."""
    r = np.asarray([float(x) for x in returns if x is not None], dtype=float)
    out: dict[str, Any] = {"n": int(r.size), "quantstats": False}
    if r.size < 2:
        out["note"] = "thin_sample"
        return out
    mu = float(r.mean())
    sig = float(r.std(ddof=1)) or 1e-12
    down = r[r < 0]
    dsig = float(down.std(ddof=1)) if down.size > 1 else sig
    wealth = np.cumprod(1.0 + r)
    peak = np.maximum.accumulate(wealth)
    dd = wealth / np.clip(peak, 1e-12, None) - 1.0
    maxdd = float(dd.min())
    ann = 252.0
    cagr = float(wealth[-1] ** (ann / r.size) - 1.0) if wealth[-1] > 0 else -1.0
    out.update(
        {
            "mean": round(mu, 6),
            "vol": round(sig, 6),
            "sharpe": round(mu / sig * np.sqrt(ann), 4),
            "sortino": round(mu / (dsig or 1e-12) * np.sqrt(ann), 4),
            "max_dd": round(maxdd, 6),
            "cagr": round(cagr, 6),
            "calmar": round(cagr / abs(maxdd), 4) if maxdd < 0 else None,
            "hit_rate": round(float(np.mean(r > 0)), 4),
            "win_loss": round(
                float(r[r > 0].mean() / abs(float(r[r < 0].mean()))) if np.any(r < 0) and np.any(r > 0) else 0.0,
                4,
            ),
        }
    )
    try:
        import pandas as pd
        import quantstats as qs

        s = pd.Series(r)
        out["quantstats"] = True
        out["qs_sharpe"] = round(float(qs.stats.sharpe(s)), 4)
        out["qs_max_dd"] = round(float(qs.stats.max_drawdown(s)), 6)
    except Exception:
        pass
    return out


def brinson_lite(
    port_w: Mapping[str, float],
    bench_w: Mapping[str, float],
    port_ret: Mapping[str, float],
    bench_ret: Mapping[str, float],
) -> dict[str, Any]:
    """Sector Brinson: allocation + selection + interaction. Missing bench → equal sectors."""
    sectors = sorted(set(port_w) | set(bench_w) | set(port_ret) | set(bench_ret))
    if not sectors:
        return {"allocation": 0.0, "selection": 0.0, "interaction": 0.0, "active": 0.0, "sectors": []}
    bw = {s: float(bench_w.get(s) or 0.0) for s in sectors}
    if sum(abs(v) for v in bw.values()) <= 1e-12:
        eq = 1.0 / len(sectors)
        bw = {s: eq for s in sectors}
    pw = {s: float(port_w.get(s) or 0.0) for s in sectors}
    rb = {s: float(bench_ret.get(s) or 0.0) for s in sectors}
    rp = {s: float(port_ret.get(s) or rb[s]) for s in sectors}
    rB = sum(bw[s] * rb[s] for s in sectors)
    alloc = sel = inter = 0.0
    rows = []
    for s in sectors:
        a = (pw[s] - bw[s]) * (rb[s] - rB)
        e = bw[s] * (rp[s] - rb[s])
        i = (pw[s] - bw[s]) * (rp[s] - rb[s])
        alloc += a
        sel += e
        inter += i
        rows.append(
            {
                "sector": s,
                "port_w": round(pw[s], 6),
                "bench_w": round(bw[s], 6),
                "allocation": round(a, 8),
                "selection": round(e, 8),
                "interaction": round(i, 8),
            }
        )
    return {
        "allocation": round(alloc, 8),
        "selection": round(sel, 8),
        "interaction": round(inter, 8),
        "active": round(alloc + sel + inter, 8),
        "sectors": rows,
    }


def risk_contributions(
    weights: Sequence[float],
    symbols: Sequence[str],
    hist: Mapping[str, Sequence[float]] | None = None,
    vols: Sequence[float] | None = None,
) -> list[dict[str, Any]]:
    """Euler RC: w ⊙ Σw / (w'Σw). Diagonal vol² if the panel is thin."""
    n = min(len(weights), len(symbols))
    if n == 0:
        return []
    w = np.asarray([float(weights[i]) for i in range(n)], dtype=float)
    cov = None
    if hist:
        cols = []
        ok = True
        for i in range(n):
            s = [float(x) for x in (hist.get(str(symbols[i]).upper()) or [])]
            if len(s) < 12:
                ok = False
                break
            cols.append(np.asarray(s, dtype=float))
        if ok and cols:
            t = min(c.size for c in cols)
            R = np.column_stack([c[-t:] for c in cols])
            if t >= 12:
                cov = np.cov(R, rowvar=False, ddof=1)
    if cov is None:
        v = [float(vols[i]) if vols and i < len(vols) else 0.20 for i in range(n)]
        cov = np.diag(np.square(np.asarray(v, dtype=float)))
    mrc = cov @ w
    port_var = float(w @ mrc)
    rows = []
    for i in range(n):
        rc = float(w[i] * mrc[i])
        rows.append(
            {
                "symbol": str(symbols[i]).upper(),
                "weight": round(float(w[i]), 6),
                "mrc": round(float(mrc[i]), 8),
                "rc": round(rc, 8),
                "rc_pct": round(rc / port_var, 6) if abs(port_var) > 1e-18 else 0.0,
            }
        )
    return rows


def _sector_weights(holdings: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    by: dict[str, float] = {}
    for h in holdings:
        sec = str(h.get("sector") or "UNK")
        by[sec] = by.get(sec, 0.0) + abs(float(h.get("weight") or 0.0))
    s = sum(by.values())
    if s <= 0:
        return by
    return {k: v / s for k, v in by.items()}


def _sector_returns(
    holdings: Sequence[Mapping[str, Any]],
    asset_returns: Mapping[str, float],
) -> dict[str, float]:
    acc: dict[str, list[tuple[float, float]]] = {}
    for h in holdings:
        sym = str(h.get("symbol") or "").upper()
        if sym not in asset_returns:
            continue
        sec = str(h.get("sector") or "UNK")
        acc.setdefault(sec, []).append((abs(float(h.get("weight") or 0.0)), float(asset_returns[sym])))
    out: dict[str, float] = {}
    for sec, pairs in acc.items():
        tw = sum(w for w, _ in pairs)
        out[sec] = sum(w * r for w, r in pairs) / tw if tw else 0.0
    return out


def build_client_pack(
    *,
    book: Mapping[str, Any] | None,
    realized: Mapping[str, Any] | None,
    excess_hist: Sequence[float] | None = None,
    hist_returns: Mapping[str, Sequence[float]] | None = None,
    bench_sector_w: Mapping[str, float] | None = None,
    bench_sector_ret: Mapping[str, float] | None = None,
    asset_returns: Mapping[str, float] | None = None,
) -> dict[str, Any]:
    holdings = list((book or {}).get("holdings") or [])
    if not holdings and realized:
        holdings = list(realized.get("holdings") or [])
    sector_src: dict[str, str] = {}
    for src in (
        (book or {}).get("construction") or {},
        ((book or {}).get("sleeves") or {}).get("retail_long_only") or {},
    ):
        for h in src.get("holdings") or []:
            if isinstance(h, Mapping) and h.get("symbol") and h.get("sector"):
                sector_src[str(h["symbol"]).upper()] = str(h["sector"])
    if sector_src:
        enriched = []
        for h in holdings:
            row = dict(h)
            if not row.get("sector") or row.get("sector") == "UNK":
                row["sector"] = sector_src.get(str(row.get("symbol") or "").upper(), row.get("sector") or "UNK")
            enriched.append(row)
        holdings = enriched
    rets = list(excess_hist or [])
    if realized and realized.get("excess") is not None:
        rets = rets + [float(realized["excess"])]
    tear = tear_metrics(rets)
    pw = _sector_weights(holdings)
    brinson = brinson_lite(
        pw,
        dict(bench_sector_w or {}),
        _sector_returns(holdings, asset_returns or {}),
        dict(bench_sector_ret or {}),
    )
    symbols = [str(h.get("symbol") or "").upper() for h in holdings]
    weights = [float(h.get("weight") or 0.0) for h in holdings]
    rc = risk_contributions(weights, symbols, hist=hist_returns)
    return {
        "as_of": str((realized or book or {}).get("as_of") or datetime.now(timezone.utc).strftime("%Y-%m-%d")),
        "tear": tear,
        "brinson": brinson,
        "risk_contribution": rc,
        "holdings_n": len(holdings),
        "note_ru": "Клиентский pack: метрики на excess, Brinson по секторам, Euler RC. Не vendor attribution.",
    }


def _safe_uid(user_id: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._@+-" else "_" for ch in str(user_id).strip()) or "paper"


def _pack_dir(user_id: str = "paper") -> Path:
    return _book_dir() / "clients" / _safe_uid(user_id)


def persist_client_pack(payload: Mapping[str, Any], *, user_id: str = "paper") -> Path | None:
    folder = _pack_dir(user_id)
    day = str(payload.get("as_of") or datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    try:
        folder.mkdir(parents=True, exist_ok=True)
        body = dict(payload)
        body["user_id"] = str(user_id)
        path = folder / f"{day}.client.json"
        path.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
        latest = folder / "latest.client.json"
        latest.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
    except OSError:
        return None


def load_latest_client_pack(*, user_id: str = "paper") -> dict[str, Any] | None:
    folder = _pack_dir(user_id)
    path = folder / "latest.client.json"
    if not path.is_file():
        files = sorted(folder.glob("????-??-??.client.json"))
        path = files[-1] if files else path
    if not path.is_file():
        return None
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(row, dict):
            return None
        owner = str(row.get("user_id") or user_id)
        if owner != str(user_id):
            return None
        return row
    except (OSError, json.JSONDecodeError):
        return None
