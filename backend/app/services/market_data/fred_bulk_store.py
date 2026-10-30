"""Local FRED series cache — free macro overlay while Stooq equity bulk is flaky.

FRED is **macro** (VIX, yields, Fed funds, unemployment), not US ETF OHLCV.
Equity live/history stays on Yahoo / keyed providers / Stooq local when available.

Layout under FRED_BULK_DIR (default ``backend/data/fred``)::

    current/{SERIES_ID}.json   overwrite-only observations
    manifest.json
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from app.core.config import settings
from app.core.http_proxy import httpx_client_kwargs
from app.core.logging import get_logger

logger = get_logger(__name__)

# Desk + forecast-relevant US series (stable FRED ids).
DEFAULT_SERIES: tuple[tuple[str, str], ...] = (
    ("UNRATE", "безработица США, %"),
    ("FEDFUNDS", "ставка ФРС, %"),
    ("VIXCLS", "индекс страха VIX"),
    ("DGS10", "доходность 10 лет, %"),
    ("BAMLH0A0HYM2", "HY OAS, п.п."),
    ("CPIAUCSL", "CPI США"),
    ("DCOILBRENTEU", "Brent, $/барр."),
    ("DTWEXBGS", "доллар (broad)"),
    ("T10Y2Y", "наклон 10y–2y, п.п."),
    ("DGS2", "доходность 2 года, %"),
    ("DFII10", "реальная 10y TIPS, %"),
    ("T10YIE", "10y breakeven inflation, п.п."),
    ("PAYEMS", "занятость nonfarm, тыс."),
    ("PPIFIS", "PPI final demand"),
    ("JTSJOL", "JOLTS вакансии, тыс."),
)

# pandas_datareader extras (macro / factors — not equity OHLCV).
WB_SERIES: tuple[tuple[str, str, str], ...] = (
    # (cache_id, country, indicator)
    ("WB_US_GDP", "US", "NY.GDP.MKTP.CD"),
    ("WB_US_INFLATION", "US", "FP.CPI.TOTL.ZG"),
)
FF_DATASET = "F-F_Research_Data_Factors_daily"


def bulk_root() -> Path:
    raw = (settings.FRED_BULK_DIR or "").strip()
    if raw:
        return Path(raw)
    # Mirror Stooq layout: docker /app/data/fred, local backend/data/fred
    stooq = (settings.STOOQ_BULK_DIR or "").strip()
    if stooq:
        return Path(stooq).resolve().parent / "fred"
    return Path(settings.EUROSTAT_STORE_DIR).resolve().parent / "fred"


def ensure_layout(root: Path | None = None) -> Path:
    base = root or bulk_root()
    (base / "current").mkdir(parents=True, exist_ok=True)
    return base


def _manifest_path(root: Path | None = None) -> Path:
    return (root or bulk_root()) / "manifest.json"


def load_manifest(root: Path | None = None) -> dict[str, Any]:
    path = _manifest_path(root)
    if not path.is_file():
        return {"series": {}, "synced_at": None}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"series": {}, "synced_at": None}


def save_manifest(payload: dict[str, Any], root: Path | None = None) -> None:
    base = ensure_layout(root)
    path = _manifest_path(base)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def series_path(series_id: str, root: Path | None = None) -> Path:
    return ensure_layout(root) / "current" / f"{series_id.upper()}.json"


def read_series(series_id: str, root: Path | None = None) -> dict[str, Any] | None:
    path = series_path(series_id, root=root)
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def latest_observation(series_id: str, root: Path | None = None) -> dict[str, Any] | None:
    payload = read_series(series_id, root=root)
    if not payload:
        return None
    obs = [o for o in (payload.get("observations") or []) if o.get("value") not in {".", "", None}]
    if not obs:
        return None
    last = obs[-1]
    try:
        return {
            "id": series_id.upper(),
            "label": payload.get("label") or series_id,
            "value": float(last["value"]),
            "date": last.get("date"),
            "source": payload.get("source") or "fred_local",
        }
    except (TypeError, ValueError, KeyError):
        return None


def latest_observation_as_of(
    series_id: str,
    as_of: str | None = None,
    root: Path | None = None,
) -> dict[str, Any] | None:
    """Last print whose knowledge_time ≤ as_of. Monthly labor/CPI stay lagged."""
    from app.services.pit.clock import latest_visible, utc_today
    from app.services.pit.macro_panel import observations_from_fred_payload

    payload = read_series(series_id, root=root)
    last = latest_visible(observations_from_fred_payload(series_id, payload), as_of or utc_today())
    if last is None:
        return None
    return {
        "id": series_id.upper(),
        "label": (payload or {}).get("label") or series_id,
        "value": last.value,
        "date": last.event_time,
        "knowledge_time": last.knowledge_time,
        "source": (payload or {}).get("source") or "fred_local",
    }


def overview_macro_rows(root: Path | None = None) -> list[dict[str, Any]]:
    """Rows for MarketsOverview macro strip (cache-first)."""
    wanted = ("UNRATE", "FEDFUNDS", "VIXCLS", "DGS10")
    labels = {sid: label for sid, label in DEFAULT_SERIES}
    out: list[dict[str, Any]] = []
    for sid in wanted:
        row = latest_observation_as_of(sid, root=root)
        if not row:
            continue
        row["label"] = labels.get(sid, row.get("label") or sid)
        out.append(row)
    return out


_VINTAGE_SERIES = {
    "UNRATE",
    "PAYEMS",
    "CPIAUCSL",
    "PPIFIS",
    "JTSJOL",
}


async def _fetch_via_http(series_id: str, *, lookback_days: int = 400) -> list[dict[str, str]]:
    from app.services.macro_registry.fred_client import fetch_fred_series_json

    vintage = series_id.upper() in _VINTAGE_SERIES
    async with httpx.AsyncClient(**httpx_client_kwargs(foreign=True, timeout=20.0)) as client:
        raw = await fetch_fred_series_json(
            client,
            series_id,
            lookback_days=lookback_days,
            vintage=vintage,
        )
    payload = json.loads(raw)
    out: list[dict[str, str]] = []
    for o in payload.get("observations") or []:
        if o.get("value") in {".", "", None}:
            continue
        row = {"date": str(o.get("date") or ""), "value": str(o.get("value") or "")}
        if o.get("realtime_start"):
            row["realtime_start"] = str(o.get("realtime_start"))
        if o.get("realtime_end"):
            row["realtime_end"] = str(o.get("realtime_end"))
        out.append(row)
    return out


def _fetch_via_pandas_datareader(series_id: str, *, lookback_days: int = 400) -> list[dict[str, str]]:
    """Optional backend — same FRED API key, sync API."""
    try:
        import pandas_datareader.data as web
    except ImportError as exc:
        raise RuntimeError("pandas_datareader not installed") from exc

    key = (settings.FRED_API_KEY or "").strip()
    if not key:
        raise RuntimeError("FRED_API_KEY not configured")
    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=lookback_days)
    df = web.DataReader(series_id, "fred", start, end, api_key=key)
    if df is None or df.empty:
        return []
    col = df.columns[0]
    out: list[dict[str, str]] = []
    for idx, val in df[col].dropna().items():
        try:
            day = idx.date().isoformat() if hasattr(idx, "date") else str(idx)[:10]
            out.append({"date": day, "value": str(float(val))})
        except (TypeError, ValueError):
            continue
    return out


async def fetch_series_observations(series_id: str, *, lookback_days: int = 400) -> tuple[list[dict[str, str]], str]:
    """HTTP FRED first; pandas_datareader fallback. Returns (obs, source)."""
    try:
        obs = await _fetch_via_http(series_id, lookback_days=lookback_days)
        if obs:
            return obs, "fred_http"
    except Exception as exc:
        logger.debug("fred_http_failed", series=series_id, error=str(exc)[:160])

    try:
        obs = await asyncio.to_thread(
            _fetch_via_pandas_datareader, series_id, lookback_days=lookback_days
        )
        if obs:
            return obs, "fred_pandas_datareader"
    except Exception as exc:
        logger.debug("fred_pdr_failed", series=series_id, error=str(exc)[:160])

    return [], "none"


async def sync_fred_bulk(*, series: list[tuple[str, str]] | None = None) -> dict[str, Any]:
    """Overwrite-sync curated FRED + pandas_datareader macro/factor packs."""
    if not (settings.FRED_API_KEY or "").strip():
        return {
            "ok": False,
            "status": "no_api_key",
            "hint": "Set FRED_API_KEY in env",
            "root": str(bulk_root()),
        }

    base = ensure_layout()
    catalog = series or list(DEFAULT_SERIES)
    synced: dict[str, Any] = {}
    errors: list[dict[str, str]] = []

    for sid, label in catalog:
        try:
            obs, source = await fetch_series_observations(sid)
            if not obs:
                errors.append({"series": sid, "error": "empty"})
                continue
            payload = {
                "series_id": sid.upper(),
                "label": label,
                "source": source,
                "synced_at": datetime.now(timezone.utc).isoformat(),
                "observations": obs,
            }
            path = series_path(sid, root=base)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)
            synced[sid.upper()] = {
                "label": label,
                "points": len(obs),
                "last": obs[-1].get("date"),
                "source": source,
            }
        except Exception as exc:
            errors.append({"series": sid, "error": str(exc)[:160]})

    # World Bank via pandas_datareader (free, no key)
    for cache_id, country, indicator in WB_SERIES:
        try:
            obs = await asyncio.to_thread(_fetch_world_bank, country, indicator)
            if not obs:
                errors.append({"series": cache_id, "error": "empty_wb"})
                continue
            payload = {
                "series_id": cache_id,
                "label": f"World Bank {country} {indicator}",
                "source": "pdr_world_bank",
                "synced_at": datetime.now(timezone.utc).isoformat(),
                "observations": obs,
            }
            path = series_path(cache_id, root=base)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)
            synced[cache_id] = {
                "label": payload["label"],
                "points": len(obs),
                "last": obs[-1].get("date"),
                "source": "pdr_world_bank",
            }
        except Exception as exc:
            errors.append({"series": cache_id, "error": str(exc)[:160]})

    # Fama–French daily factors (quant / forecast features)
    try:
        ff = await asyncio.to_thread(_fetch_fama_french_daily)
        if ff:
            path = ensure_layout(base) / "current" / "FF_DAILY_FACTORS.json"
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(ff, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)
            synced["FF_DAILY_FACTORS"] = {
                "label": "Fama-French daily factors",
                "points": len(ff.get("rows") or []),
                "last": (ff.get("rows") or [{}])[-1].get("date"),
                "source": "pdr_famafrench",
            }
    except Exception as exc:
        errors.append({"series": "FF_DAILY_FACTORS", "error": str(exc)[:160]})

    if not synced:
        existing = load_manifest(base)
        return {
            "ok": False,
            "status": "sync_failed",
            "kept_previous": bool(existing.get("series")),
            "errors": errors,
            "root": str(base),
            "synced_at": existing.get("synced_at"),
        }

    prev = load_manifest(base)
    series_meta = dict(prev.get("series") or {})
    series_meta.update(synced)
    manifest = {
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "series": series_meta,
        "errors": errors,
        "overwrite": True,
    }
    save_manifest(manifest, base)
    return {
        "ok": True,
        "status": "synced",
        "series_count": len(synced),
        "series": synced,
        "errors": errors,
        "synced_at": manifest["synced_at"],
        "root": str(base),
        "overwrite": True,
    }


def _fetch_world_bank(country: str, indicator: str) -> list[dict[str, str]]:
    from pandas_datareader import wb

    end_year = datetime.now(timezone.utc).year
    df = wb.download(indicator=indicator, country=[country], start=end_year - 15, end=end_year)
    if df is None or df.empty:
        return []
    col = df.columns[0]
    out: list[dict[str, str]] = []
    for idx, val in df[col].dropna().items():
        try:
            # idx is often (country, year)
            year = idx[1] if isinstance(idx, tuple) and len(idx) > 1 else idx
            day = f"{int(year)}-12-31"
            out.append({"date": day, "value": str(float(val))})
        except (TypeError, ValueError):
            continue
    out.sort(key=lambda r: r["date"])
    return out


def _fetch_fama_french_daily() -> dict[str, Any] | None:
    import pandas_datareader.data as web

    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=800)
    raw = web.DataReader(FF_DATASET, "famafrench", start, end)
    # famafrench returns dict of DataFrames; 0 is usually the factor table
    if not isinstance(raw, dict) or not raw:
        return None
    df = raw.get(0)
    if df is None or getattr(df, "empty", True):
        return None
    rows: list[dict[str, Any]] = []
    for idx, row in df.tail(500).iterrows():
        try:
            if hasattr(idx, "strftime"):
                day = idx.strftime("%Y-%m-%d")
            else:
                # period index YYYYMM
                s = str(idx).replace("-", "")[:8]
                if len(s) == 6:
                    day = f"{s[:4]}-{s[4:6]}-28"
                elif len(s) >= 8:
                    day = f"{s[:4]}-{s[4:6]}-{s[6:8]}"
                else:
                    day = str(idx)[:10]
            item = {"date": day}
            for col in df.columns:
                item[str(col)] = float(row[col])
            rows.append(item)
        except (TypeError, ValueError):
            continue
    if not rows:
        return None
    return {
        "dataset": FF_DATASET,
        "source": "pdr_famafrench",
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "rows": rows,
    }


def store_status(root: Path | None = None) -> dict[str, Any]:
    base = root or bulk_root()
    manifest = load_manifest(base)
    return {
        "root": str(base),
        "synced_at": manifest.get("synced_at"),
        "series_count": len(manifest.get("series") or {}),
        "series": manifest.get("series") or {},
        "overwrite": True,
        "api_key_configured": bool((settings.FRED_API_KEY or "").strip()),
    }
