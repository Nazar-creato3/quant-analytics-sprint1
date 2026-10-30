"""Catalog screener (Prompt 43). Missing fundamentals stay None — never 0."""
from __future__ import annotations

import csv
import io
import json
import time
from pathlib import Path
from typing import Any

from app.services.catalog.resolve import list_known

_GOLDEN = Path(__file__).resolve().parents[4] / "docs" / "qa" / "golden" / "screener.json"
_NO_DATA = "нет данных"
_SAVED: dict[str, list[dict[str, Any]]] = {}


def _load_golden() -> dict[str, dict[str, Any]]:
    if not _GOLDEN.exists():
        return {}
    payload = json.loads(_GOLDEN.read_text(encoding="utf-8"))
    rows = payload.get("rows") if isinstance(payload, dict) else payload
    out: dict[str, dict[str, Any]] = {}
    for row in rows or []:
        symbol = str(row.get("symbol") or "").upper()
        if symbol:
            out[symbol] = row
    return out


def _field(row: dict[str, Any], key: str) -> Any:
    value = row.get(key)
    if value is None or value == "":
        return None
    return value


def catalog_rows() -> list[dict[str, Any]]:
    golden = _load_golden()
    rows: list[dict[str, Any]] = []
    for hit in list_known():
        extra = golden.get(hit.symbol, {})
        pe = _field(extra, "pe")
        beta = _field(extra, "beta")
        vol = _field(extra, "volatility")
        es = _field(extra, "es_975")
        mcap = _field(extra, "market_cap")
        price = _field(extra, "price")
        rows.append(
            {
                "symbol": hit.symbol,
                "asset_id": hit.asset_id,
                "name": extra.get("name") or hit.symbol,
                "venue": hit.venue,
                "instrument_kind": hit.instrument_kind,
                "country": extra.get("country") or ("RU" if hit.venue == "MOEX" else "US"),
                "sector": extra.get("sector"),
                "exchange": extra.get("exchange") or hit.venue,
                "price": price,
                "market_cap": mcap,
                "pe": pe,
                "beta": beta,
                "volatility": vol,
                "es_975": es,
                "volume": _field(extra, "volume"),
                "dividend": _field(extra, "dividend"),
                "fundamentals_source": extra.get("fundamentals_source"),
                "fundamentals_as_of": extra.get("fundamentals_as_of"),
                "risk_source": extra.get("risk_source") or "risk_engine.fhs.v1",
                "risk_as_of": extra.get("risk_as_of"),
                "pe_status": _NO_DATA if pe is None else "ok",
                "beta_status": _NO_DATA if beta is None else "ok",
                "es_status": _NO_DATA if es is None else "ok",
                "source": "catalog",
            }
        )
    return rows


def _match_num(value: Any, *, ge: float | None = None, le: float | None = None) -> bool:
    if ge is None and le is None:
        return True
    if value is None:
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    if ge is not None and number < ge:
        return False
    if le is not None and number > le:
        return False
    return True


def _match_cat(value: Any, expected: str | None) -> bool:
    if not expected:
        return True
    if value is None:
        return False
    return str(value).strip().upper() == expected.strip().upper()


