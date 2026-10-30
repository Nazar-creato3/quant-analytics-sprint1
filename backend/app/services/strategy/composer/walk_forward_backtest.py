"""Walk-forward / purged backtest of a Composer IF/THEN rule.

This is NOT a naive in-sample equity curve of a fully simulated grid bot.
It answers: «на каких днях правило было бы истинно, и что случилось бы
с позицией long-vs-flat на следующем баре», using López de Prado purged
k-fold so overlapping labels do not leak into reported win rate / drawdown.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Sequence

import numpy as np

from app.domain.enums import AssetCategory, Strategy
from app.services.forecast.purged_cv import purged_kfold_splits
from app.services.strategy.composer.compiler import compile_composer_config, resolve_from_root
from app.services.strategy.composer.models import ComposerConfig
from app.services.strategy.types import (
    GridMode,
    InstrumentSnapshot,
    MarketRegime,
    SleeveStrategyContext,
    StrategyMarketContext,
)

FEATURE_WARMUP = 60
VOL_WINDOW = 20
VOL_RANK_WINDOW = 60
LABEL_HORIZON = 1
N_SPLITS = 5
EMBARGO_PCT = 0.01

IN_MARKET_STRATEGIES = frozenset(
    {
        Strategy.GRID.value,
        Strategy.TREND.value,
        Strategy.BREAKOUT.value,
        Strategy.ROTATION.value,
        Strategy.VOLATILITY_HARVESTING.value,
    }
)
FLAT_STRATEGIES = frozenset(
    {
        Strategy.MEAN_REVERSION.value,
        Strategy.HEDGE.value,
        Strategy.INCOME.value,
    }
)


@dataclass(frozen=True, slots=True)
class ComposerBacktestResult:
    symbol: str
    start: str
    end: str
    observations: int
    in_market_days: int
    win_rate: float | None
    max_drawdown: float | None
    total_return: float | None
    purged_cv_win_rate: float | None
    purged_folds: int
    equity_curve: list[dict[str, float | str]]
    insufficient_data: bool
    methodology: dict[str, Any]
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "start": self.start,
            "end": self.end,
            "observations": self.observations,
            "in_market_days": self.in_market_days,
            "win_rate": self.win_rate,
            "max_drawdown": self.max_drawdown,
            "total_return": self.total_return,
            "purged_cv_win_rate": self.purged_cv_win_rate,
            "purged_folds": self.purged_folds,
            "equity_curve": self.equity_curve,
            "insufficient_data": self.insufficient_data,
            "methodology": self.methodology,
            "notes": self.notes,
        }


def _regime_from_window(window_returns: np.ndarray, vol: float) -> MarketRegime:
    if window_returns.size < 5 or not np.isfinite(vol):
        return MarketRegime.UNKNOWN
    momentum = float(np.prod(1.0 + window_returns) - 1.0)
    if vol >= np.nanpercentile(np.abs(window_returns), 80) and vol > 0.02:
        return MarketRegime.HIGH_VOL
    if abs(momentum) < 0.5 * max(vol, 1e-8) * np.sqrt(len(window_returns)):
        return MarketRegime.RANGE if vol > 0.005 else MarketRegime.LOW_VOL
    return MarketRegime.TREND_UP if momentum > 0 else MarketRegime.TREND_DOWN


def _features_at(
    closes: np.ndarray,
    index: int,
) -> tuple[float, float, MarketRegime]:
    """Features using only data at or before `index` — no look-ahead."""
    start = max(0, index - VOL_RANK_WINDOW + 1)
    window = closes[start : index + 1]
    if len(window) < VOL_WINDOW + 1:
        return 0.0, 0.5, MarketRegime.UNKNOWN
    rets = window[1:] / window[:-1] - 1.0
    vol = float(np.std(rets[-VOL_WINDOW:], ddof=1)) if len(rets) >= VOL_WINDOW else float(np.std(rets, ddof=1))
    rolling_vols = []
    for j in range(VOL_WINDOW, len(rets) + 1):
        rolling_vols.append(float(np.std(rets[j - VOL_WINDOW : j], ddof=1)))
    if rolling_vols:
        rank = sum(1 for v in rolling_vols if v <= vol) / len(rolling_vols)
    else:
        rank = 0.5
    regime = _regime_from_window(rets[-VOL_WINDOW:], vol)
    try:
        from app.services.qa.feature_flags import is_enabled
        from app.services.market_regime.service import classify, to_composer_regime
        from app.services.strategy.types import MarketRegime as MR

        if is_enabled("qa_market_regime"):
            unified = classify(rets[-VOL_WINDOW:].astype(float).tolist(), scope="instrument", ticker="COMPOSER")
            regime = MR(to_composer_regime(str(unified["label"])))
    except Exception:
        pass
    return vol, float(min(1.0, max(0.0, rank))), regime


def _context(vol: float, vol_pct: float, regime: MarketRegime, last_price: float, symbol: str) -> StrategyMarketContext:
    snap = InstrumentSnapshot(
        instrument_id=1,
        symbol=symbol,
        category=AssetCategory.EQUITIES,
        last_price=Decimal(str(round(last_price, 6))),
        volatility=vol,
    )
    sleeve = SleeveStrategyContext(sleeve_id="composer-bt", category=AssetCategory.EQUITIES, instruments=(snap,))
    return StrategyMarketContext(
        sleeve=sleeve,
        regime=regime,
        session_active=True,
        volatility_percentile=vol_pct,
        asset_class="equity",
        grid_mode=GridMode.POINT,
    )


def _in_market(primary_strategy: str) -> bool:
    key = str(primary_strategy).lower()
    if key in FLAT_STRATEGIES:
        return False
    return key in IN_MARKET_STRATEGIES or key not in FLAT_STRATEGIES


def run_composer_walk_forward(
    config: ComposerConfig,
    *,
    symbol: str,
    dated_closes: Sequence[tuple[str, float]],
    now: datetime | None = None,
) -> ComposerBacktestResult:
    now = now or datetime.now(timezone.utc)
    methodology = {
        "method": "purged_kfold_walk_forward",
        "method_ru": (
            "Walk-forward с purged k-fold (López de Prado): сигнал на закрытии бара t, "
            "сделка по доходности t→t+1. Окно признаков строится только из прошлого. "
            "Это не наивный бэктест сетки и не обещание live-P&L."
        ),
        "label_horizon_bars": LABEL_HORIZON,
        "n_splits": N_SPLITS,
        "embargo_pct": EMBARGO_PCT,
        "participation_rule_ru": (
            "THEN-стратегии grid/trend = long на следующем баре; "
            "else/mean-reversion = вне рынка (flat). Полный симулятор сетки не запускается."
        ),
        "feature_warmup_bars": FEATURE_WARMUP,
        "computed_at": now.isoformat(),
        "microstructure_score": "нет спреда в дневных барах — оценка не подставляется",
    }
    notes: list[str] = []
    ordered = [(d, p) for d, p in dated_closes if p and p > 0]
    if len(ordered) < FEATURE_WARMUP + 30:
        return ComposerBacktestResult(
            symbol=symbol,
            start=ordered[0][0] if ordered else "",
            end=ordered[-1][0] if ordered else "",
            observations=0,
            in_market_days=0,
            win_rate=None,
            max_drawdown=None,
            total_return=None,
            purged_cv_win_rate=None,
            purged_folds=0,
            equity_curve=[],
            insufficient_data=True,
            methodology=methodology,
            notes=["Недостаточно истории для честного walk-forward (нужно ≥ 90 дневных баров)."],
        )

    compiled = compile_composer_config(config)
    dates = [d for d, _ in ordered]
    closes = np.array([p for _, p in ordered], dtype=float)
    n = len(closes)
    positions = np.zeros(n - 1, dtype=float)
    next_rets = closes[1:] / closes[:-1] - 1.0

    for i in range(FEATURE_WARMUP, n - 1):
        vol, vol_pct, regime = _features_at(closes, i)
        ctx = _context(vol, vol_pct, regime, float(closes[i]), symbol)
        outcome = resolve_from_root(ctx, compiled, root_branch_id=config.root_branch_id)
        positions[i] = 1.0 if _in_market(outcome.primary_strategy) else 0.0

    strat_rets = positions * next_rets
    active = positions > 0
    in_mkt = int(active.sum())
    wins = int(((strat_rets > 0) & active).sum())
    win_rate = (wins / in_mkt) if in_mkt else None
    eq = np.cumprod(1.0 + strat_rets)
    peak = np.maximum.accumulate(eq)
    dd = float((eq / peak - 1.0).min()) if eq.size else None
    total = float(eq[-1] - 1.0) if eq.size else None

    labels = (strat_rets > 0).astype(int)
    preds = active.astype(int)
    folds = purged_kfold_splits(
        len(labels),
        n_splits=N_SPLITS,
        label_horizon=LABEL_HORIZON,
        embargo_pct=EMBARGO_PCT,
    )
    fold_rates: list[float] = []
    for fold in folds:
        test = list(fold.test_indices)
        test_active = [i for i in test if i < len(preds) and preds[i] == 1]
        if len(test_active) < 3:
            continue
        hits = sum(1 for i in test_active if labels[i] == 1)
        fold_rates.append(hits / len(test_active))
    purged = float(np.mean(fold_rates)) if fold_rates else None

    curve = []
    step = max(1, (n - 1) // 80)
    for i in range(0, n - 1, step):
        curve.append({"date": dates[i + 1], "equity": float(eq[i])})
    if curve and curve[-1]["date"] != dates[-1]:
        curve.append({"date": dates[-1], "equity": float(eq[-1])})

    if in_mkt == 0:
        notes.append("Правило ни разу не вывело в рынок на истории — кривая = кэш.")

    return ComposerBacktestResult(
        symbol=symbol.upper(),
        start=dates[FEATURE_WARMUP],
        end=dates[-1],
        observations=int(n - 1 - FEATURE_WARMUP),
        in_market_days=in_mkt,
        win_rate=win_rate,
        max_drawdown=dd,
        total_return=total,
        purged_cv_win_rate=purged,
        purged_folds=len(fold_rates),
        equity_curve=curve,
        insufficient_data=False,
        methodology=methodology,
        notes=notes,
    )
