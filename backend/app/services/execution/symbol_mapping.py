"""Symbol mapping: market data ticker vs execution provider ticker (Task 5)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.services.execution.tokenized_provider_type import TokenizedProvider

AssetClass = Literal["tokenized_equity", "crypto", "moex_equity", "moex_currency"]


@dataclass(frozen=True)
class SymbolRoute:
    ui_symbol: str
    data_source_ticker: str
    execution_provider_ticker: str
    asset_class: AssetClass
    execution_venue: str  # tokenized_equity | binance | tinkoff | mock


# Bybit tokenized spot symbols use {TICKER}XUSDT (not legacy bare {TICKER}X).
# Legacy static map retained for aliases/tests; live listing uses bybit_instruments cache.
_BYBIT_TOKENIZED: dict[str, str] = {
    "AAPL": "AAPLXUSDT",
    "MSFT": "MSFTXUSDT",
    "GOOGL": "GOOGLXUSDT",
    "GOOG": "GOOGLXUSDT",
    "AMZN": "AMZNXUSDT",
    "META": "METAXUSDT",
    "NVDA": "NVDAXUSDT",
    "TSLA": "TSLAXUSDT",
    "SPY": "SPYXUSDT",
    "QQQ": "QQQXUSDT",
    "AMD": "AMDXUSDT",
    "NFLX": "NFLXXUSDT",
    "COIN": "COINXUSDT",
    "MSTR": "MSTRXUSDT",
}

_MEXC_TOKENIZED: dict[str, str] = {
    "AAPL": "AAPLUSDT",
    "MSFT": "MSFTUSDT",
    "GOOGL": "GOOGUSDT",
    "GOOG": "GOOGUSDT",
    "AMZN": "AMZNUSDT",
    "META": "METAUSDT",
    "NVDA": "NVDAUSDT",
    "TSLA": "TSLAUSDT",
    "SPY": "SPYUSDT",
    "QQQ": "QQQUSDT",
    "AMD": "AMDUSDT",
    "NFLX": "NFLXUSDT",
    "COIN": "COINUSDT",
    "MSTR": "MSTRUSDT",
}


def normalize_ui_symbol(symbol: str) -> str:
    return symbol.upper().strip().replace(".ME", "").split("-")[0]


def is_tokenized_equity(symbol: str) -> bool:
    """True when symbol routes to tokenized equity venue (not a live exchange listing check)."""
    from app.services.market_data.binance_spot import is_crypto_ticker
    from app.services.broker.tinkoff_orders import is_tinkoff_routable_ticker

    raw = symbol.upper().strip()
    if is_crypto_ticker(raw) or is_tinkoff_routable_ticker(raw):
        return False
    return resolve_symbol_route(raw).execution_venue == "tokenized_equity"


async def is_bybit_listed_tokenized(symbol: str) -> bool:
    from app.services.execution.bybit_instruments import bybit_supports_ui_ticker

    return await bybit_supports_ui_ticker(symbol)


async def bybit_tokenized_unavailable_reason(symbol: str) -> str | None:
    """Return user-facing RU message when tokenized route exists but Bybit has no live instrument."""
    if not is_tokenized_equity(symbol):
        return None
    if await is_bybit_listed_tokenized(symbol):
        return None
    return EXECUTION_UNAVAILABLE_RU


EXECUTION_UNAVAILABLE_RU = "Торговля этого инструмента сейчас недоступна."
# Backward-compatible alias used in tests/docs.
BYBIT_TOKENIZED_UNAVAILABLE_RU = EXECUTION_UNAVAILABLE_RU


async def list_bybit_tradeable_tokenized_bases() -> list[str]:
    from app.services.execution.bybit_instruments import get_bybit_tokenized_instruments

    instruments = await get_bybit_tokenized_instruments()
    return sorted(base for base in instruments.keys() if base != "GOOG")


def execution_ticker_for(symbol: str, *, provider_type: str = "bybit") -> str:
    base = normalize_ui_symbol(symbol)
    provider = TokenizedProvider.normalize(provider_type)
    mapping = _MEXC_TOKENIZED if provider == TokenizedProvider.MEXC else _BYBIT_TOKENIZED
    if provider == TokenizedProvider.MEXC:
        return mapping.get(base, f"{base}USDT")
    return mapping.get(base, f"{base}XUSDT")


def data_ticker_for(symbol: str) -> str:
    base = normalize_ui_symbol(symbol)
    if base in _BYBIT_TOKENIZED:
        return base
    return symbol.upper().strip()


def resolve_symbol_route(symbol: str, *, provider_type: str = "bybit") -> SymbolRoute:
    from app.services.market_data.binance_spot import is_crypto_ticker
    from app.services.broker.tinkoff_orders import is_tinkoff_routable_ticker

    raw = symbol.upper().strip()
    base = normalize_ui_symbol(raw)

    if is_crypto_ticker(raw):
        return SymbolRoute(
            ui_symbol=raw,
            data_source_ticker=raw,
            execution_provider_ticker=raw.replace("-", "").replace("/", ""),
            asset_class="crypto",
            execution_venue="binance",
        )
    if is_tinkoff_routable_ticker(raw):
        return SymbolRoute(
            ui_symbol=raw,
            data_source_ticker=raw,
            execution_provider_ticker=raw,
            asset_class="moex_currency" if raw.endswith("000") else "moex_equity",
            execution_venue="tinkoff",
        )
    exec_ticker = execution_ticker_for(base, provider_type=provider_type)
    if base in _BYBIT_TOKENIZED or base in _MEXC_TOKENIZED:
        return SymbolRoute(
            ui_symbol=base,
            data_source_ticker=base,
            execution_provider_ticker=exec_ticker,
            asset_class="tokenized_equity",
            execution_venue="tokenized_equity",
        )
    return SymbolRoute(
        ui_symbol=base,
        data_source_ticker=base,
        execution_provider_ticker=exec_ticker,
        asset_class="tokenized_equity",
        execution_venue="tokenized_equity",
    )


def list_tokenized_equity_symbols() -> list[str]:
    return sorted(_BYBIT_TOKENIZED.keys())
