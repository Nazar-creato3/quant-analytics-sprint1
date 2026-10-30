"""T-Invest first, ISS fallback. Methods checked against invest-contracts and ISS reference."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.services.bonds import store

log = logging.getLogger("data_quality")

# Proto names (opensource.tbank.ru/invest/invest-contracts, instruments.proto):
#   Bonds, BondBy, GetBondCoupons, GetAccruedInterests.
# GetBondEvents: not in the public investAPI instruments service as of 2026-10-13 —
#   offers/amortizations come from ISS bondization tables.
TINVEST_METHODS = ("Bonds", "BondBy", "GetBondCoupons", "GetAccruedInterests")
ISS_BONDIZATION = "/iss/statistics/engines/stock/markets/bonds/bondization/{secid}.json"
ISS_ZCYC = "/iss/engines/stock/zcyc.json"


def discrepancy_kop(a: float | None, b: float | None) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) > 0.01


def merge_cashflows(
    figi: str,
    tinvest: list[dict[str, Any]] | None,
    iss: list[dict[str, Any]] | None,
    *,
    as_of: str | None = None,
) -> list[dict[str, Any]]:
    primary = list(tinvest or [])
    fallback = list(iss or [])
    if not primary:
        store.put_events(figi, fallback)
        return fallback
    by_date = {str(r.get("on_date")): r for r in fallback}
    merged: list[dict[str, Any]] = []
    for row in primary:
        key = str(row.get("on_date"))
        other = by_date.get(key)
        if other and discrepancy_kop(row.get("amount_per_bond"), other.get("amount_per_bond")):
            log.warning(
                "bond cashflow mismatch figi=%s date=%s tinvest=%s iss=%s",
                figi,
                key,
                row.get("amount_per_bond"),
                other.get("amount_per_bond"),
            )
            store.log_quality(
                {
                    "figi": figi,
                    "on_date": key,
                    "tinvest": row.get("amount_per_bond"),
                    "iss": other.get("amount_per_bond"),
                    "as_of": as_of or datetime.now(timezone.utc).isoformat(),
                }
            )
        merged.append({**row, "source": "tinvest"})
    store.put_events(figi, merged)
    return merged


UNIVERSE_PATH = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "bonds" / "universe.json"
_fixtures_loaded = False


def load_fixture_universe(payload: dict[str, Any]) -> None:
    for row in payload.get("references") or []:
        store.put_reference(row)
        store.put_events(str(row["figi"]), list(row.get("cashflows") or []))
    store.put_curve(list(payload.get("g_curve") or []))


def ensure_fixtures() -> None:
    """Load tracked bond JSON only. Does not import QuantLib."""
    global _fixtures_loaded
    if _fixtures_loaded and store.all_refs():
        return
    if not UNIVERSE_PATH.is_file():
        log.warning("bond universe fixture missing path=%s", UNIVERSE_PATH)
        return
    load_fixture_universe(json.loads(UNIVERSE_PATH.read_text(encoding="utf-8")))
    _fixtures_loaded = True
