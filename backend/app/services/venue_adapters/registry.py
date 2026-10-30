"""Venue registry. New venue = adapter module + row here + fixtures."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Support = Literal["full", "partial", "research", "unsupported"]


@dataclass(frozen=True)
class VenueSpec:
    id: str
    title: str
    support: Support
    capabilities: frozenset[str]
    history_note: str
    reason: str = ""


REGISTRY: dict[str, VenueSpec] = {
    "tbank": VenueSpec(
        id="tbank",
        title="Т-Банк Инвестиции",
        support="partial",
        capabilities=frozenset(
            {
                "catalog",
                "positions",
                "balances",
                "operations_cursor",
                "orders",
                "key_check",
                "sandbox",
                "app_name",
            }
        ),
        history_note="GetOperationsByCursor; coverage from first synced page",
    ),
    "finam": VenueSpec(
        id="finam",
        title="Финам Trade API",
        support="partial",
        capabilities=frozenset({"accounts", "positions", "trades", "cash", "orders", "key_check"}),
        history_note="Trade API statements; depth depends on account",
    ),
    "binance": VenueSpec(
        id="binance",
        title="Binance",
        support="partial",
        capabilities=frozenset({"trades", "deposits", "withdrawals", "fees", "positions", "balances"}),
        history_note="Spot/futures history limited by Binance window",
    ),
    "bybit": VenueSpec(
        id="bybit",
        title="Bybit",
        support="partial",
        capabilities=frozenset({"trades", "positions", "balances", "leverage"}),
        history_note="Unified account history window",
    ),
    "mexc": VenueSpec(
        id="mexc",
        title="MEXC",
        support="partial",
        capabilities=frozenset({"trades", "balances"}),
        history_note="Exchange history window",
    ),
    "bitget": VenueSpec(
        id="bitget",
        title="Bitget",
        support="research",
        capabilities=frozenset(),
        history_note="not wired",
        reason="нет продакшн-адаптера в репозитории",
    ),
    "bcs": VenueSpec(
        id="bcs",
        title="БКС",
        support="unsupported",
        capabilities=frozenset(),
        history_note="see docs/research/bcs-api.md",
        reason="публичного Trade API для розницы с историей операций недостаточно",
    ),
}


def list_venues() -> list[VenueSpec]:
    return list(REGISTRY.values())


def get_venue(venue_id: str) -> VenueSpec:
    key = venue_id.strip().lower()
    if key in {"tinkoff", "t-bank"}:
        key = "tbank"
    return REGISTRY[key]
