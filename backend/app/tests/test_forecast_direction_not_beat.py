"""GA16-262: a market-beat flag must not replace the forecast direction."""
from __future__ import annotations

import pytest

from app.tasks.forecast import _async_refresh_daily_forecasts


@pytest.mark.asyncio
async def test_market_beat_does_not_replace_direction(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    class Session:
        async def __aenter__(self) -> "Session":
            return self

        async def __aexit__(self, *_exc: object) -> bool:
            return False

    class Instrument:
        id = 1
        symbol = "SBER"

    class Recommendation:
        value = "hold"

    class Action:
        recommendation = Recommendation()

    class Point:
        momentum_score = 0.0

    class Interval:
        horizon_days = 10

    class Hierarchy:
        calibrated_confidence = 0.4
        action_forecast = Action()
        point_forecast = Point()
        interval_forecast = Interval()

        def to_dict(self) -> dict:
            return {}

    class Ensemble:
        insufficient_history = True
        median_return = 0.0

    class Builder:
        async def build(self, *_args: object, **_kwargs: object) -> dict:
            return {"horizon_days": 10}

    class Orchestrator:
        async def get_forecast(self, *_args: object, **_kwargs: object) -> Hierarchy:
            return Hierarchy()

    class Engine:
        def compute(self, *_args: object, **_kwargs: object) -> Ensemble:
            return Ensemble()

    class Bar:
        close = 100.0
        high = 101.0
        low = 99.0
        volume = 1.0

    async def resolve(_session: object, _symbol: str) -> Instrument:
        return Instrument()

    async def enrich(*_args: object, **kwargs: object) -> dict:
        payload = dict(kwargs["payload"])
        payload["predicted_direction"] = -1
        return payload

    async def bars(*_args: object, **_kwargs: object) -> list[Bar]:
        return [Bar() for _ in range(40)]

    async def prices(*_args: object, **_kwargs: object) -> tuple:
        return [100.0] * 40, None, "series"

    async def upsert(_session: object, **kwargs: object) -> None:
        captured.update(kwargs)

    def beat(*_args: object, **_kwargs: object) -> dict:
        return {"p_beat_20": 0.9}

    async def cache_set(*_args: object, **_kwargs: object) -> None:
        return None

    monkeypatch.setattr("app.db.session.AsyncSessionLocal", lambda: Session())
    monkeypatch.setattr("app.services.instrument.resolver.resolve_or_create_instrument", resolve)
    monkeypatch.setattr("app.services.forecast.daily_builder.get_daily_forecast_builder", lambda: Builder())
    monkeypatch.setattr("app.services.prediction_hierarchy.orchestrator.get_hierarchy_orchestrator", lambda: Orchestrator())
    monkeypatch.setattr("app.services.forecast.snapshot_direction.enrich_payload_predicted_direction", enrich)
    monkeypatch.setattr("app.services.forecast.ensemble.get_ensemble_forecast_engine", lambda: Engine())
    monkeypatch.setattr("app.services.market_data.series_loader.load_forecast_price_series", prices)
    monkeypatch.setattr("app.services.market_data.bars.get_bars_for_chart", bars)
    monkeypatch.setattr("app.services.forecast.market_beat.market_beat_from_prices", beat)
    monkeypatch.setattr("app.services.forecast.excess_labels.benchmark_symbol_for", lambda _symbol: "IMOEX")
    monkeypatch.setattr("app.services.forecast.snapshot_repository.upsert_daily_snapshot", upsert)
    monkeypatch.setattr("app.services.forecast_log.emit.emit_forecast", lambda *_a, **_k: None)
    monkeypatch.setattr("app.utils.cache.cache_set", cache_set)

    result = await _async_refresh_daily_forecasts(["SBER"])
    assert result["saved"] == 1
    assert captured["payload"]["predicted_direction"] == -1
    assert captured["payload"]["market_beat"]["p_beat_20"] == 0.9
