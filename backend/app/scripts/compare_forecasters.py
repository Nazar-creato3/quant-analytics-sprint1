"""Which model guesses the 5-day direction best on our own history? Old vs new vs neural nets.

    docker compose ... exec backend python -m app.scripts.compare_forecasters
    docker compose ... exec backend python -m app.scripts.compare_forecasters --quick   # 8 tickers

For every ticker the last ~120 trading days give 60 forecast origins (every 2nd day). At each
origin a model sees prices up to that day only and calls the direction of the next 5 days.
Training of LightGBM / N-BEATS uses data strictly before the first origin (minus 5 days),
so no model peeks into the test period. Prints a table: accuracy, number of calls, a 95%
interval and the gap to the "always up" baseline. Read-only: saves nothing.
"""
from __future__ import annotations

import argparse
import asyncio
import math
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

MOEX = ["SBER", "GAZP", "LKOH", "YDEX", "ROSN", "GMKN", "PLZL", "MOEX", "NVTK", "TATN", "CHMF", "MTSS"]
US = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "JPM", "SPY"]
H = 5
N_ORIGINS = 60  # with 20 tickers: ~1 200 calls, 95% interval about ±2.8 p.p.
STEP = 2


def _dir(x: float) -> int:
    return 1 if x > 0 else -1


async def _load(symbols: list[str], days: int) -> dict[str, pd.DataFrame]:
    from app.scripts.retrain_direction import load

    return await load(symbols, days)


# ── models: each returns a predicted 5-day direction (+1 / -1) from history up to the origin ──

def m_always_up(_c: np.ndarray) -> int:
    return 1


def m_momentum(c: np.ndarray) -> int:
    return _dir(c[-1] / c[-21] - 1) if len(c) > 21 else 1


def m_arima(c: np.ndarray) -> int | None:
    import warnings

    try:
        from statsmodels.tsa.arima.model import ARIMA
    except ImportError:
        return None
    r = np.diff(np.log(c[-250:]))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fit = ARIMA(r, order=(1, 0, 1)).fit()
    return _dir(float(np.sum(fit.forecast(steps=H))))


class LGBM5:
    """LightGBM on the platform's 34 features, target = 5-day direction, trained before the test."""

    def __init__(self, frames: dict[str, pd.DataFrame], cutoff: dict[str, int]) -> None:
        import lightgbm as lgb

        from app.services.ml.features import compute_features, get_feature_columns

        self.cols = get_feature_columns()
        self.feat: dict[str, pd.DataFrame] = {}
        parts = []
        for sym, df in frames.items():
            f = compute_features(df.copy()).replace([np.inf, -np.inf], np.nan)
            self.feat[sym] = f
            train = f.iloc[: cutoff[sym] - H].dropna(subset=[c for c in self.cols if c in f.columns] + ["target_5d"])
            parts.append(train)
        tr = pd.concat(parts)
        self.cols = [c for c in self.cols if c in tr.columns]
        self.model = lgb.LGBMClassifier(
            n_estimators=300, learning_rate=0.03, max_depth=5, num_leaves=24, min_child_samples=50,
            subsample=0.8, subsample_freq=1, colsample_bytree=0.8, random_state=42, verbose=-1,
        )
        self.model.fit(tr[self.cols], tr["target_5d"].values)

    def predict(self, sym: str, i: int) -> int | None:
        row = self.feat[sym].iloc[[i]][self.cols]
        if row.isna().any(axis=None):
            return None
        return 1 if self.model.predict_proba(row)[0, 1] >= 0.5 else -1


class Chronos:
    def __init__(self) -> None:
        import torch
        from chronos import BaseChronosPipeline

        self.torch = torch
        last = None
        for mid in ("amazon/chronos-bolt-small", "amazon/chronos-t5-small", "amazon/chronos-t5-tiny"):
            try:
                self.pipe = BaseChronosPipeline.from_pretrained(mid, device_map="cpu", torch_dtype=torch.float32)
                self.name = mid.split("/")[-1]
                return
            except Exception as exc:  # noqa: BLE001
                last = exc
        raise RuntimeError(f"Chronos weights unavailable: {last}")

    def predict(self, c: np.ndarray) -> int:
        ctx = self.torch.tensor(c[-512:], dtype=self.torch.float32)
        q, _mean = self.pipe.predict_quantiles(ctx, prediction_length=H, quantile_levels=[0.5])
        return _dir(float(q[0, -1, 0]) / c[-1] - 1)


