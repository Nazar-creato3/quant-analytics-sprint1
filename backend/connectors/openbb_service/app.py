"""
Internal regulatory data sidecar.

OpenBB (AGPL) runs only inside this container. The main backend talks to this
service over HTTP — it never imports openbb packages directly.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Query

log = logging.getLogger("regulatory_sidecar")

app = FastAPI(
    title="Regulatory Data Service",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

try:
    from openbb import obb

    _OBB_READY = True
except ImportError:
    obb = None  # type: ignore[assignment,misc]
    _OBB_READY = False
    log.warning("OpenBB SDK not installed — sidecar will return 503 on data routes")


def _serialize_rows(result: Any) -> list[dict[str, Any]]:
    """Normalize OpenBB OBBject / DataFrame responses to JSON-safe dict rows."""
    if result is None:
        return []
    if hasattr(result, "to_dict"):
        try:
            records = result.to_dict("records")
            if isinstance(records, list):
                return [_json_safe(row) for row in records]
        except Exception:
            pass
    if hasattr(result, "results"):
        inner = result.results
        if isinstance(inner, list):
            return [_json_safe(item.model_dump() if hasattr(item, "model_dump") else item) for item in inner]
        if hasattr(inner, "to_dict"):
            try:
                records = inner.to_dict("records")
                if isinstance(records, list):
                    return [_json_safe(row) for row in records]
            except Exception:
                pass
    if isinstance(result, list):
        return [_json_safe(item) for item in result]
    if isinstance(result, dict):
        return [_json_safe(result)]
    return []


def _json_safe(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        raw = value.model_dump()
    elif isinstance(value, dict):
        raw = dict(value)
    else:
        raw = {"value": value}
    out: dict[str, Any] = {}
    for key, val in raw.items():
        if isinstance(val, (datetime, date)):
            out[key] = val.isoformat()
        elif val is None or isinstance(val, (str, int, float, bool)):
            out[key] = val
        else:
            out[key] = str(val)
    return out


@app.get("/health")
def health() -> dict[str, Any]:
    return {"status": "ok" if _OBB_READY else "degraded", "engine_ready": _OBB_READY}


@app.get("/v1/sec/filings")
def sec_filings(
    symbol: str = Query(..., min_length=1, max_length=16),
    limit: int = Query(20, ge=1, le=100),
    form_type: str | None = Query(None, max_length=32),
) -> dict[str, Any]:
    if not _OBB_READY:
        raise HTTPException(status_code=503, detail="Regulatory engine unavailable")
    ticker = symbol.strip().upper()
    kwargs: dict[str, Any] = {"limit": limit}
    if form_type:
        kwargs["form_type"] = form_type.strip().upper()
    try:
        # OpenBB SEC filings — filter by symbol when supported by installed version.
        try:
            result = obb.equity.discovery.filings(symbol=ticker, **kwargs)
        except TypeError:
            result = obb.equity.discovery.filings(**kwargs)
            rows = _serialize_rows(result)
            rows = [r for r in rows if str(r.get("symbol", "")).upper() == ticker][:limit]
            return {"symbol": ticker, "filings": rows, "count": len(rows)}
        rows = _serialize_rows(result)
        if rows and "symbol" in rows[0]:
            rows = [r for r in rows if str(r.get("symbol", "")).upper() == ticker][:limit]
        return {"symbol": ticker, "filings": rows[:limit], "count": min(len(rows), limit)}
    except Exception as exc:
        log.exception("sec filings fetch failed for %s", ticker)
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.get("/v1/finra/short-interest")
def finra_short_interest(
    symbol: str = Query(..., min_length=1, max_length=16),
    limit: int = Query(12, ge=1, le=52),
) -> dict[str, Any]:
    if not _OBB_READY:
        raise HTTPException(status_code=503, detail="Regulatory engine unavailable")
    ticker = symbol.strip().upper()
    try:
        result = obb.equity.shorts.short_interest(symbol=ticker, provider="finra")
        rows = _serialize_rows(result)[:limit]
        return {"symbol": ticker, "records": rows, "count": len(rows)}
    except Exception as exc:
        log.exception("finra short interest fetch failed for %s", ticker)
        raise HTTPException(status_code=502, detail=str(exc)) from exc
