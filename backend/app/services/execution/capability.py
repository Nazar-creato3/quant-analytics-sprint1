"""Dynamic execution capability checks per provider (live/cached exchange data)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.services.broker.tinkoff_orders import is_tinkoff_routable_ticker
from app.services.execution.bybit_instruments import bybit_supports_ui_ticker
from app.services.execution.symbol_mapping import normalize_ui_symbol, resolve_symbol_route
from app.services.execution.tokenized_provider_type import TOKENIZED_EQUITY_VENUE
from app.services.instrument.data_only import is_data_only_symbol
from app.services.market_data.binance_spot import is_crypto_ticker
from app.services.trading_keys.user_executor import user_has_trading_key

logger = get_logger(__name__)

ExecutionBlockType = Literal["unavailable", "connect_provider"]

PROVIDER_LABELS: dict[str, str] = {
    "bybit_tokenized": "Bybit",
    "binance": "Binance",
    "tinkoff": "Т-Банк",
}


@dataclass(frozen=True)
class ProviderExecutionCapability:
    provider_id: str
    display_name_ru: str
    venue: str
    exchange_supports: bool
    user_connected: bool


@dataclass(frozen=True)
class ExecutionCapability:
    ticker: str
    primary_venue: str | None
    globally_tradeable: bool
    user_can_execute: bool
    execution_enabled: bool
    providers: tuple[ProviderExecutionCapability, ...]
    block_reason_ru: str | None
    block_type: ExecutionBlockType | None
    bybit_tokenized_listed: bool | None = None


def _unavailable_message() -> str:
    return "Торговля этого инструмента сейчас недоступна."


def _connect_message(provider_names: list[str]) -> str:
    names = ", ".join(provider_names)
    return f"Подключите {names} для торговли этим инструментом."


async def _provider_user_connected(
    db: AsyncSession,
    *,
    user_id: str | None,
    venue: str,
    account_mode: str | None,
) -> bool:
    if not user_id:
        return False
    return await user_has_trading_key(
        db,
        user_id,
        venue=venue,
        account_mode=account_mode,
    )


async def resolve_execution_capability(
    db: AsyncSession,
    *,
    ticker: str,
    user_id: str | None = None,
    account_mode: str | None = None,
) -> ExecutionCapability:
    """Determine whether a symbol can be executed and through which providers."""
    sym = ticker.upper().strip()
    route = resolve_symbol_route(sym)
    providers: list[ProviderExecutionCapability] = []
    bybit_listed: bool | None = None

    if is_data_only_symbol(sym):
        return ExecutionCapability(
            ticker=sym,
            primary_venue=route.execution_venue,
            globally_tradeable=False,
            user_can_execute=False,
            execution_enabled=False,
            providers=tuple(),
            block_reason_ru=_unavailable_message(),
            block_type="unavailable",
            bybit_tokenized_listed=None,
        )

    if route.execution_venue == "tokenized_equity":
        exchange_supports = await bybit_supports_ui_ticker(sym)
        bybit_listed = exchange_supports
        user_connected = False
        if exchange_supports and user_id:
            user_connected = await _provider_user_connected(
                db,
                user_id=user_id,
                venue=TOKENIZED_EQUITY_VENUE,
                account_mode=account_mode,
            )
        providers.append(
            ProviderExecutionCapability(
                provider_id="bybit_tokenized",
                display_name_ru=PROVIDER_LABELS["bybit_tokenized"],
                venue="tokenized_equity",
                exchange_supports=exchange_supports,
                user_connected=user_connected,
            )
        )
    elif route.execution_venue == "binance":
        exchange_supports = is_crypto_ticker(sym)
        user_connected = False
        if exchange_supports and user_id:
            user_connected = await _provider_user_connected(
                db,
                user_id=user_id,
                venue="binance",
                account_mode=account_mode,
            )
        providers.append(
            ProviderExecutionCapability(
                provider_id="binance",
                display_name_ru=PROVIDER_LABELS["binance"],
                venue="binance",
                exchange_supports=exchange_supports,
                user_connected=user_connected,
            )
        )
    elif route.execution_venue == "tinkoff":
        exchange_supports = is_tinkoff_routable_ticker(sym)
        user_connected = False
        if exchange_supports and user_id:
            user_connected = await _provider_user_connected(
                db,
                user_id=user_id,
                venue="tinkoff",
                account_mode=account_mode,
            )
        providers.append(
            ProviderExecutionCapability(
                provider_id="tinkoff",
                display_name_ru=PROVIDER_LABELS["tinkoff"],
                venue="tinkoff",
                exchange_supports=exchange_supports,
                user_connected=user_connected,
            )
        )
    else:
        logger.warning("Unknown execution venue for capability check", ticker=sym, venue=route.execution_venue)

    supporting = [p for p in providers if p.exchange_supports]
    connected_supporting = [p for p in supporting if p.user_connected]
    globally_tradeable = bool(supporting)
    user_can_execute = bool(connected_supporting)

    block_type: ExecutionBlockType | None = None
    block_reason: str | None = None

    if not globally_tradeable:
        block_type = "unavailable"
        block_reason = _unavailable_message()
    elif user_id is not None and not user_can_execute:
        block_type = "connect_provider"
        block_reason = _connect_message([p.display_name_ru for p in supporting])

    execution_enabled = globally_tradeable and (user_id is None or user_can_execute)

    return ExecutionCapability(
        ticker=normalize_ui_symbol(sym),
        primary_venue=route.execution_venue if globally_tradeable else None,
        globally_tradeable=globally_tradeable,
        user_can_execute=user_can_execute,
        execution_enabled=execution_enabled,
        providers=tuple(providers),
        block_reason_ru=block_reason,
        block_type=block_type,
        bybit_tokenized_listed=bybit_listed,
    )


async def symbol_execution_hint(ticker: str) -> dict[str, str | bool | None]:
    """Lightweight hint for symbol lists (no user key lookup)."""
    sym = ticker.upper().strip()
    route = resolve_symbol_route(sym)
    globally_tradeable = False
    required_provider_ru: str | None = None

    if is_data_only_symbol(sym):
        return {
            "execution_available_globally": False,
            "execution_hint_ru": _unavailable_message(),
            "required_provider_ru": None,
        }

    if route.execution_venue == "tokenized_equity":
        globally_tradeable = await bybit_supports_ui_ticker(sym)
        required_provider_ru = PROVIDER_LABELS["bybit_tokenized"]
    elif route.execution_venue == "binance":
        globally_tradeable = is_crypto_ticker(sym)
        required_provider_ru = PROVIDER_LABELS["binance"]
    elif route.execution_venue == "tinkoff":
        globally_tradeable = is_tinkoff_routable_ticker(sym)
        required_provider_ru = PROVIDER_LABELS["tinkoff"]

    if not globally_tradeable:
        return {
            "execution_available_globally": False,
            "execution_hint_ru": _unavailable_message(),
            "required_provider_ru": None,
        }
    return {
        "execution_available_globally": True,
        "execution_hint_ru": None,
        "required_provider_ru": required_provider_ru,
    }
