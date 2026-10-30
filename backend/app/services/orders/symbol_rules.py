"""Per-symbol trading constraints for the generic spot order ticket."""
from __future__ import annotations

import httpx
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.logging import get_logger
from app.services.market_data.binance_spot import is_crypto_ticker, ticker_to_binance_symbol
from app.services.market_data.moex_currency import (
    fetch_moex_currency_rules,
    is_moex_currency_ticker,
    normalize_moex_currency_symbol,
)
from app.services.market_data.moex_spot import is_moex_ticker, normalize_moex_symbol

logger = get_logger(__name__)

TIMEOUT = httpx.Timeout(8.0, connect=4.0)
BINANCE_SPOT_URL = "https://api.binance.com"

# Sensible defaults when venue metadata is unavailable.
_DEFAULT_US = {"tick_size": 0.01, "lot_size": 1.0, "min_qty": 1.0, "min_notional_usd": 1.0}
_DEFAULT_MOEX = {"tick_size": 0.01, "lot_size": 1.0, "min_qty": 1.0, "min_notional_usd": 0.0}
_DEFAULT_MOEX_FX = {"tick_size": 0.0025, "lot_size": 1000.0, "min_qty": 1000.0, "min_notional_usd": 0.0}
_DEFAULT_CRYPTO = {"tick_size": 0.00000001, "lot_size": 0.00000001, "min_qty": 0.00000001, "min_notional_usd": 5.0}


class SymbolTradingRules(BaseModel):
    ticker: str
    venue: str
    tick_size: float = Field(..., gt=0)
    lot_size: float = Field(..., gt=0)
    min_qty: float = Field(..., gt=0)
    min_notional_usd: float = Field(0.0, ge=0)
    price_decimals: int = Field(2, ge=0, le=12)
    qty_decimals: int = Field(6, ge=0, le=12)


def _decimals_from_step(step: float) -> int:
    text = f"{step:.12f}".rstrip("0")
    if "." not in text:
        return 0
    return len(text.split(".")[1])


async def _binance_rules(ticker: str) -> SymbolTradingRules | None:
    symbol = ticker_to_binance_symbol(ticker)
    if not symbol:
        return None
    url = f"{BINANCE_SPOT_URL}/api/v3/exchangeInfo"
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(url, params={"symbol": symbol})
            resp.raise_for_status()
            payload = resp.json()
    except Exception as exc:
        logger.debug("Binance exchangeInfo failed", symbol=symbol, error=str(exc))
        return None

    info = (payload.get("symbols") or [None])[0]
    if not info:
        return None

    tick_size = float(_DEFAULT_CRYPTO["tick_size"])
    lot_size = float(_DEFAULT_CRYPTO["lot_size"])
    min_qty = float(_DEFAULT_CRYPTO["min_qty"])
    min_notional = float(_DEFAULT_CRYPTO["min_notional_usd"])

    for filt in info.get("filters") or []:
        ftype = filt.get("filterType")
        if ftype == "PRICE_FILTER":
            tick_size = float(filt.get("tickSize") or tick_size)
        elif ftype == "LOT_SIZE":
            lot_size = float(filt.get("stepSize") or lot_size)
            min_qty = float(filt.get("minQty") or min_qty)
        elif ftype == "MIN_NOTIONAL":
            min_notional = float(filt.get("minNotional") or filt.get("notional") or min_notional)

    return SymbolTradingRules(
        ticker=ticker.upper(),
        venue="binance",
        tick_size=tick_size,
        lot_size=lot_size,
        min_qty=min_qty,
        min_notional_usd=min_notional,
        price_decimals=_decimals_from_step(tick_size),
        qty_decimals=_decimals_from_step(lot_size),
    )


async def _moex_fx_rules(ticker: str) -> SymbolTradingRules:
    bare = normalize_moex_currency_symbol(ticker)
    meta = await fetch_moex_currency_rules(bare)
    tick_size = float(meta.get("tick_size") or _DEFAULT_MOEX_FX["tick_size"])
    lot_size = float(meta.get("lot_size") or _DEFAULT_MOEX_FX["lot_size"])
    min_qty = float(meta.get("min_qty") or lot_size)
    return SymbolTradingRules(
        ticker=bare,
        venue="moex_fx",
        tick_size=tick_size,
        lot_size=lot_size,
        min_qty=min_qty,
        min_notional_usd=float(_DEFAULT_MOEX_FX["min_notional_usd"]),
        price_decimals=_decimals_from_step(tick_size),
        qty_decimals=0,
    )


