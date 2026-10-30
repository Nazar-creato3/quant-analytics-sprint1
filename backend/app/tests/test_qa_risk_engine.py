"""Prompt 09: unified FHS risk engine, backtests, Euler, shadow."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.portfolio_book.service import ensure_account, record_transaction
from app.services.portfolio_book.store import get_book
from app.services.qa.feature_flags import reset_for_tests
from app.tests.qa_session import bind_session_user, clear_session_user
from app.services.risk_engine.backtest import (
    evaluate_series,
    exception_flags,
    kupiec_lr,
    traffic_light_99,
)
from app.services.risk_engine.euler import euler_allocate
from app.services.risk_engine.fhs import fhs_bundle, fhs_var_es
from app.services.risk_engine.series import put_series, reset as reset_series
from app.services.risk_engine.service import (
    as_dict,
    compute_risk,
    compute_risk_for_user,
    store_backtest,
)
from app.services.risk_engine.shadow import diffs, reset_diffs, shadow_compare


def setup_function() -> None:
    reset_for_tests()
    get_book().reset()
    reset_series()
    reset_diffs()


def teardown_function() -> None:
    get_book().reset()
    reset_series()
    reset_diffs()
    reset_for_tests()
    clear_session_user()


def _normal(n: int, seed: int, scale: float = 0.01) -> list[float]:
    rng = np.random.default_rng(seed)
    return rng.normal(0.0, scale, size=n).tolist()


def test_fhs_same_method_ticker_and_portfolio():
    r = _normal(200, 3)
    one = compute_risk(r, tickers=["SBER"])
    put_series("SBER", r)
    ensure_account(account_id="p1", user_id="u1", venue="bots", mode="paper")
    record_transaction(
        account_id="p1",
        user_id="u1",
        mode="paper",
        venue="bots",
        external_id="t1",
        kind="trade",
        instrument_id="SBER",
        ticker="SBER",
        qty="1",
        amount="100",
        ccy="RUB",
        event_time=datetime(2024, 1, 2, tzinfo=timezone.utc),
    )
    port = compute_risk_for_user("u1")
    assert abs(port["var_95"] - one.var_95) < 1e-9
    assert port["source"] == "оценка риска"
    assert "risk_engine" not in port["source"]


def test_euler_components_sum_to_portfolio():
    rng = np.random.default_rng(4)
    a = rng.normal(0, 0.012, 180)
    b = 0.6 * a + rng.normal(0, 0.008, 180)
    matrix = np.column_stack([a, b]).tolist()
    alloc = euler_allocate(matrix, [0.5, 0.5])
    assert abs(sum(alloc["component_var"]) - alloc["portfolio_var"]) < 1e-9


def test_e46_11_single_asset_component_equals_portfolio_var():
    rng = np.random.default_rng(0)
    r = rng.normal(0.0004, 0.012, 80)
    matrix = np.column_stack([r]).tolist()
    alloc = euler_allocate(matrix, [1.0])
    assert alloc["portfolio_var"] > 0
    assert abs(alloc["component_var"][0] - alloc["portfolio_var"]) < 1e-9
    assert abs(sum(alloc["component_var"]) - alloc["portfolio_var"]) < 1e-9


def test_kupiec_and_traffic_light():
    flags = [0] * 240 + [1] * 4
    assert kupiec_lr(flags, 0.01) >= 0
    assert traffic_light_99(4) == "green"
    assert traffic_light_99(10) == "red"
    r = _normal(80, 8)
    var = [0.02] * 80
    assert len(exception_flags(r, var)) == 80


def test_three_control_portfolios_backtest():
    ru = _normal(756, 11, 0.015)
    mix = [0.7 * x + 0.3 * y for x, y in zip(ru, _normal(756, 12, 0.004))]
    us_crypto = _normal(756, 13, 0.03)
    for name, series in (("ru_equity", ru), ("mixed_bonds", mix), ("us_crypto", us_crypto)):
        report = evaluate_series(series, window=120)
        assert report["traffic_light"] in {"green", "yellow", "red"}
        assert report["status"] in {"ready", "beta"}
        store_backtest(name, report)
    from app.services.risk_engine.service import backtests

    assert set(backtests()) == {"ru_equity", "mixed_bonds", "us_crypto"}


def test_shadow_and_api():
    r = _normal(50, 21)
    shadow_compare(r)
    assert diffs()
    put_series("GAZP", r)
    ensure_account(account_id="p2", user_id="u2", venue="bots", mode="paper")
    record_transaction(
        account_id="p2",
        user_id="u2",
        mode="paper",
        venue="bots",
        external_id="t2",
        kind="trade",
        instrument_id="GAZP",
        ticker="GAZP",
        qty="2",
        amount="200",
        ccy="RUB",
        event_time=datetime(2024, 2, 1, tzinfo=timezone.utc),
    )
    bind_session_user("u2")
    client = TestClient(app)
    body = client.get("/api/v1/risk", params={"user_id": "u2"}).json()
    assert body["method"] == "fhs_ewma"
    assert "var_95" in body
    packed = as_dict(compute_risk(r, nav_rub=100_000))
    assert packed["rubles_var_95"] is not None
    assert fhs_bundle(r)["var_95"] == fhs_var_es(r, alpha=0.05)[0]


@pytest.mark.asyncio
async def test_e46_08_chat_risk_no_series_is_no_data_not_hierarchy():
    from app.services.chat.tools import _tool_risk

    body = await _tool_risk(AsyncMock(), "NOSERIES")
    assert body.get("data_status") == "нет данных"
    assert body.get("risk_metrics") is None


@pytest.mark.asyncio
async def test_e46_08_chat_portfolio_risk_uses_engine():
    from app.services.chat.tools import _tool_portfolio_risk

    body = await _tool_portfolio_risk(AsyncMock(), owner_user_id="u-empty", owner_email=None)
    assert body.get("method") == "fhs_ewma"
    assert "historical_simulation" not in str(body)
