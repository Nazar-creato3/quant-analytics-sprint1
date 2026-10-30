"""Backtest engine, walk-forward, and result analyzer."""
from __future__ import annotations

from typing import Callable, Sequence

import numpy as np

from app.services.terminal_platform.quant.metrics import (
    cagr,
    compute_risk_metrics,
    max_drawdown,
    sharpe_ratio,
    sortino_ratio,
    volatility,
)
from app.services.terminal_platform.quant.models import (
    BacktestConfig,
    BacktestResult,
    PriceSeries,
    ReturnSeries,
    WalkForwardFold,
    WalkForwardResult,
)
from app.services.terminal_platform.quant.utils import returns_from_prices

SignalFn = Callable[[Sequence[float], int, BacktestConfig], int]


def momentum_signal(prices: Sequence[float], index: int, config: BacktestConfig) -> int:
    """Simple lookback momentum: long if price > lookback-ago price."""
    lookback = config.signal_lookback
    if index < lookback:
        return 0
    if prices[index] > prices[index - lookback]:
        return 1
    if config.allow_short and prices[index] < prices[index - lookback]:
        return -1
    return 0 if not config.allow_short else -1


def run_backtest(
    prices: PriceSeries | Sequence[float],
    params: BacktestConfig | None = None,
    *,
    strategy: SignalFn | None = None,
) -> BacktestResult:
    """Run a bar-by-bar backtest with a pluggable signal function."""
    config = params or BacktestConfig()
    signal_fn = strategy or momentum_signal
    price_values = list(prices.values) if isinstance(prices, PriceSeries) else [float(p) for p in prices]
    if len(price_values) < config.signal_lookback + 2:
        raise ValueError("insufficient price history for backtest")

    capital = float(config.initial_capital)
    equity = [capital]
    period_returns: list[float] = []
    signals: list[int] = [0]
    position = 0
    n_trades = 0
    cost = config.transaction_cost_bps / 10_000.0

    for i in range(1, len(price_values)):
        desired = signal_fn(price_values, i - 1, config)
        if desired != position:
            n_trades += 1
            capital *= 1.0 - cost
            position = desired
        ret = price_values[i] / price_values[i - 1] - 1.0
        pnl = position * ret
        capital *= 1.0 + pnl
        equity.append(capital)
        period_returns.append(pnl)
        signals.append(position)

    metadata: dict = {"strategy": getattr(signal_fn, "__name__", "custom"), "backtest_engine": "numpy"}
    if strategy is None:
        try:
            from app.services.trading_engines.runtime.overlays import try_vectorbt_overlay

            overlay = try_vectorbt_overlay(price_values, lookback=config.signal_lookback)
            if overlay is not None:
                metadata["vectorbt"] = overlay
                metadata["backtest_engine"] = "numpy+vectorbt"
        except Exception:
            pass

    return analyze_backtest(
        equity,
        period_returns,
        signals=signals,
        n_trades=n_trades,
        config=config,
        metadata=metadata,
    )


