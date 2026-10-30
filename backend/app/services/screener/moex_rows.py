"""Russian shares for the screener: the whole TQBR board, not a hand-picked list.

Per share, best source first, each field filled once:
1. MOEX ISS board snapshot (one request for ~250 names, cached 10 min) — name,
   price, capitalisation, traded value.
2. T-Invest ``GetAssetFundamentals`` when a platform T-Invest token is set —
   P/E, dividend yield, beta, capitalisation (cached 12 h).
3. Our price history — volatility, ES 97.5, beta to IMOEX, trailing dividend yield.
4. A curated sector map (MOEX gives no sector in ISS; T-Invest does when available).

Anything no source can give stays None — the UI shows «—», never 0.
"""
from __future__ import annotations

import math
import statistics
import time
from typing import Any

import httpx

from app.core.logging import get_logger
from app.services.market_data.moex_iss_client import fetch_moex_iss_json
from app.services.price_history import moex as iss

logger = get_logger(__name__)

_SNAPSHOT_URL = f"{iss.ISS}/engines/stock/markets/shares/boards/TQBR/securities.json"
_SNAPSHOT_TTL = 600
_TINV_TTL = 12 * 3600
_snapshot: dict[str, Any] = {"at": 0.0, "rows": []}
_tinv: dict[str, Any] = {"at": 0.0, "rows": {}}

# Sector names match the screener's English sector filter values.
SECTOR: dict[str, str] = {
    **dict.fromkeys(["SBER", "SBERP", "VTBR", "T", "TCSG", "MOEX", "SPBE", "CBOM", "BSPB", "SVCB", "RENI", "LEAS", "MBNK", "SFIN", "AFKS", "DOMRF", "ZAYM", "CARM", "SOFL", "BSPBP", "ROSB", "KZOS"], "Financial Services"),
    **dict.fromkeys(["LKOH", "ROSN", "GAZP", "NVTK", "TATN", "TATNP", "SNGS", "SNGSP", "SIBN", "TRNFP", "BANE", "BANEP", "RNFT", "ELFV"], "Energy"),
    **dict.fromkeys(["GMKN", "PLZL", "ALRS", "CHMF", "NLMK", "MAGN", "RUAL", "PHOR", "SELG", "UGLD", "RASP", "MTLR", "MTLRP", "AKRN", "ENPG", "TRMK", "VSMO", "SGZH", "KAZT", "LNZL", "MRKZ"], "Basic Materials"),
    **dict.fromkeys(["YDEX", "YNDX", "VKCO", "OZON", "POSI", "ASTR", "DIAS", "IVAT", "SOFL", "HEAD", "CNRU", "WUSH", "DATA", "DELI", "VSEH"], "Technology"),
    **dict.fromkeys(["MTSS", "RTKM", "RTKMP"], "Communication Services"),
    **dict.fromkeys(["MGNT", "X5", "FIVE", "FIXP", "LENT", "MVID", "OKEY", "BELU", "ABRD", "AQUA", "GCHE", "SVAV", "EUTR"], "Consumer Defensive"),
    **dict.fromkeys(["AFLT", "FLOT", "NMTP", "FESH", "GLTR", "KMAZ", "UWGN", "IRKT", "UNAC", "NKHP", "TGKN"], "Industrials"),
    **dict.fromkeys(["IRAO", "HYDR", "FEES", "UPRO", "MSNG", "OGKB", "TGKA", "MRKC", "MRKP", "MRKV", "MRKU", "LSNG", "LSNGP", "ELMT", "MSRS"], "Utilities"),
    **dict.fromkeys(["PIKK", "SMLT", "LSRG", "ETLN", "ETAL"], "Real Estate"),
    **dict.fromkeys(["MDMG", "GEMC", "PRMD", "APTK", "OZPH", "LIFE"], "Healthcare"),
    **dict.fromkeys(["SFTL", "MGKL", "HNFG", "RAGR", "KLSB"], "Consumer Cyclical"),
}

_TINV_SECTOR = {
    "financial": "Financial Services", "energy": "Energy", "materials": "Basic Materials", "it": "Technology",
    "telecom": "Communication Services", "consumer": "Consumer Defensive", "industrials": "Industrials",
    "utilities": "Utilities", "real_estate": "Real Estate", "health_care": "Healthcare", "green_energy": "Utilities",
    "electrocars": "Consumer Cyclical", "ecomaterials": "Basic Materials",
}


