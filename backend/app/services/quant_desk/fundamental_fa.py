"""FundamentalAnalysis / FinanceToolkit / FMP free-tier fundamentals.

``FundamentalAnalysis`` (Jeroen Bouma) is deprecated upstream in favor of
``financetoolkit``. We accept either; both need ``FMP_API_KEY``. Disk cache
limits free-plan burn (~250 calls/day).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import settings

# Liquid names for desk tilt — keep small on free FMP.
DEFAULT_SYMBOLS: tuple[str, ...] = ("SPY", "QQQ", "AAPL", "MSFT", "NVDA")
CACHE_TTL_HOURS = 20


def _api_key() -> str:
    return str(getattr(settings, "FMP_API_KEY", "") or "").strip()


def _cache_dir() -> Path:
    try:
        from app.services.market_data.fred_bulk_store import bulk_root

        root = bulk_root() / "current" / "fa_fmp"
    except Exception:
        root = Path(__file__).resolve().parents[3] / "data" / "fred" / "current" / "fa_fmp"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _cache_path(symbol: str) -> Path:
    return _cache_dir() / f"{symbol.strip().upper()}.json"


def _fresh(path: Path) -> bool:
    if not path.is_file():
        return False
    age_h = (datetime.now(timezone.utc).timestamp() - path.stat().st_mtime) / 3600.0
    return age_h < CACHE_TTL_HOURS


def _load_cache(symbol: str) -> dict[str, Any] | None:
    path = _cache_path(symbol)
    if not _fresh(path):
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def _save_cache(symbol: str, row: dict[str, Any]) -> None:
    path = _cache_path(symbol)
    try:
        path.write_text(json.dumps(row, ensure_ascii=False, default=str), encoding="utf-8")
    except Exception:
        pass


def _backend() -> str:
    try:
        import FundamentalAnalysis as fa  # noqa: F401

        return "fundamentalanalysis"
    except Exception:
        pass
    try:
        from financetoolkit import Toolkit  # noqa: F401

        return "financetoolkit"
    except Exception:
        return "fmp_http"


def _via_fundamentalanalysis(symbol: str, key: str) -> dict[str, Any]:
    import FundamentalAnalysis as fa

    profile = fa.profile(symbol, key)
    ratios = fa.financial_ratios(symbol, key, period="annual")
    out: dict[str, Any] = {"symbol": symbol, "source": "fundamentalanalysis"}
    if hasattr(profile, "to_dict"):
        pdata = profile.to_dict()
        # FA profile is often a Series indexed by field
        if isinstance(pdata, dict):
            # Series.to_dict -> {field: value} or {0: {field: value}}
            flat = pdata.get(0) if 0 in pdata and isinstance(pdata.get(0), dict) else pdata
            if isinstance(flat, dict):
                out["pe"] = flat.get("priceEarningsRatio") or flat.get("pe")
                out["beta"] = flat.get("beta")
                out["mkt_cap"] = flat.get("mktCap") or flat.get("marketCap")
                out["sector"] = flat.get("sector")
    if hasattr(ratios, "iloc") and len(ratios.columns):
        col = ratios.columns[0]
        series = ratios[col]
        out["roe"] = _num(series.get("returnOnEquity") if hasattr(series, "get") else None)
        out["roa"] = _num(series.get("returnOnAssets") if hasattr(series, "get") else None)
        out["debt_to_equity"] = _num(series.get("debtEquityRatio") if hasattr(series, "get") else None)
        out["current_ratio"] = _num(series.get("currentRatio") if hasattr(series, "get") else None)
        out["net_margin"] = _num(series.get("netProfitMargin") if hasattr(series, "get") else None)
        if out.get("pe") is None:
            out["pe"] = _num(series.get("priceEarningsRatio") if hasattr(series, "get") else None)
    return {k: v for k, v in out.items() if v is not None}


def _num(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _via_financetoolkit(symbol: str, key: str) -> dict[str, Any]:
    from financetoolkit import Toolkit

    tk = Toolkit([symbol], api_key=key, progress_bar=False)
    out: dict[str, Any] = {"symbol": symbol, "source": "financetoolkit"}
    try:
        ratios = tk.ratios.collect_profitability_ratios()
        if hasattr(ratios, "empty") and not ratios.empty:
            # MultiIndex columns (metric, ticker) or (ticker,)
            for metric in ("Return on Equity", "Return on Assets", "Net Profit Margin"):
                if metric in ratios.index:
                    row = ratios.loc[metric]
                    val = row.iloc[-1] if hasattr(row, "iloc") else row
                    if hasattr(val, "iloc"):
                        val = val.iloc[0]
                    key_map = {
                        "Return on Equity": "roe",
                        "Return on Assets": "roa",
                        "Net Profit Margin": "net_margin",
                    }
                    out[key_map[metric]] = _num(val)
    except Exception:
        pass
    try:
        vals = tk.ratios.collect_valuation_ratios()
        if hasattr(vals, "empty") and not vals.empty:
            for metric in ("Price-to-Earnings Ratio", "Price to Earnings Ratio", "PE Ratio"):
                if metric in vals.index:
                    row = vals.loc[metric]
                    val = row.iloc[-1] if hasattr(row, "iloc") else row
                    if hasattr(val, "iloc"):
                        val = val.iloc[0]
                    out["pe"] = _num(val)
                    break
    except Exception:
        pass
    return {k: v for k, v in out.items() if v is not None}


def _via_fmp_http(symbol: str) -> dict[str, Any]:
    """Sync FMP v3 profile + key-metrics (same free key)."""
    import httpx

    from app.core.http_proxy import httpx_client_kwargs

    key = _api_key()
    if not key:
        return {}
    base = "https://financialmodelingprep.com/api/v3"
    kwargs = httpx_client_kwargs(foreign=True, timeout=httpx.Timeout(12.0, connect=4.0))
    out: dict[str, Any] = {"symbol": symbol, "source": "fmp_http"}
    try:
        with httpx.Client(**kwargs) as client:
            profile = client.get(f"{base}/profile/{symbol}", params={"apikey": key})
            profile.raise_for_status()
            prow = profile.json()
            row = prow[0] if isinstance(prow, list) and prow else (prow if isinstance(prow, dict) else {})
            out["pe"] = _num(row.get("pe"))
            out["beta"] = _num(row.get("beta"))
            out["mkt_cap"] = _num(row.get("mktCap"))
            out["sector"] = row.get("sector")
            metrics = client.get(f"{base}/key-metrics/{symbol}", params={"apikey": key, "limit": 1})
            metrics.raise_for_status()
            mraw = metrics.json()
            mrow = mraw[0] if isinstance(mraw, list) and mraw else {}
            if out.get("pe") is None:
                out["pe"] = _num(mrow.get("peRatio") or mrow.get("peRatioTTM"))
            out["roe"] = _num(mrow.get("roe") or mrow.get("returnOnEquity"))
            out["roa"] = _num(mrow.get("roa") or mrow.get("returnOnAssets"))
            out["debt_to_equity"] = _num(mrow.get("debtToEquity"))
            out["current_ratio"] = _num(mrow.get("currentRatio"))
            out["net_margin"] = _num(mrow.get("netProfitMargin"))
    except Exception:
        return {}
    return {k: v for k, v in out.items() if v is not None}


def fetch_fundamentals(symbol: str, *, force: bool = False) -> dict[str, Any]:
    """Profile + key ratios for one ticker. Uses cache unless force=True."""
    sym = symbol.strip().upper()
    if not sym:
        return {}
    if not force:
        cached = _load_cache(sym)
        if cached:
            return cached
    key = _api_key()
    if not key:
        return {}
    row: dict[str, Any] = {}
    backend = _backend()
    try:
        if backend == "fundamentalanalysis":
            row = _via_fundamentalanalysis(sym, key)
        elif backend == "financetoolkit":
            row = _via_financetoolkit(sym, key)
        else:
            row = _via_fmp_http(sym)
    except Exception:
        row = _via_fmp_http(sym)
    if row:
        row["as_of"] = datetime.now(timezone.utc).isoformat()
        row["backend"] = backend
        _save_cache(sym, row)
    return row


def spy_pe_tilt() -> float | None:
    from app.services.quant_desk.licensed_alt import pe_to_growth_tilt

    row = fetch_fundamentals("SPY")
    return pe_to_growth_tilt(_num(row.get("pe")))


def refresh_fa_universe(symbols: tuple[str, ...] | None = None) -> dict[str, Any]:
    """Best-effort nightly: only miss/stale symbols to spare free quota."""
    syms = symbols or DEFAULT_SYMBOLS
    out: dict[str, Any] = {"backend": _backend(), "rows": {}, "skipped_fresh": []}
    for sym in syms:
        if _load_cache(sym):
            out["skipped_fresh"].append(sym)
            continue
        row = fetch_fundamentals(sym, force=True)
        if row:
            out["rows"][sym] = {k: row.get(k) for k in ("pe", "roe", "roa", "source", "backend")}
    return out