def filter_rows(rows: list[dict[str, Any]], filters: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        if not _match_cat(row.get("country"), filters.get("country")):
            continue
        if not _match_cat(row.get("sector"), filters.get("sector")):
            continue
        if not _match_cat(row.get("exchange"), filters.get("exchange")):
            continue
        if not _match_num(row.get("market_cap"), ge=filters.get("marketCapMoreThan"), le=filters.get("marketCapLowerThan")):
            continue
        if not _match_num(row.get("price"), ge=filters.get("priceMoreThan"), le=filters.get("priceLowerThan")):
            continue
        if not _match_num(row.get("beta"), ge=filters.get("betaMoreThan"), le=filters.get("betaLowerThan")):
            continue
        if not _match_num(row.get("volatility"), ge=filters.get("volMoreThan"), le=filters.get("volLowerThan")):
            continue
        if not _match_num(row.get("es_975"), ge=filters.get("esMoreThan"), le=filters.get("esLowerThan")):
            continue
        if not _match_num(row.get("pe"), ge=filters.get("peMoreThan"), le=filters.get("peLowerThan")):
            continue
        div = filters.get("dividendMoreThan")  # percent in the UI, fraction in rows
        if div is not None and not _match_num(row.get("dividend"), ge=float(div) / 100.0):
            continue
        if not _match_num(row.get("volume"), ge=filters.get("volumeMoreThan")):
            continue
        if filters.get("isEtf") and row.get("instrument_kind") not in {"etf", "fund"} and not row.get("is_etf"):
            continue
        if filters.get("industry") and str(row.get("industry") or "").upper() != str(filters["industry"]).upper():
            continue
        out.append(row)
    limit = int(filters.get("limit") or 50)
    return out[: max(1, min(limit, 300))]


def screen(filters: dict[str, Any]) -> dict[str, Any]:
    t0 = time.perf_counter()
    items = filter_rows(catalog_rows(), filters)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    return {
        "items": items,
        "count": len(items),
        "source": "catalog",
        "elapsed_ms": round(elapsed_ms, 3),
        "universe": "catalog.list_known",
    }


async def screen_live(filters: dict[str, Any]) -> dict[str, Any]:
    """Catalog universe enriched with live fundamentals/risk before filtering."""
    from app.services.screener.fundamentals import live_fields, merge_live

    t0 = time.perf_counter()
    country = str(filters.get("country") or "").upper()
    rows = catalog_rows()
    merged: list[dict[str, Any]] = []
    if country in {"", "RU"}:
        # Whole TQBR board from MOEX instead of the short catalog list.
        try:
            from app.services.screener.moex_rows import rows as moex_rows

            ru = await moex_rows()
        except Exception:  # noqa: BLE001 — ISS down: fall back to catalog MOEX names
            ru = []
        if ru:
            merged.extend(ru)
            rows = [r for r in rows if r.get("venue") != "MOEX"]
    if country != "RU":
        from app.services.market_data.koyfin_snapshot import fetch_fmp_screener

        fmp = await fetch_fmp_screener({**filters, "limit": 100}, limit=100)
        seen = {str(r["symbol"]).upper() for r in merged}
        if fmp:
            for r in fmp:
                sym = str(r["symbol"]).upper()
                if sym in seen:
                    continue
                seen.add(sym)
                merged.append({**r, "venue": r.get("exchange") or "US", "instrument_kind": "etf" if r.get("is_etf") else "equity",
                               "currency": "USD", "pe_status": "ok" if r.get("pe") is not None else "нет данных",
                               "beta_status": "ok" if r.get("beta") is not None else "нет данных", "es_status": "нет данных"})
    # Catalog names (US, crypto, and MOEX when ISS failed) with live Yahoo/xFinLink fields.
    rest = [r for r in rows if str(r["symbol"]).upper() not in {str(m["symbol"]).upper() for m in merged}]
    symbols = [r["symbol"] for r in rest if r.get("venue") != "MOEX" and r.get("instrument_kind") != "crypto"]
    live = await live_fields(symbols)
    merged.extend(merge_live(r, live.get(str(r["symbol"]).upper())) for r in rest)
    if str(filters.get("sort") or "") != "none":
        merged.sort(key=lambda r: float(r.get("market_cap") or 0), reverse=True)
    items = filter_rows(merged, filters)
    return {
        "items": items,
        "count": len(items),
        "source": "catalog+live",
        "elapsed_ms": round((time.perf_counter() - t0) * 1000, 3),
        "universe": "catalog.list_known",
        "pending": max(0, len(symbols) - len(live)),
    }


def save_screen(user_id: str, name: str, filters: dict[str, Any]) -> dict[str, Any]:
    entry = {"name": name.strip() or "без имени", "filters": dict(filters)}
    _SAVED.setdefault(user_id, []).append(entry)
    return entry


def list_saved(user_id: str) -> list[dict[str, Any]]:
    return list(_SAVED.get(user_id, []))


def reset_saved() -> None:
    _SAVED.clear()


def export_csv(rows: list[dict[str, Any]]) -> str:
    fields = [
        "symbol",
        "name",
        "country",
        "sector",
        "price",
        "pe",
        "beta",
        "volatility",
        "es_975",
        "fundamentals_source",
        "fundamentals_as_of",
        "risk_source",
        "pe_status",
        "beta_status",
        "es_status",
    ]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({k: ("" if row.get(k) is None else row.get(k)) for k in fields})
    return buf.getvalue()