def _num(v: Any) -> float | None:
    if isinstance(v, dict) and "units" in v:  # T-Invest Quotation {units, nano}
        try:
            return float(v.get("units") or 0) + float(v.get("nano") or 0) / 1e9
        except (TypeError, ValueError):
            return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


async def snapshot() -> list[dict[str, Any]]:
    """All TQBR shares with price, capitalisation and traded value (cached)."""
    if _snapshot["rows"] and time.monotonic() - _snapshot["at"] < _SNAPSHOT_TTL:
        return _snapshot["rows"]
    payload = await fetch_moex_iss_json(
        _SNAPSHOT_URL,
        {
            "iss.meta": "off",
            "iss.only": "securities,marketdata",
            "securities.columns": "SECID,SHORTNAME,SECNAME,PREVPRICE,ISSUESIZE,LISTLEVEL",
            "marketdata.columns": "SECID,LAST,MARKETPRICE,VALTODAY,VALTODAY_RUR,VOLTODAY,ISSUECAPITALIZATION",
        },
    )
    sec = {r["SECID"]: r for r in iss.rows(payload, "securities") if r.get("SECID")}
    md = {r["SECID"]: r for r in iss.rows(payload, "marketdata") if r.get("SECID")}
    out = []
    for secid, s in sec.items():
        m = md.get(secid, {})
        price = _num(m.get("LAST")) or _num(m.get("MARKETPRICE")) or _num(s.get("PREVPRICE"))
        cap = _num(m.get("ISSUECAPITALIZATION"))
        if cap is None and price and _num(s.get("ISSUESIZE")):
            cap = price * float(s["ISSUESIZE"])
        out.append(
            {
                "symbol": secid,
                "name": s.get("SHORTNAME") or s.get("SECNAME") or secid,
                "price": price,
                "market_cap_rub": cap,
                "value_today_rub": _num(m.get("VALTODAY_RUR")) or _num(m.get("VALTODAY")),
                "volume": _num(m.get("VOLTODAY")),
                "list_level": s.get("LISTLEVEL"),
            }
        )
    if out:
        _snapshot.update(at=time.monotonic(), rows=out)
    return out or _snapshot["rows"]


async def tinvest_fundamentals() -> dict[str, dict[str, Any]]:
    """P/E, dividend yield, beta, sector by ticker from T-Invest (needs a platform token)."""
    from app.services.integration.historical_data import tinkoff_rpc
    from app.services.trading_keys.platform_keys import tinkoff_market_data_token

    token = tinkoff_market_data_token()
    if not token:
        return {}
    if _tinv["rows"] and time.monotonic() - _tinv["at"] < _TINV_TTL:
        return _tinv["rows"]
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    out: dict[str, dict[str, Any]] = {}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(25.0, connect=5.0)) as client:
            resp = await client.post(tinkoff_rpc("InstrumentsService/Shares"), headers=headers, json={"instrumentStatus": "INSTRUMENT_STATUS_BASE"})
            resp.raise_for_status()
            shares = [s for s in resp.json().get("instruments") or [] if s.get("classCode") == "TQBR" and s.get("assetUid")]
            by_uid = {s["assetUid"]: s for s in shares}
            uids = list(by_uid)
            for i in range(0, len(uids), 100):
                r = await client.post(
                    tinkoff_rpc("InstrumentsService/GetAssetFundamentals"), headers=headers, json={"assets": uids[i : i + 100]}
                )
                if r.status_code != 200:
                    logger.info("tinvest_fundamentals_skip", status=r.status_code)
                    continue
                for f in r.json().get("fundamentals") or []:
                    share = by_uid.get(f.get("assetUid"))
                    if not share:
                        continue
                    div = _num(f.get("dividendYieldDailyTtm"))
                    out[str(share["ticker"]).upper()] = {
                        "pe": _num(f.get("peRatioTtm")),
                        "dividend": None if div is None else div / 100.0,
                        "beta": _num(f.get("beta")),
                        "market_cap_rub": _num(f.get("marketCapitalization")),
                        "sector": _TINV_SECTOR.get(str(share.get("sector") or "").lower()),
                        "name": share.get("name"),
                    }
    except Exception as exc:  # noqa: BLE001 — T-Invest down: ISS + history still fill the row
        logger.warning("tinvest_fundamentals_failed", error=str(exc)[:200])
        return _tinv["rows"]
    if out:
        _tinv.update(at=time.monotonic(), rows=out)
    return out or _tinv["rows"]


