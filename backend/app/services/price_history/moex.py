"""Moscow Exchange ISS: where a security trades and its daily history.

Uses the platform ISS session (passport login when MOEX_USERNAME/PASSWORD are set,
otherwise the public delayed feed — enough for end-of-day history).
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from app.core.logging import get_logger
from app.services.market_data.moex_iss_client import fetch_moex_iss_json

logger = get_logger(__name__)

ISS = "https://iss.moex.com/iss"

# Boards we value at, best first. Engine/market come from ISS itself.
_PREFERRED_BOARDS = ("TQBR", "TQTF", "TQTD", "TQIF", "TQOB", "TQCB", "TQOD", "TQIR", "SMAL", "CETS", "SNDX", "RTSI")

def rows(payload: dict[str, Any] | None, block: str) -> list[dict[str, Any]]:
    """ISS {columns, data} → list of dicts."""
    part = (payload or {}).get(block) or {}
    cols = part.get("columns") or []
    return [dict(zip(cols, r)) for r in part.get("data") or [] if isinstance(r, list)]


async def locate(secid: str) -> dict[str, str] | None:
    """Engine, market and board of a MOEX security, or None when ISS does not know it."""
    payload = await fetch_moex_iss_json(f"{ISS}/securities/{secid}.json", {"iss.meta": "off", "iss.only": "boards,description"})
    boards = [b for b in rows(payload, "boards") if str(b.get("is_traded", 1)) in {"1", "True", "true"}]
    if not boards:
        return None
    by_id = {str(b.get("boardid") or "").upper(): b for b in boards}
    pick = next((by_id[b] for b in _PREFERRED_BOARDS if b in by_id), None)
    if pick is None:
        pick = next((b for b in boards if str(b.get("is_primary")) in {"1", "True", "true"}), boards[0])
    desc = {str(r.get("name") or "").upper(): r.get("value") for r in rows(payload, "description")}
    return {
        "engine": str(pick.get("engine") or ""),
        "market": str(pick.get("market") or ""),
        "board": str(pick.get("boardid") or "").upper(),
        "ccy": str(pick.get("currencyid") or "RUB").upper().replace("SUR", "RUB"),
        "facevalue": desc.get("FACEVALUE"),
        "type": str(desc.get("TYPE") or ""),
        "name": str(desc.get("SHORTNAME") or desc.get("NAME") or secid),
    }


async def history(secid: str, where: dict[str, str], *, days: int = 760) -> list[list[Any]]:
    """[[date, close, value_rub, volume], ...] for the last ``days`` calendar days, oldest first.

    Bond closes come from ISS in % of face value and are converted to roubles per bond.
    """
    engine, market, board = where["engine"], where["market"], where["board"]
    start_day = (date.today() - timedelta(days=days)).isoformat()
    url = f"{ISS}/history/engines/{engine}/markets/{market}/boards/{board}/securities/{secid}.json"
    out: list[list[Any]] = []
    offset = 0
    bond = market == "bonds"
    for _ in range(40):  # 40 pages × 100 rows ≫ 3 years
        payload = await fetch_moex_iss_json(url, {"iss.meta": "off", "from": start_day, "start": offset})
        page = rows(payload, "history")
        if not page:
            break
        for r in page:
            close = r.get("LEGALCLOSEPRICE") or r.get("CLOSE") or r.get("WAPRICE")
            day = r.get("TRADEDATE")
            if close in (None, "", 0) or not day:
                continue
            close = float(close)
            if bond:
                face = r.get("FACEVALUE") or where.get("facevalue") or 1000
                close = close * float(face) / 100.0
            value = r.get("VALUE")
            volume = r.get("VOLUME")
            high, low = r.get("HIGH"), r.get("LOW")
            out.append(
                [
                    str(day)[:10],
                    close,
                    float(value) if value not in (None, "") else None,
                    float(volume) if volume not in (None, "") else None,
                    float(high) if high not in (None, "", 0) else None,
                    float(low) if low not in (None, "", 0) else None,
                ]
            )
            if bond:
                where["duration_days"] = r.get("DURATION") or where.get("duration_days")
                where["yield"] = r.get("YIELDCLOSE") or where.get("yield")
                where["facevalue"] = r.get("FACEVALUE") or where.get("facevalue")
                where["aci"] = r.get("ACCINT") if r.get("ACCINT") not in (None, "") else where.get("aci")
                where["clean_pct"] = r.get("LEGALCLOSEPRICE") or r.get("CLOSE") or where.get("clean_pct")
                where["matdate"] = r.get("MATDATE") or where.get("matdate")
                where["offerdate"] = r.get("OFFERDATE") or where.get("offerdate")
        cursor = rows(payload, "history.cursor")
        total = int((cursor[0] if cursor else {}).get("TOTAL") or 0)
        offset += len(page)
        if not cursor or offset >= total:
            break
    out.sort(key=lambda x: x[0])
    return out


async def index_history(secid: str = "IMOEX", *, days: int = 760) -> list[list[Any]]:
    return await history(secid, {"engine": "stock", "market": "index", "board": "SNDX"}, days=days)


# Bank of Russia currency codes for the official daily rate (USD/EUR stopped trading on MOEX in June 2024).
CBR_CODES = {"USD": "R01235", "EUR": "R01239", "CNY": "R01375", "HKD": "R01200", "GBP": "R01035", "JPY": "R01820"}


async def fx_history(ccy: str, *, days: int = 760) -> list[list[Any]]:
    """Official Bank of Russia rate, roubles per one unit of ``ccy``: [[date, rate, None, None], ...]."""
    import xml.etree.ElementTree as ET

    import httpx

    from app.core.http_proxy import httpx_client_kwargs

    code = CBR_CODES.get(ccy.upper())
    if not code:
        return []
    end = date.today()
    start = end - timedelta(days=days)
    url = "https://www.cbr.ru/scripts/XML_dynamic.asp"
    params = {"date_req1": start.strftime("%d/%m/%Y"), "date_req2": end.strftime("%d/%m/%Y"), "VAL_NM_RQ": code}
    try:
        async with httpx.AsyncClient(**httpx_client_kwargs(foreign=False, timeout=httpx.Timeout(20.0, connect=5.0))) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
    except Exception as exc:  # noqa: BLE001
        logger.warning("cbr_fx_failed", ccy=ccy, error=str(exc)[:200])
        return []
    out: list[list[Any]] = []
    for rec in root.findall("Record"):
        try:
            day = datetime.strptime(rec.get("Date") or "", "%d.%m.%Y").date().isoformat()
            nominal = float((rec.findtext("Nominal") or "1").replace(",", "."))
            value = float((rec.findtext("Value") or "").replace(",", "."))
        except ValueError:
            continue
        if nominal > 0 and value > 0:
            out.append([day, value / nominal, None, None])
    out.sort(key=lambda x: x[0])
    return out


async def dividends(secid: str) -> list[dict[str, Any]]:
    """Dividend history with record (registry close) dates; future rows are declared ones."""
    payload = await fetch_moex_iss_json(f"{ISS}/securities/{secid}/dividends.json", {"iss.meta": "off"})
    out: list[dict[str, Any]] = []
    for r in rows(payload, "dividends"):
        day, value = r.get("registryclosedate"), r.get("value")
        if not day or value in (None, ""):
            continue
        out.append({"record_date": str(day)[:10], "amount": float(value), "ccy": str(r.get("currencyid") or "RUB").upper().replace("SUR", "RUB")})
    out.sort(key=lambda x: x["record_date"])
    return out


async def bondization(secid: str) -> dict[str, list[dict[str, Any]]]:
    """Coupon and amortisation schedule of a bond (amounts in roubles per bond where ISS has them)."""
    payload = await fetch_moex_iss_json(
        f"{ISS}/securities/{secid}/bondization.json",
        {"iss.meta": "off", "iss.only": "coupons,amortizations", "limit": "unlimited"},
    )
    coupons = []
    for r in rows(payload, "coupons"):
        day = r.get("coupondate")
        if not day:
            continue
        value = r.get("value_rub") if r.get("value_rub") not in (None, "") else r.get("value")
        coupons.append(
            {
                "date": str(day)[:10],
                "record_date": str(r.get("recorddate") or "")[:10] or None,
                "amount": float(value) if value not in (None, "") else None,
                "rate_pct": float(r["valueprc"]) if r.get("valueprc") not in (None, "") else None,
            }
        )
    amort = []
    for r in rows(payload, "amortizations"):
        day = r.get("amortdate")
        value = r.get("value_rub") if r.get("value_rub") not in (None, "") else r.get("value")
        if not day or value in (None, ""):
            continue
        amort.append({"date": str(day)[:10], "amount": float(value), "kind": str(r.get("data_source") or "amortization")})
    return {"coupons": sorted(coupons, key=lambda x: x["date"]), "amortizations": sorted(amort, key=lambda x: x["date"])}
