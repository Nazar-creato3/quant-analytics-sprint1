"""ISS index analytics and UK file parsers. Live fetch is off unless FF set.

ISS shape: https://iss.moex.com/iss/reference/ (analytics columns/data).
UK samples are synthetic copies of column layouts; site ToS [ЮРИСТ] L-15.
"""

from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal
from typing import Any

UK_NAMES = ("t_capital", "sber_ua", "vtb", "alfa", "pervaya", "finam")


def parse_iss_analytics(payload: dict[str, Any], *, index_code: str, as_of: date, source_url: str) -> dict[str, Any]:
    block = payload.get("analytics") or payload
    columns = [str(c).lower() for c in (block.get("columns") or [])]
    data = block.get("data") or []
    try:
        w_i = columns.index("weight")
    except ValueError:
        w_i = 1
    try:
        id_i = columns.index("secid")
    except ValueError:
        id_i = 0
    holdings = []
    for row in data:
        secid = str(row[id_i]).upper()
        raw_w = Decimal(str(row[w_i]))
        # ISS analytics weight is percent (1 = 1%). Do not treat 1 as a fraction.
        weight = raw_w / Decimal("100") if raw_w >= 1 else raw_w
        holdings.append(
            {
                "holding_isin": secid,
                "holding_name": secid,
                "issuer": secid,
                "weight": str(weight),
                "asset_class": "equity",
                "currency": "RUB",
                "country": "RU",
                "sector": "unknown",
            }
        )
    return {
        "fund_figi": f"INDEX:{index_code}",
        "ticker": index_code,
        "index_code": index_code,
        "as_of": as_of.isoformat(),
        "source": "index",
        "composition_note": "состав по индексу",
        "source_url": source_url,
        "holdings": holdings,
    }


def parse_uk_csv(uk: str, text: str, *, fund_figi: str, as_of: date, source_url: str) -> dict[str, Any]:
    if uk not in UK_NAMES:
        raise ValueError("unknown uk")
    reader = csv.DictReader(io.StringIO(text.strip()), delimiter=";")
    holdings = []
    for row in reader:
        name = (row.get("ticker") or row.get("name") or "").upper()
        isin = (row.get("isin") or name).upper()
        weight = Decimal(str(row.get("weight") or ""))
        holdings.append(
            {
                "holding_isin": isin,
                "holding_name": name or isin,
                "issuer": (row.get("issuer") or name or isin).upper(),
                "weight": str(weight),
                "asset_class": row.get("asset_class") or "unknown",
                "currency": row.get("currency") or "RUB",
                "country": row.get("country") or "RU",
                "sector": row.get("sector") or "unknown",
            }
        )
    return {
        "fund_figi": fund_figi,
        "ticker": fund_figi,
        "as_of": as_of.isoformat(),
        "source": f"uk:{uk}",
        "composition_note": "",
        "source_url": source_url,
        "holdings": holdings,
    }