def walk_forward(
    prices: PriceSeries | Sequence[float],
    train_window: int,
    test_window: int,
    params: BacktestConfig | None = None,
    *,
    strategy: SignalFn | None = None,
) -> WalkForwardResult:
    """Rolling walk-forward: train window unused for param fit (signal is rule-based),
    test window evaluated sequentially; lookback may use prices inside the fold.
    """
    config = params or BacktestConfig()
    price_values = list(prices.values) if isinstance(prices, PriceSeries) else [float(p) for p in prices]
    ppy = (
        prices.periods_per_year
        if isinstance(prices, PriceSeries)
        else config.periods_per_year
    )
    if train_window < 10 or test_window < 5:
        raise ValueError("train_window >= 10 and test_window >= 5 required")
    if len(price_values) < train_window + test_window:
        raise ValueError("price history shorter than train_window + test_window")

    folds: list[WalkForwardFold] = []
    start = 0
    fold_index = 0
    while start + train_window + test_window <= len(price_values):
        test_start = start + train_window
        test_end = test_start + test_window
        # Include lookback cushion from train so signals are defined on test bars.
        cushion = max(config.signal_lookback, 1)
        slice_start = max(0, test_start - cushion)
        window_prices = PriceSeries(
            symbol="WF",
            values=price_values[slice_start:test_end],
            periods_per_year=ppy,
        )
        full = run_backtest(window_prices, config, strategy=strategy)
        # Keep only test-segment equity/returns for fold metrics.
        offset = test_start - slice_start
        test_equity = full.equity_curve[offset:]
        test_returns = full.returns[offset:] if offset < len(full.returns) else full.returns
        test_signals = full.signals[offset:]
        fold_result = analyze_backtest(
            test_equity if len(test_equity) >= 2 else full.equity_curve,
            test_returns if test_returns else full.returns,
            signals=test_signals if test_signals else full.signals,
            n_trades=full.n_trades,
            config=config,
            metadata={"fold": fold_index},
        )
        folds.append(
            WalkForwardFold(
                fold_index=fold_index,
                train_start=start,
                train_end=test_start,
                test_start=test_start,
                test_end=test_end,
                test_result=fold_result,
            )
        )
        start += test_window
        fold_index += 1

    if not folds:
        raise ValueError("no walk-forward folds produced")

    # Stitch test returns for aggregate.
    agg_returns: list[float] = []
    for fold in folds:
        agg_returns.extend(fold.test_result.returns)
    agg_equity = [config.initial_capital]
    for r in agg_returns:
        agg_equity.append(agg_equity[-1] * (1.0 + r))
    aggregate = analyze_backtest(
        agg_equity,
        agg_returns,
        signals=[0] * len(agg_equity),
        n_trades=sum(f.test_result.n_trades for f in folds),
        config=config,
        metadata={"n_folds": len(folds)},
    )
    mean_sharpe = float(np.mean([f.test_result.sharpe for f in folds]))
    mean_dd = float(np.mean([f.test_result.max_drawdown for f in folds]))
    return WalkForwardResult(
        folds=folds,
        aggregate=aggregate,
        mean_test_sharpe=mean_sharpe,
        mean_test_max_drawdown=mean_dd,
    )


def analyze_backtest(
    equity_curve: Sequence[float],
    returns: Sequence[float],
    *,
    signals: Sequence[int] | None = None,
    n_trades: int = 0,
    config: BacktestConfig | None = None,
    metadata: dict | None = None,
) -> BacktestResult:
    """Derive performance stats from equity / return series."""
    cfg = config or BacktestConfig()
    equity = [float(x) for x in equity_curve]
    rets = [float(x) for x in returns]
    if len(equity) < 2:
        raise ValueError("equity_curve needs at least 2 points")

    price_series = PriceSeries(
        symbol="BT",
        values=equity,
        periods_per_year=cfg.periods_per_year,
    )
    ret_series = ReturnSeries(
        symbol="BT",
        values=rets if rets else returns_from_prices(equity).values,
        periods_per_year=cfg.periods_per_year,
        risk_free_rate=cfg.risk_free_rate,
    )
    metrics = compute_risk_metrics(ret_series, prices=price_series)
    wins = sum(1 for r in ret_series.values if r > 0)
    total = len(ret_series.values) or 1
    total_return = equity[-1] / equity[0] - 1.0

    return BacktestResult(
        equity_curve=equity,
        returns=list(ret_series.values),
        signals=list(signals) if signals is not None else [0] * len(equity),
        total_return=float(total_return),
        cagr=float(cagr(price_series)),
        sharpe=float(sharpe_ratio(ret_series)),
        sortino=float(sortino_ratio(ret_series)),
        max_drawdown=float(max_drawdown(price_series)),
        volatility_annual=float(volatility(ret_series, annualize=True)),
        win_rate=float(wins / total),
        n_trades=int(n_trades),
        metrics=metrics,
        metadata=metadata or {},
    )
