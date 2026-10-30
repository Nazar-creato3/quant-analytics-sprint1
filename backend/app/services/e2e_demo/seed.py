"""Load the tracked e2e/demo fixture into the local price store and paper book.

The fixture file is the source. Nothing here is fetched from an exchange.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)
_START = date(2026, 9, 1)
_market_cache: dict[str, Any] | None = None
_side_loaded = False


def fixture_path() -> Path:
    env = os.environ.get("E2E_FIXTURE_PATH", "").strip()
    candidates = []
    if env:
        candidates.append(Path(env))
    candidates.append(Path("/app/e2e_fixtures/demo_market.json"))
    candidates.append(Path(__file__).resolve().parents[4] / "e2e" / "fixtures" / "demo_market.json")
    for path in candidates:
        if path.is_file():
            return path
    raise FileNotFoundError("e2e demo fixture demo_market.json")


def read_fixture() -> dict[str, Any]:
    payload = json.loads(fixture_path().read_text(encoding="utf-8"))
    if payload.get("label") != "e2e/demo":
        raise RuntimeError("demo fixture must be labeled e2e/demo")
    if not payload.get("source"):
        raise RuntimeError("demo fixture needs an explicit source")
    return payload


def load_demo_market() -> dict[str, Any]:
    """Write price history and in-process return series from the fixture."""
    global _market_cache
    from app.services.market_data.equity_eod_store import ensure_layout, save_manifest, symbol_path
    from app.services.risk_engine.series import put_series

    payload = read_fixture()
    source = str(payload["source"])
    history: dict[str, list[Any]] = payload["history"]
    root = ensure_layout()
    counts: dict[str, int] = {}
    for ticker, closes in history.items():
        symbol = str(ticker).upper()
        bars: list[dict[str, Any]] = []
        returns: list[float] = []
        prev: float | None = None
        for offset, raw in enumerate(closes):
            px = float(raw)
            day = _START + timedelta(days=offset)
            bars.append(
                {
                    "timestamp": f"{day.isoformat()}T00:00:00+00:00",
                    "open": px,
                    "high": px,
                    "low": px,
                    "close": px,
                    "volume": 0.0,
                    "source": source,
                }
            )
            if prev not in (None, 0.0):
                returns.append((px - prev) / prev)
            prev = px
        path = symbol_path(symbol, root=root)
        path.write_text(
            json.dumps(
                {
                    "symbol": symbol,
                    "label": "e2e/demo",
                    "source": source,
                    "not_a_live_quote": True,
                    "bars": bars,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        put_series(symbol, returns)
        counts[symbol] = len(bars)
    save_manifest(
        {
            "label": "e2e/demo",
            "source": source,
            "symbols": counts,
            "synced_at": None,
        },
        root=root,
    )
    _market_cache = {
        "label": "e2e/demo",
        "source": source,
        "symbols": ",".join(sorted(counts)),
        "bars": sum(counts.values()),
    }
    return dict(_market_cache)


def apply_demo_book(user_id: str) -> dict[str, Any]:
    """Attach the fixture paper book to one user inside this API process."""
    from app.services.portfolio_book.service import ensure_account, record_transaction

    started = perf_counter()
    loaded = _market_cache if _market_cache is not None else load_demo_market()
    logger.info("e2e demo-book market", elapsed_ms=round((perf_counter() - started) * 1000, 1))
    payload = read_fixture()
    account_id = f"e2e-demo:{user_id}"
    ensure_account(
        account_id=account_id,
        user_id=user_id,
        venue="e2e-demo",
        mode="paper",
        source=str(payload["source"]),
    )
    when = datetime(_START.year, _START.month, _START.day, tzinfo=timezone.utc)
    tickers: list[str] = []
    deposit = sum((abs(Decimal(str(row["amount"]))) for row in payload["positions"]), Decimal("0"))
    if deposit > 0:
        record_transaction(
            account_id=account_id,
            user_id=user_id,
            mode="paper",
            venue="e2e-demo",
            external_id=f"e2e-demo-{user_id}-deposit",
            kind="deposit",
            instrument_id="CASH",
            ticker="CASH",
            qty="0",
            amount=str(deposit),
            ccy=str(payload.get("ccy") or "RUB"),
            event_time=when,
        )
    for row in payload["positions"]:
        ticker = str(row["ticker"]).upper()
        record_transaction(
            account_id=account_id,
            user_id=user_id,
            mode="paper",
            venue="e2e-demo",
            external_id=f"e2e-demo-{user_id}-{ticker}",
            kind="trade",
            instrument_id=ticker,
            ticker=ticker,
            qty=str(row["qty"]),
            amount=str(row["amount"]),
            ccy=str(payload.get("ccy") or "RUB"),
            event_time=when,
        )
        tickers.append(ticker)
    global _side_loaded
    if not _side_loaded:
        from app.services.bonds.ingest import ensure_fixtures as load_bond_fixture

        load_bond_fixture()
        from app.services.factor_lens.ingest import rebuild_from_fixture

        rebuild_from_fixture()
        _side_loaded = True
    logger.info(
        "e2e demo-book attached",
        user_id=user_id,
        elapsed_ms=round((perf_counter() - started) * 1000, 1),
        tickers=len(tickers),
    )
    return {**loaded, "user_id": user_id, "tickers": tickers}