class NBeats:
    """One N-BEATS per ticker on log prices, trained before the test, then rolled forward."""

    def __init__(self) -> None:
        from darts.models import NBEATSModel  # noqa: F401

        self.models: dict[str, object] = {}

    def fit(self, sym: str, c: np.ndarray) -> None:
        from darts import TimeSeries
        from darts.models import NBEATSModel

        s = TimeSeries.from_values(np.log(c).astype(np.float32))
        m = NBEATSModel(
            input_chunk_length=60, output_chunk_length=H, n_epochs=15, random_state=42,
            pl_trainer_kwargs={"enable_progress_bar": False, "logger": False, "enable_model_summary": False},
        )
        m.fit(s)
        self.models[sym] = m

    def predict(self, sym: str, c: np.ndarray) -> int:
        from darts import TimeSeries

        s = TimeSeries.from_values(np.log(c[-120:]).astype(np.float32))
        f = self.models[sym].predict(H, series=s, verbose=False)
        return _dir(float(np.exp(f.values()[-1, 0])) / c[-1] - 1)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--days", type=int, default=1100)
    args = ap.parse_args()
    global N_ORIGINS, STEP
    symbols = (MOEX[:5] + US[:3]) if args.quick else (MOEX + US)
    if args.quick:
        N_ORIGINS, STEP = 20, 3

    print(f"Загрузка истории: {len(symbols)} бумаг", flush=True)
    frames = asyncio.run(_load(symbols, args.days))
    frames = {s: f for s, f in frames.items() if len(f) > 400}
    origins = {s: [len(f) - H - 1 - STEP * k for k in range(N_ORIGINS)][::-1] for s, f in frames.items()}
    cutoff = {s: o[0] for s, o in origins.items()}

    models: dict[str, object] = {"Всегда рост": m_always_up, "Импульс 20 дн.": m_momentum, "ARIMA": m_arima}
    t = time.monotonic()
    try:
        models["LightGBM (наши 34 признака)"] = LGBM5(frames, cutoff)
        print(f"LightGBM обучен за {time.monotonic() - t:.0f} с", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"LightGBM пропущен: {type(exc).__name__}: {str(exc)[:120]}", flush=True)
    try:
        t = time.monotonic()
        ch = Chronos()
        models[f"Chronos ({ch.name})"] = ch
        print(f"Chronos загружен за {time.monotonic() - t:.0f} с", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"Chronos пропущен: {type(exc).__name__}: {str(exc)[:160]}", flush=True)
    try:
        nb = NBeats()
        t = time.monotonic()
        for s, f in frames.items():
            nb.fit(s, f["close"].values[: cutoff[s] - H])
        models["N-BEATS"] = nb
        print(f"N-BEATS обучен на {len(frames)} бумагах за {time.monotonic() - t:.0f} с", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"N-BEATS пропущен: {type(exc).__name__}: {str(exc)[:160]}", flush=True)

    hits: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
    for name, m in models.items():
        t = time.monotonic()
        for s, f in frames.items():
            c_all = f["close"].values
            mk = "MOEX" if s in MOEX else "US"
            for i in origins[s]:
                c = c_all[: i + 1]
                actual = _dir(c_all[i + H] / c_all[i] - 1)
                try:
                    if isinstance(m, LGBM5):
                        p = m.predict(s, i)
                    elif isinstance(m, NBeats):
                        p = m.predict(s, c)
                    elif isinstance(m, Chronos):
                        p = m.predict(c)
                    else:
                        p = m(c)  # type: ignore[operator]
                except Exception:  # noqa: BLE001
                    p = None
                if p is None:
                    continue
                hits[name][mk].append(int(p == actual))
                hits[name]["Все"].append(int(p == actual))
        print(f"  {name}: прогноз за {time.monotonic() - t:.0f} с", flush=True)

    base = np.mean(hits["Всегда рост"]["Все"]) if hits["Всегда рост"]["Все"] else float("nan")
    print(f"\nТочность направления на 5 дней ({N_ORIGINS} точек на бумагу, {len(frames)} бумаг):")
    print(f"{'Модель':<30} {'Все':>7} {'±95%':>6} {'MOEX':>7} {'США':>7} {'n':>5} {'к «всегда рост»':>16}")
    for name, by in hits.items():
        a = by["Все"]
        if not a:
            continue
        p = float(np.mean(a))
        ci = 1.96 * math.sqrt(p * (1 - p) / len(a))
        mo = f"{np.mean(by['MOEX']):.1%}" if by["MOEX"] else "—"
        us = f"{np.mean(by['US']):.1%}" if by["US"] else "—"
        print(f"{name:<30} {p:>7.1%} {ci:>6.1%} {mo:>7} {us:>7} {len(a):>5} {p - base:>+15.1%}")
    print("\nПравило решения: модель берём, если она лучше LightGBM на 2–3 п.п. и выше «всегда рост»,"
          " и разница больше интервала ±95%.")


if __name__ == "__main__":
    main()