def _history_fields(ticker: str) -> dict[str, float | None]:
    from app.services.price_history import service as history
    from app.services.price_history import store as ph

    r = history.returns(ticker)
    out: dict[str, float | None] = {"volatility": None, "es_975": None, "beta": None, "dividend": None}
    if len(r) >= 120:
        tail = r[-252:]
        out["volatility"] = statistics.pstdev(tail) * math.sqrt(252)
        worst = sorted(tail)[: max(1, int(len(tail) * 0.025))]
        out["es_975"] = -sum(worst) / len(worst)
        idx = history.dated_returns("IMOEX")
        mine = history.dated_returns(ticker)
        common = sorted(set(idx) & set(mine))[-252:]
        if len(common) >= 120:
            x = [idx[d] for d in common]
            y = [mine[d] for d in common]
            mx, my = statistics.fmean(x), statistics.fmean(y)
            var = sum((a - mx) ** 2 for a in x)
            if var > 0:
                out["beta"] = sum((a - mx) * (b - my) for a, b in zip(x, y)) / var
    pay = ph.read(f"PAY_{ticker}") or {}
    mark = history.last(ticker)
    if pay.get("kind") == "dividend" and mark and mark[1] > 0:
        from datetime import date, timedelta

        cutoff = (date.today() - timedelta(days=365)).isoformat()
        trail = sum(float(x["amount"]) for x in pay.get("dividends") or [] if cutoff <= str(x["record_date"]) <= date.today().isoformat())
        out["dividend"] = trail / mark[1]
    return out


async def rows() -> list[dict[str, Any]]:
    """Screener rows for Russian shares, in the same shape as catalog rows."""
    from app.services.price_history import service as history

    snap = await snapshot()
    tinv = await tinvest_fundamentals()
    usd = history.fx_rate("USD")
    if usd is None and history.store.enabled():
        from app.services.price_history.sync import sync_fx

        await sync_fx()
        usd = history.fx_rate("USD")
    out: list[dict[str, Any]] = []
    for s in snap:
        t = s["symbol"]
        f = tinv.get(t, {})
        h = _history_fields(t)
        cap_rub = f.get("market_cap_rub") or s.get("market_cap_rub")
        pe = f.get("pe")
        beta = f.get("beta") if f.get("beta") is not None else h["beta"]
        dividend = f.get("dividend") if f.get("dividend") is not None else h["dividend"]
        out.append(
            {
                "symbol": t,
                "asset_id": f"eq:{t}",
                "name": f.get("name") or s.get("name") or t,
                "venue": "MOEX",
                "instrument_kind": "equity",
                "country": "RU",
                "sector": f.get("sector") or SECTOR.get(t),
                "exchange": "MOEX",
                "currency": "RUB",
                "price": s.get("price"),
                "market_cap": (cap_rub / usd) if cap_rub and usd else None,  # USD, for the shared size filter
                "market_cap_rub": cap_rub,
                "pe": pe,
                "beta": beta,
                "volatility": h["volatility"],
                "es_975": h["es_975"],
                "volume": s.get("volume"),
                "value_today_rub": s.get("value_today_rub"),
                "dividend": dividend,
                "fundamentals_source": "T-Invest" if f else "Московская биржа",
                "fundamentals_as_of": None,
                "risk_source": "история цен Мосбиржи",
                "risk_as_of": None,
                "pe_status": "нет данных" if pe is None else "ok",
                "beta_status": "нет данных" if beta is None else "ok",
                "es_status": "нет данных" if h["es_975"] is None else "ok",
                "source": "moex_iss",
            }
        )
    liquid = sorted(out, key=lambda r: r.get("value_today_rub") or 0, reverse=True)[:120]
    history.want([r["symbol"] for r in liquid])
    return out
