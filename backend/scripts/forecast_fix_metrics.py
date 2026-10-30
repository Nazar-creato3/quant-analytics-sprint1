"""Quick before/after metrics: momentum baseline vs per-horizon momentum + LGBM train stats."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.forecast.direction_accuracy import direction_from_return
from app.services.forecast.ensemble import (
    _momentum_bull_bear_accuracy,
    _momentum_forecast,
    _momentum_forecast_for_symbol,
    _should_invert_aapl_bearish_momentum,
    bearish_inversion_improves_accuracy,
)
from app.services.forecast.gradient_boost_component import train_forecast_lgbm
from app.services.forecast.purged_cv import evaluate_purged_accuracy
from app.services.forecast.symbol_horizon import select_best_horizon
from app.utils.wilson_ci import wilson_ci


def _fetch(symbol: str) -> list[float]:
    import yfinance as yf

    hist = yf.Ticker(symbol).history(period="504d", auto_adjust=True)
    return [float(v) for v in hist["Close"].tolist()]


def _momentum_cv(prices: list[float], horizon: int, *, invert_aapl: bool = False) -> tuple[float, int]:
    labels: list[int] = []
    preds: list[int] = []
    for i in range(30, len(prices) - horizon):
        if invert_aapl:
            mom_acc = _momentum_bull_bear_accuracy(prices[: i + 1], horizon=horizon)
            pred_ret = _momentum_forecast_for_symbol(
                prices[: i + 1],
                horizon,
                symbol="AAPL",
                invert_bearish=_should_invert_aapl_bearish_momentum(mom_acc),
            )[0]
        else:
            pred_ret = _momentum_forecast(prices[: i + 1], horizon)[0]
        pred = direction_from_return(pred_ret)
        actual_ret = (prices[i + horizon] - prices[i]) / max(prices[i], 1e-9)
        actual = direction_from_return(actual_ret)
        labels.append(actual)
        preds.append(pred)
    purged = evaluate_purged_accuracy(labels, preds, label_horizon=horizon)
    return purged.accuracy, purged.n


def main() -> None:
    symbols = ["AAPL", "MSFT", "SPY"]
    out: dict[str, object] = {"symbols": {}}
    for symbol in symbols:
        prices = _fetch(symbol)
        before_acc, before_n = _momentum_cv(prices, horizon=10)
        sel = select_best_horizon(prices, symbol=symbol, use_ensemble=False)
        after_acc, after_n = _momentum_cv(
            prices,
            sel.horizon_days,
            invert_aapl=(symbol == "AAPL"),
        )
        lgbm = train_forecast_lgbm(prices, symbol=symbol)
        b_ci = wilson_ci(int(round(before_acc * before_n)), before_n)
        a_ci = wilson_ci(int(round(after_acc * after_n)), after_n)
        inv_ok, raw_b, inv_b = bearish_inversion_improves_accuracy(prices)
        out["symbols"][symbol] = {
            "before_h10": {
                "accuracy": round(before_acc, 4),
                "n": before_n,
                "ci_low": round(b_ci.ci_low, 4),
                "ci_high": round(b_ci.ci_high, 4),
            },
            "after": {
                "horizon_days": sel.horizon_days,
                "accuracy": round(after_acc, 4),
                "n": after_n,
                "ci_low": round(a_ci.ci_low, 4),
                "ci_high": round(a_ci.ci_high, 4),
                "lgbm_prediction_std": lgbm.get("prediction_std"),
                "lgbm_is_stub": lgbm.get("is_stub"),
                "lgbm_purged_cv": lgbm.get("purged_cv_accuracy"),
            },
            "aapl_bearish_inversion_improves": inv_ok if symbol == "AAPL" else None,
            "aapl_bearish_raw_vs_inv": [round(raw_b, 4), round(inv_b, 4)] if symbol == "AAPL" else None,
        }
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
