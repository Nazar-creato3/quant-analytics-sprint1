"""Public Eurostat ESI + CFTC COT — QC-equivalent *ideas* without LEAN files.

Network is optional. Failures return empty cache; digest must still build.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from app.core.http_proxy import httpx_client_kwargs
from app.services.terminal_platform.providers.public_macro import _jsonstat_time_values

EUROSTAT_BASE = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"
CFTC_TFF_URL = "https://publicreporting.cftc.gov/resource/jun7-fc8e.json"

ESI_SPECS: tuple[tuple[str, str, dict[str, str]], ...] = (
    ("esi_consumer", "ei_bsco_m", {"geo": "EA", "indic": "BS-CSMCI", "s_adj": "SA"}),
    ("esi_industry", "ei_bsin_m", {"geo": "EA", "indic": "BS-ICI", "s_adj": "SA"}),
)


def _cache_path() -> Path:
    from app.services.market_data.fred_bulk_store import bulk_root

    path = bulk_root() / "current" / "PUBLIC_ALT.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def latest_jsonstat_value(payload: dict[str, Any]) -> float | None:
    rows = _jsonstat_time_values(payload)
    if not rows:
        return None
    try:
        return float(rows[-1]["value"])
    except (KeyError, TypeError, ValueError):
        return None


def cftc_lev_money_net_share(rows: list[Any]) -> float | None:
    """Net leveraged-money / open interest in [-1, 1]."""
    if not rows:
        return None
    row = rows[0] if isinstance(rows[0], dict) else None
    if not row:
        return None

    def _f(*keys: str) -> float | None:
        for k in keys:
            if k in row and row[k] not in (None, ""):
                try:
                    return float(row[k])
                except (TypeError, ValueError):
                    continue
        return None

    long_ = _f("lev_money_positions_long_all", "lev_money_positions_long")
    short_ = _f("lev_money_positions_short_all", "lev_money_positions_short")
    oi = _f("open_interest_all", "open_interest")
    if long_ is None or short_ is None or not oi or oi <= 0:
        return None
    return max(-1.0, min(1.0, (long_ - short_) / oi))


def _get_json(url: str, params: dict[str, str] | None = None, *, timeout: float = 8.0) -> Any:
    kwargs = httpx_client_kwargs(foreign=True, timeout=httpx.Timeout(timeout, connect=4.0))
    with httpx.Client(**kwargs) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


def fetch_esi_snapshot() -> dict[str, float]:
    out: dict[str, float] = {}
    for key, dataset, extra in ESI_SPECS:
        url = f"{EUROSTAT_BASE}/{dataset}"
        params = {"format": "JSON", "lang": "EN", "lastTimePeriod": "8", **extra}
        try:
            payload = _get_json(url, params)
            if isinstance(payload, dict):
                val = latest_jsonstat_value(payload)
                if val is not None:
                    out[key] = val
        except Exception:
            continue
    return out


def fetch_cftc_es_net_share() -> float | None:
    params = {
        "$limit": "8",
        "$order": "report_date_as_yyyy_mm_dd DESC",
        "$where": "upper(contract_market_name) like '%E-MINI S&P 500%'",
    }
    try:
        payload = _get_json(CFTC_TFF_URL, params, timeout=10.0)
        rows = payload if isinstance(payload, list) else []
        return cftc_lev_money_net_share(rows)
    except Exception:
        return None


def load_public_alt_cache() -> dict[str, Any]:
    path = _cache_path()
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def refresh_public_alt_cache() -> dict[str, Any]:
    """Best-effort; never raise into the digest."""
    esi = {}
    cftc = None
    try:
        esi = fetch_esi_snapshot()
    except Exception:
        esi = {}
    try:
        cftc = fetch_cftc_es_net_share()
    except Exception:
        cftc = None
    licensed: dict[str, Any] = {}
    try:
        from app.services.quant_desk.fundamental_fa import refresh_fa_universe

        refresh_fa_universe()
    except Exception:
        pass
    try:
        from app.services.quant_desk.licensed_alt import snapshot_licensed_alt

        licensed = snapshot_licensed_alt()
    except Exception:
        licensed = {}
    payload = {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "esi_consumer": esi.get("esi_consumer"),
        "esi_industry": esi.get("esi_industry"),
        "cftc_es_lev_net_share": cftc,
        **licensed,
    }
    try:
        _cache_path().write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass
    return payload
