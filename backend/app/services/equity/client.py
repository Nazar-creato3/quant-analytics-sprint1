"""yfinance-backed equity data fetcher (free public API)."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)


def _parse_yf_date(value: Any) -> datetime | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        import pandas as pd

        ts = pd.Timestamp(value)
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        return ts.to_pydatetime()
    except Exception:
        return None


def _fetch_yfinance_sync(symbol: str) -> dict[str, Any]:
    import yfinance as yf

    ticker = yf.Ticker(symbol.upper())
    info = ticker.info or {}
    calendar = ticker.calendar
    actions = ticker.actions
    splits = ticker.splits

    earnings_rows: list[dict[str, Any]] = []
    if calendar is not None and not getattr(calendar, "empty", True):
        for idx, row in calendar.iterrows():
            report_date = _parse_yf_date(idx)
            if report_date is None:
                continue
            earnings_rows.append(
                {
                    "symbol": symbol.upper(),
                    "report_date": report_date,
                    "fiscal_period": None,
                    "eps_estimate": None,
                    "source": "yfinance",
                    "raw_data": {str(k): str(v) for k, v in row.to_dict().items()},
                }
            )

    dividend_rows: list[dict[str, Any]] = []
    split_rows: list[dict[str, Any]] = []
    if actions is not None and not getattr(actions, "empty", True):
        for idx, row in actions.iterrows():
            event_at = _parse_yf_date(idx)
            if event_at is None:
                continue
            dividend_val = row.get("Dividends", 0) if hasattr(row, "get") else 0
            split_val = row.get("Stock Splits", 0) if hasattr(row, "get") else 0
            try:
                dividend_amount = float(dividend_val or 0)
            except (TypeError, ValueError):
                dividend_amount = 0.0
            try:
                split_ratio = float(split_val or 0)
            except (TypeError, ValueError):
                split_ratio = 0.0
            if dividend_amount > 0:
                dividend_rows.append(
                    {
                        "symbol": symbol.upper(),
                        "ex_dividend_date": event_at,
                        "amount": Decimal(str(dividend_amount)),
                        "currency": "USD",
                        "source": "yfinance",
                    }
                )
            if split_ratio > 0:
                split_rows.append(
                    {
                        "symbol": symbol.upper(),
                        "split_date": event_at,
                        "ratio": Decimal(str(split_ratio)),
                        "source": "yfinance",
                    }
                )

    if splits is not None and not getattr(splits, "empty", True):
        for idx, ratio in splits.items():
            event_at = _parse_yf_date(idx)
            if event_at is None:
                continue
            try:
                ratio_val = float(ratio)
            except (TypeError, ValueError):
                continue
            if ratio_val <= 0:
                continue
            split_rows.append(
                {
                    "symbol": symbol.upper(),
                    "split_date": event_at,
                    "ratio": Decimal(str(ratio_val)),
                    "source": "yfinance",
                }
            )

    return {
        "symbol": symbol.upper(),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "earnings": earnings_rows,
        "dividends": dividend_rows,
        "splits": split_rows,
    }


async def fetch_equity_fundamentals(symbol: str) -> dict[str, Any]:
    """Fetch dividends, splits, and earnings calendar via yfinance (non-blocking wrapper)."""
    try:
        return await asyncio.to_thread(_fetch_yfinance_sync, symbol)
    except Exception as exc:
        logger.warning("yfinance equity fetch failed", symbol=symbol, error=str(exc))
        return {
            "symbol": symbol.upper(),
            "sector": None,
            "industry": None,
            "earnings": [],
            "dividends": [],
            "splits": [],
        }
