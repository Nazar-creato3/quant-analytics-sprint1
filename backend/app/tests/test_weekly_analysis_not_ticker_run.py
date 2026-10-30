"""GA16-273: weekly analysis must not appear as a _PORTFOLIO_ ticker run."""

from types import SimpleNamespace

from app.services.backtest_analysis.weekly import is_real_backtest_run


def test_weekly_analysis_strategy_is_not_a_ticker_run():
    assert not is_real_backtest_run(
        SimpleNamespace(strategy="weekly_analysis", ticker="SBER")
    )


def test_legacy_portfolio_ticker_is_not_a_ticker_run():
    assert not is_real_backtest_run(
        SimpleNamespace(strategy="momentum", ticker="_PORTFOLIO_")
    )


def test_real_ticker_run_passes():
    assert is_real_backtest_run(SimpleNamespace(strategy="momentum", ticker="SBER"))
