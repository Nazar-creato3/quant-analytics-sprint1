"""Alt signals: QuantConnect LEAN dump first, then vendor REST / local PIT.

Official drop folder: QUANTCONNECT_DATA_DIR (`lean data download` from your QC
account). HTTP only fills gaps when a vendor key is set. Empty key → no HTTP.
Spectral ticks: latest small CSV / SPECTRAL_FLOW.json, not full tape replay.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from app.core.config import settings
from app.core.http_proxy import httpx_client_kwargs

_POS = ("beat", "surge", "rally", "upgrade", "record", "bullish", "soar")
_NEG = ("miss", "plunge", "downgrade", "bankrupt", "fraud", "bearish", "crash")


def _clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _key(attr: str) -> str:
    return str(getattr(settings, attr, "") or "").strip()


def _get_json(url: str, *, headers: dict[str, str] | None = None, params: dict[str, Any] | None = None) -> Any:
    kwargs = httpx_client_kwargs(foreign=True, timeout=httpx.Timeout(8.0, connect=4.0))
    with httpx.Client(**kwargs) as client:
        resp = client.get(url, headers=headers, params=params)
        resp.raise_for_status()
        return resp.json()


def _local_json(*rel: str) -> dict[str, Any]:
    roots: list[Path] = []
    try:
        from app.services.market_data.fred_bulk_store import bulk_root

        roots.append(bulk_root() / "current")
    except Exception:
        pass
    for attr in ("TIER_C_STORE_DIR", "PIT_STORE_DIR"):
        raw = str(getattr(settings, attr, "") or "").strip()
        if raw:
            roots.append(Path(raw))
    for root in roots:
        for name in rel:
            path = root / name
            if path.is_file():
                try:
                    payload = json.loads(path.read_text(encoding="utf-8"))
                    if isinstance(payload, dict):
                        return payload
                except Exception:
                    continue
    return {}


def brain_row_sentiment(row: dict[str, Any]) -> float | None:
    for key in (
        "sentiment_7d",
        "SENTIMENT_7D",
        "sentiment_7_days",
        "bsi_7d",
        "score",
        "sentiment",
    ):
        if key in row and row[key] not in (None, ""):
            try:
                return _clip(float(row[key]))
            except (TypeError, ValueError):
                continue
    return None


def benzinga_headline_tilt(items: list[Any]) -> float | None:
    if not items:
        return None
    score = 0.0
    n = 0
    for item in items[:60]:
        if not isinstance(item, dict):
            continue
        raw = item.get("sentiment") or item.get("sentimentScore")
        if raw not in (None, ""):
            try:
                score += float(raw)
                n += 1
                continue
            except (TypeError, ValueError):
                pass
        text = " ".join(
            str(item.get(k) or "") for k in ("title", "headline", "teaser", "body")
        ).lower()
        if not text.strip():
            continue
        n += 1
        if any(w in text for w in _POS):
            score += 1.0
        if any(w in text for w in _NEG):
            score -= 1.0
    if n <= 0:
        return None
    return _clip(score / n)


def congress_net_tilt(rows: list[Any]) -> float | None:
    if not rows:
        return None
    buys = sales = 0
    for row in rows[:120]:
        if not isinstance(row, dict):
            continue
        t = str(row.get("Transaction") or row.get("transaction") or row.get("Type") or "").lower()
        if "purchase" in t or t in {"buy", "bought"}:
            buys += 1
        elif "sale" in t or "sell" in t:
            sales += 1
    n = buys + sales
    if n <= 0:
        return None
    return _clip((buys - sales) / n)


def spectral_ofi_tilt(row: dict[str, Any]) -> float | None:
    for key in ("ofi", "order_flow_imbalance", "imbalance", "trade_imbalance"):
        if key in row and row[key] not in (None, ""):
            try:
                return _clip(float(row[key]))
            except (TypeError, ValueError):
                continue
    return None


def pe_to_growth_tilt(pe: float | None) -> float | None:
    if pe is None or pe <= 0:
        return None
    return _clip((float(pe) - 18.0) / 12.0)


def fetch_brain_tilt() -> float | None:
    local = _local_json("BRAIN_BSI.json", "brain.json")
    sent = brain_row_sentiment(local)
    if sent is not None:
        return sent
    base = _key("BRAIN_API_BASE_URL").rstrip("/")
    token = _key("BRAIN_API_KEY")
    if not base or not token:
        return None
    try:
        payload = _get_json(
            f"{base}/bsi",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            params={"ticker": "SPY"},
        )
        row = payload if isinstance(payload, dict) else {}
        if isinstance(payload, list) and payload and isinstance(payload[0], dict):
            row = payload[0]
        return brain_row_sentiment(row)
    except Exception:
        return None


def fetch_benzinga_tilt() -> float | None:
    token = _key("BENZINGA_API_KEY")
    if not token:
        return None
    try:
        payload = _get_json(
            "https://api.benzinga.com/api/v2/news",
            headers={"Authorization": f"token {token}", "Accept": "application/json"},
            params={"pageSize": 40, "displayOutput": "headline"},
        )
        items = payload if isinstance(payload, list) else payload.get("news") or []
        return benzinga_headline_tilt(items if isinstance(items, list) else [])
    except Exception:
        return None


def fetch_quiver_congress_tilt() -> float | None:
    token = _key("QUIVER_API_KEY")
    if not token:
        return None
    try:
        payload = _get_json(
            "https://api.quiverquant.com/beta/live/congresstrading",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        rows = payload if isinstance(payload, list) else payload.get("data") or []
        return congress_net_tilt(rows if isinstance(rows, list) else [])
    except Exception:
        return None


def fetch_morningstar_pe_tilt() -> float | None:
    """Morningstar if licensed; else free FMP via FundamentalAnalysis/FinanceToolkit."""
    local = _local_json("MORNINGSTAR.json", "morningstar.json")
    pe = None
    for key in ("pe", "pe_ttm", "peRatioTTM", "trailingPE"):
        if local.get(key) not in (None, ""):
            try:
                pe = float(local[key])
                break
            except (TypeError, ValueError):
                continue
    if pe is None:
        ms_key = _key("MORNINGSTAR_API_KEY")
        ms_base = _key("MORNINGSTAR_API_BASE_URL").rstrip("/")
        if ms_key and ms_base:
            try:
                payload = _get_json(
                    ms_base,
                    headers={"Authorization": f"Bearer {ms_key}", "Accept": "application/json"},
                    params={"symbol": "SPY"},
                )
                row = payload if isinstance(payload, dict) else {}
                for key in ("pe", "pe_ttm", "peRatioTTM"):
                    if row.get(key) not in (None, ""):
                        pe = float(row[key])
                        break
            except Exception:
                pe = None
    if pe is None:
        try:
            from app.services.quant_desk.fundamental_fa import spy_pe_tilt

            return spy_pe_tilt()
        except Exception:
            return None
    return pe_to_growth_tilt(pe)


def fetch_spectral_tilt() -> float | None:
    local = _local_json("SPECTRAL_FLOW.json", "spectral.json")
    return spectral_ofi_tilt(local)


def snapshot_licensed_alt() -> dict[str, Any]:
    """QC dump wins; vendor HTTP fills None. Never raise."""
    out: dict[str, Any] = {
        "brain_tilt": None,
        "benzinga_tilt": None,
        "quiver_tilt": None,
        "morningstar_tilt": None,
        "spectral_tilt": None,
        "qc_lean_root": None,
    }
    try:
        from app.services.quant_desk.qc_lean_ingest import ingest_qc_lean_snapshot

        dumped = ingest_qc_lean_snapshot()
        for key, val in dumped.items():
            if key in out:
                out[key] = val
    except Exception:
        pass
    fillers = (
        ("brain_tilt", fetch_brain_tilt),
        ("benzinga_tilt", fetch_benzinga_tilt),
        ("quiver_tilt", fetch_quiver_congress_tilt),
        ("morningstar_tilt", fetch_morningstar_pe_tilt),
        ("spectral_tilt", fetch_spectral_tilt),
    )
    for key, fn in fillers:
        if out.get(key) is not None:
            continue
        try:
            out[key] = fn()
        except Exception:
            continue
    return out
