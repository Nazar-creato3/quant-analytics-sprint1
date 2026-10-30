"""Rolling window retraining for forecast model components (Step 6)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

from app.core.logging import get_logger
from app.services.forecast.gradient_boost_component import train_forecast_lgbm
from app.services.forecast.mlflow_registry import register_ensemble_run
from app.services.forecast.regime_models import train_regime_models
from app.services.forecast.shap_diagnostics import run_forecast_shap_diagnostics
from app.services.platform_honesty import ENSEMBLE_ACCURACY_CEILING

logger = get_logger(__name__)

ROLLING_TRAIN_WINDOW_DAYS = 504  # ~2 years


@dataclass(frozen=True, slots=True)
class RetrainResult:
    symbol: str
    bars_used: int
    lgbm_metrics: dict[str, object]
    regime_metrics: dict[str, dict[str, float]]
    shap_report: dict[str, object]
    trained_at: str


def retrain_forecast_models(
    closes: Sequence[float],
    *,
    symbol: str = "BENCHMARK",
    highs: Sequence[float] | None = None,
    lows: Sequence[float] | None = None,
    news_sentiment: float = 0.0,
    order_book_imbalance: float = 0.0,
    benchmark_closes: Sequence[float] | None = None,
    extras: dict[str, float] | None = None,
    volumes: Sequence[float] | None = None,
    dates: Sequence[str] | None = None,
) -> RetrainResult:
    """Retrain LightGBM + regime models on trailing window."""
    window = list(closes[-ROLLING_TRAIN_WINDOW_DAYS:])
    h = list(highs[-ROLLING_TRAIN_WINDOW_DAYS:]) if highs else None
    l = list(lows[-ROLLING_TRAIN_WINDOW_DAYS:]) if lows else None
    bench = list(benchmark_closes[-ROLLING_TRAIN_WINDOW_DAYS:]) if benchmark_closes else None
    extra = extras or {}
    vols = list(volumes[-ROLLING_TRAIN_WINDOW_DAYS:]) if volumes else None
    date_w = list(dates[-ROLLING_TRAIN_WINDOW_DAYS:]) if dates else None
    if date_w is not None and len(date_w) != len(window):
        date_w = None

    enrichments = [
        {"news_sentiment": news_sentiment, "order_book_imbalance": order_book_imbalance}
        for _ in window
    ]

    lgbm_metrics: dict[str, object] = {}
    regime_metrics: dict[str, dict[str, float]] = {}
    shap_report: dict[str, object] = {}
    try:
        lgbm_metrics = train_forecast_lgbm(
            window,
            symbol=symbol,
            highs=h,
            lows=l,
            news_sentiment=news_sentiment,
            order_book_imbalance=order_book_imbalance,
            benchmark_closes=bench,
            extras=extra,
            horizon=20,
            volumes=vols,
            dates=date_w,
        )
    except Exception as exc:
        logger.warning("Forecast LightGBM 20d retrain failed", symbol=symbol, error=str(exc))
        lgbm_metrics = {"error": 1.0, "message": str(exc)[:200]}
    try:
        lgbm_metrics["h60"] = train_forecast_lgbm(
            window,
            symbol=symbol,
            highs=h,
            lows=l,
            news_sentiment=news_sentiment,
            order_book_imbalance=order_book_imbalance,
            benchmark_closes=bench,
            extras=extra,
            horizon=60,
            volumes=vols,
            dates=date_w,
        )
    except Exception as exc:
        logger.warning("Forecast LightGBM 60d retrain failed", symbol=symbol, error=str(exc))
        lgbm_metrics["h60"] = {"error": 1.0, "message": str(exc)[:200]}

    from app.services.alpha.horizons import ALPHA_HORIZONS

    stack_out: dict[str, object] = {}
    for hz in ALPHA_HORIZONS:
        try:
            stack_out[f"h{hz}"] = train_forecast_lgbm(
                window,
                symbol=symbol,
                highs=h,
                lows=l,
                news_sentiment=news_sentiment,
                order_book_imbalance=order_book_imbalance,
                benchmark_closes=bench,
                extras=extra,
                horizon=int(hz),
                volumes=vols,
                dates=date_w,
                model_name=f"forecast_direction_lgbm_{symbol.upper()}_h{int(hz)}",
            )
        except Exception as exc:
            logger.warning(
                "Forecast LightGBM stack retrain failed",
                symbol=symbol,
                horizon=hz,
                error=str(exc),
            )
            stack_out[f"h{hz}"] = {"error": 1.0, "message": str(exc)[:200]}
    lgbm_metrics["alpha_stack"] = stack_out

    try:
        from app.services.alpha.model_card import build_card, promote_to_prod
        from app.services.forecast.feature_store import get_forecast_feature_store

        store = get_forecast_feature_store()
        freeze_id = None
        try:
            freeze_id = f"{symbol.upper()}_{datetime.now(timezone.utc).strftime('%Y%m%d')}"
            store.freeze(freeze_id)
        except Exception:
            freeze_id = None
        lin = store.lineage()
        card = build_card(
            name=f"forecast_lgbm_{symbol.upper()}",
            metrics={
                "accuracy": float(lgbm_metrics.get("purged_cv_accuracy") or 0.0),
                "outer_accuracy": float(lgbm_metrics.get("nested_cpcv_accuracy") or 0.0),
                "outer_n": float(lgbm_metrics.get("purged_cv_n") or 0),
            },
            n_train=int(lgbm_metrics.get("n_train") or 0),
            feature_lineage=(lin.content_hash if lin else ""),
            feature_freeze_id=freeze_id,
            label_recipe=str(lgbm_metrics.get("label") or "triple_barrier+meta_label"),
            cv_method=str(lgbm_metrics.get("cv_method") or "nested_combinatorial_purged_cv"),
            horizons=ALPHA_HORIZONS,
            promoted=False,
            note="research retrain; promote_to_prod only with freeze_id",
        )
        lgbm_metrics["model_card"] = promote_to_prod(card)
    except Exception as exc:
        logger.warning("alpha model card skipped", symbol=symbol, error=str(exc)[:200])

    try:
        regime_metrics = train_regime_models(window)
    except Exception as exc:
        logger.warning("Regime model retrain failed", symbol=symbol, error=str(exc))
        regime_metrics = {"error": {"skipped": True, "message": str(exc)[:200]}}

    try:
        shap = run_forecast_shap_diagnostics(
            window,
            symbol=symbol,
            enrichments=enrichments[-len(window) :],
        )
        shap_report = shap.to_dict()
        if shap.shap_available and lgbm_metrics.get("purged_cv_n"):
            register_ensemble_run(
                model_name=f"forecast_lgbm_{symbol.upper()}",
                accuracy=float(lgbm_metrics.get("purged_cv_accuracy") or 0.0),
                n=int(lgbm_metrics.get("purged_cv_n") or 0),
                params={"symbol": symbol, "honest_ceiling": ENSEMBLE_ACCURACY_CEILING},
                tags={"stage": "retrain", "shap": "true"},
                artifact_dict={"shap_report": shap_report},
            )
    except Exception as exc:
        logger.warning("SHAP diagnostics failed", symbol=symbol, error=str(exc))
        shap_report = {"error": str(exc)[:200]}

    try:
        from app.services.trading_engines.runtime.finrl_agent import train_and_save

        if len(window) >= 32:
            train_and_save(window, symbol=symbol, episodes=16)
    except Exception as exc:
        logger.warning("FinRL policy retrain failed", symbol=symbol, error=str(exc)[:200])

    return RetrainResult(
        symbol=symbol,
        bars_used=len(window),
        lgbm_metrics=lgbm_metrics,
        regime_metrics=regime_metrics,
        shap_report=shap_report,
        trained_at=datetime.now(timezone.utc).isoformat(),
    )
