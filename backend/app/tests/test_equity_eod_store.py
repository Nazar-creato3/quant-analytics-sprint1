"""Equity EOD local board cache."""
from __future__ import annotations

import json
from pathlib import Path

from app.services.market_data.equity_eod_store import (
    EquityEodLocalClient,
    read_latest_quote,
    sync_equity_eod,
)


def test_read_quote_from_cache(tmp_path: Path, monkeypatch) -> None:
    from app.services.market_data import equity_eod_store as store

    root = tmp_path / "eod"
    (root / "current").mkdir(parents=True)
    (root / "current" / "SPY.json").write_text(
        json.dumps(
            {
                "symbol": "SPY",
                "source": "tiingo",
                "bars": [
                    {
                        "timestamp": "2026-09-15T00:00:00+00:00",
                        "open": 100,
                        "high": 101,
                        "low": 99,
                        "close": 100.5,
                        "volume": 1,
                        "source": "tiingo",
                    },
                    {
                        "timestamp": "2026-09-16T00:00:00+00:00",
                        "open": 100.5,
                        "high": 102,
                        "low": 100,
                        "close": 101.5,
                        "volume": 2,
                        "source": "tiingo",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(store, "bulk_root", lambda: root)
    q = read_latest_quote("SPY")
    assert q["price"] == 101.5
    assert abs(float(q["change_pct"]) - ((101.5 / 100.5) - 1) * 100) < 1e-6


async def _client_bars(tmp_path: Path, monkeypatch):
    import asyncio
    from datetime import datetime, timezone

    from app.services.market_data import equity_eod_store as store

    root = tmp_path / "eod"
    (root / "current").mkdir(parents=True)
    (root / "current" / "QQQ.json").write_text(
        json.dumps(
            {
                "symbol": "QQQ",
                "bars": [
                    {
                        "timestamp": "2026-09-15T00:00:00+00:00",
                        "open": 1,
                        "high": 1,
                        "low": 1,
                        "close": 1,
                        "volume": 0,
                        "source": "yahoo_chart",
                    },
                    {
                        "timestamp": "2026-09-16T00:00:00+00:00",
                        "open": 1,
                        "high": 2,
                        "low": 1,
                        "close": 2,
                        "volume": 0,
                        "source": "yahoo_chart",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(store, "bulk_root", lambda: root)
    client = EquityEodLocalClient()
    bars = await client.get_bars(
        "QQQ",
        "1d",
        datetime(2026, 9, 1, tzinfo=timezone.utc),
        datetime(2026, 9, 20, tzinfo=timezone.utc),
    )
    assert len(bars) == 2


def test_client_bars(tmp_path: Path, monkeypatch) -> None:
    import asyncio

    asyncio.run(_client_bars(tmp_path, monkeypatch))
