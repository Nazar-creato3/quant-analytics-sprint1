"""Exchange session metadata for order book snapshots."""
from __future__ import annotations

from typing import Literal

from app.schemas.orders import OrderBookSnapshot
from app.services.market_data.binance_spot import is_crypto_ticker
from app.services.market_data.moex_spot import is_moex_ticker
from app.services.terminal_platform.market.hours import session_status_for_exchange

SessionStatus = Literal["open", "closed", "pre", "post"]

_EXCHANGE_NAMES_RU: dict[str, str] = {
    "BINANCE": "Binance",
    "MOEX": "MOEX",
    "NYSE": "NYSE",
    "NASDAQ": "NASDAQ",
}

# Well-known NASDAQ-listed symbols (regular session hours match NYSE).
_NASDAQ_TICKERS = frozenset(
    {
        "AAPL",
        "MSFT",
        "GOOGL",
        "GOOG",
        "AMZN",
        "META",
        "NVDA",
        "QQQ",
        "TSLA",
        "NFLX",
        "AMD",
        "INTC",
        "AVGO",
        "COST",
        "PEP",
        "CSCO",
        "CMCSA",
        "ADBE",
        "QCOM",
        "TXN",
        "AMGN",
        "HON",
        "INTU",
        "AMAT",
        "SBUX",
        "GILD",
        "MDLZ",
        "ADP",
        "ISRG",
        "BKNG",
        "VRTX",
        "REGN",
        "LRCX",
        "MU",
        "PANW",
        "SNPS",
        "CDNS",
        "KLAC",
        "MRVL",
        "CRWD",
        "PYPL",
        "ABNB",
        "MAR",
        "ORLY",
        "ADSK",
        "MNST",
        "CHTR",
        "WDAY",
        "FTNT",
        "DXCM",
        "PCAR",
        "MELI",
        "KDP",
        "AZN",
        "BIIB",
        "LULU",
        "EA",
        "NXPI",
        "ROST",
        "IDXX",
        "FAST",
        "VRSK",
        "CSGP",
        "ODFL",
        "CTAS",
        "EXC",
        "XEL",
        "KHC",
        "GEHC",
        "ON",
        "ANSS",
        "ZS",
        "DDOG",
        "TEAM",
        "ARM",
        "SMCI",
        "PLTR",
        "COIN",
        "MSTR",
    }
)


def resolve_exchange_for_ticker(ticker: str) -> tuple[str, str]:
    """Map ticker to primary exchange id and Russian display name."""
    raw = ticker.strip().upper()
    if is_crypto_ticker(raw):
        return "BINANCE", _EXCHANGE_NAMES_RU["BINANCE"]
    if is_moex_ticker(raw) or raw.endswith(".ME"):
        return "MOEX", _EXCHANGE_NAMES_RU["MOEX"]
    if raw in _NASDAQ_TICKERS:
        return "NASDAQ", _EXCHANGE_NAMES_RU["NASDAQ"]
    return "NYSE", _EXCHANGE_NAMES_RU["NYSE"]


def session_status_for_ticker(ticker: str) -> SessionStatus:
    exchange_id, _ = resolve_exchange_for_ticker(ticker)
    if exchange_id == "BINANCE":
        return "open"
    status = session_status_for_exchange(exchange_id)
    if status == "holiday":
        return "closed"
    return status  # type: ignore[return-value]


def build_session_message_ru(exchange_id: str, session_status: str) -> str:
    name = _EXCHANGE_NAMES_RU.get(exchange_id, exchange_id)
    if exchange_id == "BINANCE":
        return f"{name} · торговля 24/7"
    if session_status == "open":
        return f"{name} · торговая сессия открыта"
    if session_status == "pre":
        return f"{name} · премаркет"
    if session_status == "post":
        return f"{name} · после закрытия"
    return f"{name} · торговая сессия закрыта"


def enrich_order_book_session(snapshot: OrderBookSnapshot, ticker: str) -> OrderBookSnapshot:
    exchange_id, exchange_name_ru = resolve_exchange_for_ticker(ticker)
    session_status = session_status_for_ticker(ticker)
    session_message_ru = build_session_message_ru(exchange_id, session_status)

    updates: dict = {
        "exchange_id": exchange_id,
        "exchange_name_ru": exchange_name_ru,
        "session_status": session_status,
        "session_message_ru": session_message_ru,
    }

    # A recorded book (Nasdaq replay or a past close) has no live session to report.
    if (snapshot.session_label or "").startswith("Запись"):
        updates["session_status"] = None
        updates["session_message_ru"] = None
        return snapshot.model_copy(update=updates)

    # Keep CLOSED banner separate from depth-unavailable copy.
    if (
        exchange_id != "BINANCE"
        and session_status != "open"
        and not snapshot.depth_available
    ):
        closed_depth = "Торговая сессия закрыта. Глубина стакана недоступна вне часов работы биржи"
        reason = snapshot.depth_unavailable_reason
        if not reason:
            updates["depth_unavailable_reason"] = closed_depth
        elif closed_depth not in reason:
            updates["depth_unavailable_reason"] = f"{closed_depth} · {reason}"
        label = snapshot.session_label or ""
        if not label or "Yahoo" in label or label.startswith("глубина недоступна") or "сессия закрыта" in label:
            updates["session_label"] = closed_depth

    return snapshot.model_copy(update=updates)
