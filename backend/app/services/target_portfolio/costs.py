"""Broker commission from config, plus spread and slippage. No invented tariff."""
from __future__ import annotations

import json
from decimal import Decimal, ROUND_HALF_EVEN
from pathlib import Path

MONEY = Decimal("0.01")
_CONFIG = Path(__file__).with_name("broker_costs.json")


def load_cost_table(path: Path | None = None) -> dict:
    raw = (path or _CONFIG).read_text(encoding="utf-8")
    return json.loads(raw)


def commission_rate(table: dict, broker: str, tariff: str) -> Decimal | None:
    brokers = table.get("brokers") or {}
    row = brokers.get(broker) or {}
    item = (row.get("tariffs") or {}).get(tariff)
    if not item or "commission_rate" not in item:
        return None
    return Decimal(str(item["commission_rate"]))


def trade_costs(
    *,
    traded_notional: Decimal,
    rate: Decimal | None,
    spread_bps: Decimal | None,
    slippage_bps: Decimal | None,
) -> dict[str, str | None]:
    """Half the quoted spread is the crossing cost. Missing inputs stay unset."""
    missing: list[str] = []
    if rate is None:
        missing.append("комиссия")
    if spread_bps is None:
        missing.append("спред")
    if slippage_bps is None:
        missing.append("проскальзывание")
    if missing:
        return {
            "commission": None,
            "spread": None,
            "slippage": None,
            "total": None,
            "status": "нет данных",
            "reason": "нет данных: " + ", ".join(missing),
        }
    assert rate is not None and spread_bps is not None and slippage_bps is not None
    commission = (traded_notional * rate).quantize(MONEY, rounding=ROUND_HALF_EVEN)
    spread = (traded_notional * spread_bps / Decimal("10000") / Decimal("2")).quantize(
        MONEY, rounding=ROUND_HALF_EVEN
    )
    slippage = (traded_notional * slippage_bps / Decimal("10000")).quantize(
        MONEY, rounding=ROUND_HALF_EVEN
    )
    total = (commission + spread + slippage).quantize(MONEY, rounding=ROUND_HALF_EVEN)
    return {
        "commission": format(commission, "f"),
        "spread": format(spread, "f"),
        "slippage": format(slippage, "f"),
        "total": format(total, "f"),
        "status": "ok",
        "reason": "",
    }


def decide_rebalance(
    expected_gain: Decimal | None,
    total_cost: Decimal | None,
) -> tuple[bool, str]:
    """Do not propose a rebalance when the expected gain does not exceed costs."""
    if expected_gain is None or total_cost is None:
        return False, "нет данных по издержкам или ожидаемому результату"
    if expected_gain <= total_cost:
        return False, "ожидаемый выигрыш не выше издержек"
    return True, ""
