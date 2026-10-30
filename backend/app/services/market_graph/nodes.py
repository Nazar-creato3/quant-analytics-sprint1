"""Node ID helpers for the market graph."""
from __future__ import annotations

from app.services.market_graph.types import NodeKind


def instrument_node(instrument_id: int) -> str:
    return f"{NodeKind.INSTRUMENT.value}:{instrument_id}"


def sector_node(sector: str) -> str:
    return f"{NodeKind.SECTOR.value}:{sector}"


def macro_node(indicator_code: str) -> str:
    return f"{NodeKind.MACRO.value}:{indicator_code}"


def factor_node(factor_name: str) -> str:
    return f"{NodeKind.FACTOR.value}:{factor_name}"


def news_node(news_id: str) -> str:
    return f"{NodeKind.NEWS.value}:{news_id}"


def parse_instrument_node(node_id: str) -> int | None:
    prefix = f"{NodeKind.INSTRUMENT.value}:"
    if not node_id.startswith(prefix):
        return None
    try:
        return int(node_id[len(prefix) :])
    except ValueError:
        return None


def parse_sector_node(node_id: str) -> str | None:
    prefix = f"{NodeKind.SECTOR.value}:"
    if not node_id.startswith(prefix):
        return None
    return node_id[len(prefix) :]
