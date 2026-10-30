"""Crypto stack API — Collect (CCXT) health + sample market endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.deps import get_current_user_email
from app.core.logging import get_logger
from app.services.crypto_stack.health import stack_health
from app.services.crypto_stack.market import (
    cryptodatapy_status,
    fetch_ohlcv,
    fetch_ticker,
    ta_snapshot,
)

router = APIRouter(prefix="/crypto-stack", tags=["crypto-stack"])
logger = get_logger(__name__)
_UNAVAILABLE = "Нет данных"


@router.get("/health")
async def crypto_stack_health(
    _: str = Depends(get_current_user_email),
) -> dict:
    """Package availability for the crypto integration stack."""
    return stack_health()


@router.get("/ticker")
async def crypto_ticker(
    symbol: str = Query("BTC/USDT", description="CCXT symbol, e.g. BTC/USDT"),
    _: str = Depends(get_current_user_email),
) -> dict:
    """Sample public ticker (default BTCUSDT via Binance/CCXT)."""
    try:
        return fetch_ticker(symbol=symbol)
    except Exception as exc:  # noqa: BLE001
        logger.warning("crypto_stack ticker failed", error=str(exc), symbol=symbol)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_UNAVAILABLE,
        ) from exc


@router.get("/ohlcv")
async def crypto_ohlcv(
    symbol: str = Query("BTC/USDT"),
    timeframe: str = Query("1h", pattern="^(1m|5m|15m|1h|4h|1d)$"),
    limit: int = Query(50, ge=1, le=500),
    _: str = Depends(get_current_user_email),
) -> dict:
    """Sample OHLCV candles via CCXT Binance public API."""
    try:
        return fetch_ohlcv(symbol=symbol, timeframe=timeframe, limit=limit)
    except Exception as exc:  # noqa: BLE001
        logger.warning("crypto_stack ohlcv failed", error=str(exc), symbol=symbol)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_UNAVAILABLE,
        ) from exc


@router.get("/ta")
async def crypto_ta(
    symbol: str = Query("BTC/USDT"),
    timeframe: str = Query("1h", pattern="^(1m|5m|15m|1h|4h|1d)$"),
    limit: int = Query(100, ge=20, le=500),
    _: str = Depends(get_current_user_email),
) -> dict:
    """TA snapshot (SMA/EMA/RSI) derived from OHLCV."""
    try:
        return ta_snapshot(symbol=symbol, timeframe=timeframe, limit=limit)
    except Exception as exc:  # noqa: BLE001
        logger.warning("crypto_stack ta failed", error=str(exc), symbol=symbol)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=_UNAVAILABLE,
        ) from exc


@router.get("/cryptodatapy")
async def crypto_datapapy_probe(
    _: str = Depends(get_current_user_email),
) -> dict:
    """CryptoDataPy import/version probe (no paid API keys required)."""
    return cryptodatapy_status()
