"""Retrain the direction model (LightGBM) on real history and compare it with the current one.

    docker compose ... exec backend python -m app.scripts.retrain_direction            # compare only
    docker compose ... exec backend python -m app.scripts.retrain_direction --save     # save if not worse

Why: the shipped model was fitted on an unnamed 32-column array while the code now computes
34 named features, so the columns it sees may not be the ones it learned. This script:
  1. loads ~4 years of daily OHLCV per ticker (MOEX via ISS, US via Alpaca/Yahoo through the proxy);
  2. computes features per ticker (no mixing across tickers), target = next-day direction;
  3. splits by date: train on the past, test on the last 20% of dates, 5-day embargo;
  4. prints accuracy / AUC of the current model and of the new one on the same test rows;
  5. with --save, keeps a copy of the current files (*.prev.pkl) and writes the new model
     only if it is not worse. Restart celery-pipeline and backend afterwards to load it.
"""
from __future__ import annotations

import argparse
import asyncio
import pickle
import shutil
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

MOEX = [
    "SBER", "GAZP", "LKOH", "YDEX", "ROSN", "GMKN", "PLZL", "MOEX", "NVTK", "TATN", "SNGS", "CHMF",
    "NLMK", "MAGN", "ALRS", "VTBR", "MTSS", "AFLT", "PHOR", "IRAO", "RUAL", "OZON", "X5",
]
US = ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "JPM", "XOM", "SPY", "QQQ", "BRK-B"]


async def load(symbols: list[str], days: int) -> dict[str, pd.DataFrame]:
    from app.services.market_data.client import get_bars_resolved

    end = datetime.now(timezone.utc)
    start = end - timedelta(days=days)
    sem = asyncio.Semaphore(4)
    out: dict[str, pd.DataFrame] = {}

    async def one(sym: str) -> None:
        async with sem:
            try:
                bars = await asyncio.wait_for(
                    get_bars_resolved(sym, "1d", start, end, moex_limit=days, crypto_limit=days), timeout=60
                )
            except Exception as exc:  # noqa: BLE001
                print(f"  {sym}: пропущен ({type(exc).__name__})", flush=True)
                return
            if not bars or len(bars) < 300:
                print(f"  {sym}: мало истории ({len(bars or [])} дн.)", flush=True)
                return
            df = pd.DataFrame(bars)
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True).dt.normalize()
            df = df.drop_duplicates("timestamp", keep="last").set_index("timestamp").sort_index()
            df = df[["open", "high", "low", "close", "volume"]].astype(float)
            if df.index[-1] < pd.Timestamp(end) - pd.Timedelta(days=10):
                print(f"  {sym}: история устарела (последний день {df.index[-1].date()}) — пропущен", flush=True)
                return
            out[sym] = df
            print(f"  {sym}: {len(df)} дн. ({df.index[0].date()} — {df.index[-1].date()})", flush=True)

    await asyncio.gather(*[one(s) for s in symbols])
    try:
        from app.utils.cache import close_redis_client

        await close_redis_client()
    except Exception:  # noqa: BLE001
        pass
    return out


def panel(frames: dict[str, pd.DataFrame]) -> pd.DataFrame:
    from app.services.ml.features import compute_features, get_feature_columns

    cols = get_feature_columns()
    parts = []
    for sym, df in frames.items():
        f = compute_features(df.copy())
        f = f.iloc[:-1]  # last row has no next-day target
        keep = [c for c in cols if c in f.columns]
        f = f[keep + ["target_1d"]].replace([np.inf, -np.inf], np.nan).dropna()
        f["symbol"] = sym
        parts.append(f)
    p = pd.concat(parts)
    return p.sort_index()


def evaluate(model, calibrator, X: pd.DataFrame, y: np.ndarray, width: int | None = None) -> dict[str, float]:
    from sklearn.metrics import accuracy_score, roc_auc_score

    Xm = X.iloc[:, :width] if width else X
    arr = Xm.values if width else Xm
    est = calibrator if calibrator is not None else model
    try:
        prob = est.predict_proba(arr)[:, 1]
    except Exception:  # noqa: BLE001
        prob = model.predict_proba(arr)[:, 1]
    pred = (prob >= 0.5).astype(int)
    hi = np.abs(prob - 0.5) >= 0.05  # rows where the model has a view
    return {
        "accuracy": float(accuracy_score(y, pred)),
        "auc": float(roc_auc_score(y, prob)),
        "share_with_view": float(hi.mean()),
        "accuracy_with_view": float(accuracy_score(y[hi], pred[hi])) if hi.any() else float("nan"),
    }


