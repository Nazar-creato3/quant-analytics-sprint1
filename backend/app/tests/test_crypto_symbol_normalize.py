"""Crypto symbol normalization and forecast market-data fallbacks."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.market_data.binance_spot import (
    is_crypto_ticker,
    normalize_crypto_ticker,
    ticker_to_binance_symbol,
)
from app.services.market_data.series_loader import market_data_fetch_symbols
from app.services.prediction_hierarchy.orchestrator import PredictionHierarchyOrchestrator


@pytest.mark.parametrize(
    ("raw", "canonical", "binance"),
    [
        ("SOL", "SOL-USD", "SOLUSDT"),
        ("sol", "SOL-USD", "SOLUSDT"),
        ("SOL-USD", "SOL-USD", "SOLUSDT"),
        ("BTC-USD", "BTC-USD", "BTCUSDT"),
        ("ETH", "ETH-USD", "ETHUSDT"),
        ("SOLUSDT", "SOL-USD", "SOLUSDT"),
        ("AAPL", None, None),
        ("GAZP", None, None),
        ("EUR/USD", None, None),
        ("USDJPY", None, None),
        ("USD/CNY", None, None),
    ],
)
def test_normalize_crypto_ticker(raw: str, canonical: str | None, binance: str | None):
    assert normalize_crypto_ticker(raw) == canonical
    assert is_crypto_ticker(raw) == (canonical is not None)
    assert ticker_to_binance_symbol(raw) == binance


def test_market_data_fetch_symbols_sol_variants():
    variants = market_data_fetch_symbols("SOL")
    assert variants[0] == "SOL-USD"
    assert "SOL" in variants
    assert "SOLUSDT" in variants


def test_market_data_fetch_symbols_moex():
    variants = market_data_fetch_symbols("GAZP")
    assert variants[0] == "GAZP"


@pytest.mark.asyncio
async def test_orchestrator_degraded_forecast_when_no_bars():
    orchestrator = PredictionHierarchyOrchestrator()
    db = AsyncMock()

    with (
        patch.object(
            orchestrator,
            "_load_market_series",
            new_callable=AsyncMock,
            return_value=([], [], None),
        ),
        patch.object(
            orchestrator,
            "_load_macro_indicators",
            new_callable=AsyncMock,
            return_value={"vix": 18.0, "cpi": 3.0},
        ),
        patch.object(
            orchestrator,
            "_bootstrap_global_engine_history",
            new_callable=AsyncMock,
        ),
        patch(
            "app.services.prediction_hierarchy.orchestrator.set_cached_forecast",
            new_callable=AsyncMock,
        ),
    ):
        output = await orchestrator.get_forecast(
            db,
            99,
            symbol="SOL",
            include_narrative=True,
            use_cache=False,
        )

    assert output.metadata.get("degraded") is True
    assert output.symbol == "SOL"
    assert output.action_forecast.recommendation.value == "wait"
    assert output.narrator_insights
    assert "SOL" in output.narrator_insights[0].text_ru


@pytest.mark.asyncio
async def test_load_forecast_price_series_uses_binance_for_sol():
    from app.services.market_data.series_loader import load_forecast_price_series

    db = AsyncMock()
    db.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))

    fake_bars = [
        {"close": 100 + i, "volume": 1000, "timestamp": f"2026-01-{i+1:02d}T00:00:00+00:00"}
        for i in range(15)
    ]

    with patch(
        "app.services.market_data.series_loader.get_crypto_bars",
        new_callable=AsyncMock,
        return_value=fake_bars,
    ) as mock_crypto:
        prices, volumes, source = await load_forecast_price_series(
            db,
            instrument_id=1,
            symbol="SOL",
            persist=False,
        )

    mock_crypto.assert_called()
    assert mock_crypto.call_args[0][0] == "SOL-USD"
    assert len(prices) >= 10
    assert source == "binance"