async def _moex_rules(ticker: str) -> SymbolTradingRules:
    from app.services.market_data.moex_iss_provider import fetch_moex_quote_enriched

    bare = normalize_moex_symbol(ticker)
    meta = await fetch_moex_quote_enriched(bare) or {}
    lot = meta.get("lot_size") or meta.get("LOTSIZE") or _DEFAULT_MOEX["lot_size"]
    try:
        lot_size = float(lot)
    except (TypeError, ValueError):
        lot_size = float(_DEFAULT_MOEX["lot_size"])
    min_price_step = meta.get("min_step") or meta.get("MINSTEP") or _DEFAULT_MOEX["tick_size"]
    try:
        tick_size = float(min_price_step)
    except (TypeError, ValueError):
        tick_size = float(_DEFAULT_MOEX["tick_size"])
    return SymbolTradingRules(
        ticker=bare,
        venue="moex",
        tick_size=tick_size,
        lot_size=lot_size,
        min_qty=lot_size,
        min_notional_usd=float(_DEFAULT_MOEX["min_notional_usd"]),
        price_decimals=_decimals_from_step(tick_size),
        qty_decimals=_decimals_from_step(lot_size),
    )


async def _us_rules(ticker: str) -> SymbolTradingRules:
    sym = ticker.upper()
    tick_size = float(_DEFAULT_US["tick_size"])
    lot_size = float(_DEFAULT_US["lot_size"])
    min_qty = float(_DEFAULT_US["min_qty"])

    if settings.POLYGON_API_KEY:
        try:
            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                resp = await client.get(
                    f"https://api.polygon.io/v3/reference/tickers/{sym}",
                    params={"apiKey": settings.POLYGON_API_KEY},
                )
                if resp.status_code == 200:
                    result = resp.json().get("results") or {}
                    share = result.get("share_class_shares") or {}
                    if share.get("round_lot"):
                        lot_size = float(share["round_lot"])
                        min_qty = lot_size
        except Exception as exc:
            logger.debug("Polygon ticker meta failed", ticker=sym, error=str(exc))

    return SymbolTradingRules(
        ticker=sym,
        venue="us",
        tick_size=tick_size,
        lot_size=lot_size,
        min_qty=min_qty,
        min_notional_usd=float(_DEFAULT_US["min_notional_usd"]),
        price_decimals=_decimals_from_step(tick_size),
        qty_decimals=_decimals_from_step(lot_size),
    )


async def get_symbol_trading_rules(ticker: str) -> SymbolTradingRules:
    """Resolve lot/tick/min order constraints for crypto, US, or MOEX tickers."""
    from app.services.instrument.data_only import execution_flags, is_data_only_symbol

    raw = ticker.strip().upper()
    if is_data_only_symbol(raw):
        flags = execution_flags(raw)
        raise ValueError(
            f"{raw}: только данные — торговля недоступна "
            f"({flags.get('feed_label_ru') or 'EOD'})"
        )
    if not raw:
        return SymbolTradingRules(
            ticker="",
            venue="unknown",
            tick_size=0.01,
            lot_size=1.0,
            min_qty=1.0,
        )

    if is_moex_currency_ticker(raw):
        return await _moex_fx_rules(raw)

    try:
        from app.services.instrument.data_only import execution_flags, is_data_only_symbol

        if is_data_only_symbol(raw):
            flags = execution_flags(raw)
            raise ValueError(
                f"{raw}: только данные — торговля недоступна "
                f"({flags.get('feed_label_ru') or 'EOD'})"
            )
    except ImportError:
        pass

    if is_crypto_ticker(raw):
        rules = await _binance_rules(raw)
        if rules:
            return rules
        return SymbolTradingRules(
            ticker=raw,
            venue="binance",
            **_DEFAULT_CRYPTO,
            price_decimals=8,
            qty_decimals=8,
        )

    if is_moex_currency_ticker(raw):
        return await _moex_fx_rules(raw)

    if is_moex_ticker(raw):
        return await _moex_rules(raw)

    return await _us_rules(raw)


def round_price(price: float, rules: SymbolTradingRules) -> float:
    step = rules.tick_size
    if step <= 0:
        return price
    rounded = round(round(price / step) * step, rules.price_decimals)
    return max(rounded, step)


def round_qty(qty: float, rules: SymbolTradingRules) -> float:
    step = rules.lot_size
    if step <= 0:
        return qty
    rounded = round(int(qty / step) * step, rules.qty_decimals)
    return max(rounded, rules.min_qty)


def validate_order_qty_price(
    *,
    qty: float,
    price: float | None,
    rules: SymbolTradingRules,
) -> list[str]:
    errors: list[str] = []
    if qty < rules.min_qty:
        errors.append(f"Minimum quantity is {rules.min_qty}")
    rounded_qty = round_qty(qty, rules)
    if abs(qty - rounded_qty) > rules.lot_size * 0.001:
        errors.append(f"Quantity must be a multiple of {rules.lot_size}")
    if price is not None:
        rounded_px = round_price(price, rules)
        if abs(price - rounded_px) > rules.tick_size * 0.001:
            errors.append(f"Price must align to tick size {rules.tick_size}")
        if rules.min_notional_usd > 0 and qty * price < rules.min_notional_usd:
            errors.append(f"Minimum notional is ${rules.min_notional_usd:.2f}")
    return errors
