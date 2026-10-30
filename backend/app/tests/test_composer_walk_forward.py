"""Purged walk-forward backtest of Composer IF/THEN rules."""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np

from app.services.strategy.composer.fixtures import default_composer_config
from app.services.strategy.composer.walk_forward_backtest import run_composer_walk_forward


def _closes(n: int = 220, start: str = "2024-01-01") -> list[tuple[str, float]]:
    rng = np.random.default_rng(11)
    day = date.fromisoformat(start)
    price = 100.0
    rows = [(day.isoformat(), price)]
    for _ in range(n):
        day += timedelta(days=1)
        price = max(1.0, price * (1.0 + float(rng.normal(0.0005, 0.015))))
        rows.append((day.isoformat(), price))
    return rows


def test_default_rule_backtest_has_methodology_and_metrics():
    config = default_composer_config()
    result = run_composer_walk_forward(config, symbol="AAPL", dated_closes=_closes())
    payload = result.to_dict()
    assert payload["insufficient_data"] is False
    assert payload["observations"] > 50
    assert payload["methodology"]["method"] == "purged_kfold_walk_forward"
    assert "purged" in payload["methodology"]["method_ru"].lower()
    assert payload["equity_curve"]
    assert payload["max_drawdown"] is not None
    assert payload["purged_folds"] >= 0
    # win_rate may be None only if never in market; default rule usually fires
    if payload["in_market_days"] > 0:
        assert payload["win_rate"] is not None
        assert 0.0 <= payload["win_rate"] <= 1.0


def test_short_history_is_honest_insufficient():
    result = run_composer_walk_forward(
        default_composer_config(),
        symbol="MSFT",
        dated_closes=_closes(20),
    )
    assert result.insufficient_data is True
    assert result.win_rate is None
    assert "Недостаточно" in result.notes[0]
