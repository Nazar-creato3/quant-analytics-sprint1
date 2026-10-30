from __future__ import annotations

from app.services.explanations.service import filter_wording
from app.services.forecast_log.store import get_store
from app.services.market_analysis.service import event_calendar, overview
from app.services.market_regime.service import _reset as reset_regime
from app.services.market_regime.service import classify
from app.services.qa.feature_flags import reset_for_tests
from app.services.risk_engine.fhs import fhs_bundle
from app.services.risk_engine.series import put_series, reset as reset_series


def setup_function() -> None:
    reset_for_tests()
    reset_series()
    reset_regime()
    get_store().reset()


def teardown_function() -> None:
    reset_series()
    reset_regime()
    get_store().reset()
    reset_for_tests()


def test_regime_and_var_match_canonical_services():
    rets = [0.004] * 40
    put_series("IMOEX", rets)
    put_series("SBER", [0.003] * 40)
    expected = classify(rets, scope="market", ticker="IMOEX")
    payload = overview()
    assert payload["regime"]["label"] == expected["label"]
    assert payload["regime"]["source"] == "market_regime"
    assert payload["risk"]["var_95"] == fhs_bundle(rets)["var_95"]
    assert payload["risk"]["method"] == "FHS"
    assert payload["text"]["source"] == "explanations"
    assert payload["text"]["key"] == "market_regime"
    assert not filter_wording(payload["text"]["phrase"])
    assert "купите" not in payload["text"]["phrase"].lower()
    assert "IMOEX" in payload["forecast_log_tickers"]
    assert payload["forecasts"][0]["source"] == "forecast_core"


def test_calendar_has_source_fields_not_invented_dates():
    cal = event_calendar()
    assert cal["data_status"] == "нет данных"
    kinds = {e["kind"] for e in cal["events"]}
    assert kinds == {"dividend_cutoff", "earnings", "cbr", "expiration"}
    assert all(e["date"] is None for e in cal["events"])
    assert all(e["source"] is None for e in cal["events"])
    assert all("updated_at" in e for e in cal["events"])


def test_breadth_missing_is_not_zero():
    payload = overview()
    assert payload["breadth"]["data_status"] == "нет данных"
    assert payload["breadth"]["advancers"] is None
    assert payload["correlations"][0]["value"] is None
    assert payload["correlations"][0]["data_status"] == "нет данных"
    assert payload["rates"]["data_status"] == "нет данных"
    assert payload["fx"]["value"] is None