def main() -> None:
    import lightgbm as lgb
    from sklearn.calibration import CalibratedClassifierCV

    from app.services.ml.model import MODEL_DIR

    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=1460)
    ap.add_argument("--save", action="store_true")
    args = ap.parse_args()

    print(f"Загрузка истории: {len(MOEX)} бумаг Мосбиржи и {len(US)} США, ~{args.days // 365} года", flush=True)
    frames = asyncio.run(load(MOEX + US, args.days))
    if len(frames) < 10:
        print("Слишком мало бумаг загрузилось — обучение отменено.")
        return
    p = panel(frames)
    feats = [c for c in p.columns if c not in ("target_1d", "symbol")]
    dates = p.index.unique().sort_values()
    cut = dates[int(len(dates) * 0.8)]
    embargo_end = dates[min(len(dates) - 1, int(len(dates) * 0.8) + 5)]
    train = p[p.index < cut]
    calib = train[train.index >= dates[int(len(dates) * 0.65)]]
    fit = train[train.index < dates[int(len(dates) * 0.65)]]
    test = p[p.index > embargo_end]
    print(f"\nСтрок: обучение {len(fit)}, калибровка {len(calib)}, проверка {len(test)} (с {embargo_end.date()})", flush=True)

    model = lgb.LGBMClassifier(
        n_estimators=300, learning_rate=0.03, max_depth=5, num_leaves=24, min_child_samples=50,
        subsample=0.8, subsample_freq=1, colsample_bytree=0.8, reg_lambda=1.0, random_state=42, verbose=-1,
    )
    model.fit(fit[feats], fit["target_1d"].values)
    calibrator = CalibratedClassifierCV(model, method="isotonic", cv="prefit")
    calibrator.fit(calib[feats], calib["target_1d"].values)
    y = test["target_1d"].values
    new = evaluate(model, calibrator, test[feats], y)
    base_rate = float(y.mean())

    old = None
    try:
        with open(MODEL_DIR / "direction_lgbm.pkl", "rb") as f:
            old_model = pickle.load(f)
        old_cal = None
        try:
            with open(MODEL_DIR / "direction_lgbm_calibrator.pkl", "rb") as f:
                old_cal = pickle.load(f)
        except FileNotFoundError:
            pass
        width = int(getattr(old_model, "n_features_in_", len(feats)))
        old = evaluate(old_model, old_cal, test[feats], y, width=width)
    except Exception as exc:  # noqa: BLE001
        print(f"Текущая модель не оценена: {type(exc).__name__}: {str(exc)[:120]}")

    print(f"\nДоля дней роста в проверке: {base_rate:.1%} (угадывать «всегда рост» = {max(base_rate, 1 - base_rate):.1%})")
    fmt = lambda m: (f"точность {m['accuracy']:.1%}, AUC {m['auc']:.3f}, "  # noqa: E731
                     f"с уверенным мнением {m['share_with_view']:.0%} дней, точность в них {m['accuracy_with_view']:.1%}")
    if old:
        print(f"Текущая модель: {fmt(old)}")
    print(f"Новая модель:   {fmt(new)}")

    better = old is None or new["auc"] >= old["auc"] - 0.002
    if not args.save:
        print("\nСохранение не запрашивалось (--save).")
        return
    if not better:
        print("\nНовая модель хуже текущей — не сохраняю.")
        return
    for name in ("direction_lgbm.pkl", "direction_lgbm_calibrator.pkl"):
        src = MODEL_DIR / name
        if src.exists():
            shutil.copy2(src, MODEL_DIR / name.replace(".pkl", ".prev.pkl"))
    with open(MODEL_DIR / "direction_lgbm.pkl", "wb") as f:
        pickle.dump(model, f)
    with open(MODEL_DIR / "direction_lgbm_calibrator.pkl", "wb") as f:
        pickle.dump(calibrator, f)
    print(f"\nСохранено в {MODEL_DIR} (прежние файлы — *.prev.pkl). Перезапустите backend и celery-pipeline.")


if __name__ == "__main__":
    main()
