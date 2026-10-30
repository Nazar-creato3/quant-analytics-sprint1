"""
Maneuver Generator.
Orchestrates the full signal → maneuver pipeline.
Always produces exactly MANEUVER_COUNT slots.
Unfilled slots become NO_TRADE entries.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.risk.profit_projection import IntervalForecastLike

import pandas as pd

from app.core.config import settings
from app.core.logging import get_logger
from app.services.market_regime.service import label_from_closes
from app.services.ml.model import ModelPrediction, get_classifier
from app.services.risk.confidence_filter import (
    ConfidenceFilterResult,
    build_confidence_filter_result,
    max_directional_confidence,
    passes_confidence_threshold,
)
from app.services.risk.position_sizing import conviction_risk_pct, volume_zscore
from app.services.risk.portfolio_sizing import resolve_portfolio_size_usd
from app.services.risk.engine import (
    PortfolioState,
    RiskEngine,
    RiskParameters,
    TradeRiskResult,
)

logger = get_logger(__name__)

MANEUVER_COUNT = settings.MANEUVER_COUNT
# Minimum ML confidence for optional backfill slots (labeled «ниже порога»).
BACKFILL_CONFIDENCE_FLOOR = 0.28
# Hard floor when topping up to fill all proposal slots from the watchlist.
MIN_SLOT_CONFIDENCE = 0.26

# Market regime favorability in 0..1 (used by the regime scoring component).
_REGIME_FAVORABILITY: dict[str, float] = {
    "trend_up": 1.0,
    "range": 0.6,
    "volatility": 0.45,
    "trend_down": 0.3,
    "crisis": 0.2,
    "insufficient": 0.5,
    "bull": 1.0,
    "sideways": 0.6,
    "volatile": 0.45,
    "bear": 0.3,
    "unknown": 0.5,
}


def score_weights() -> tuple[float, float, float]:
    """Return normalized (technical, news/events, regime) weights from settings.

    Defaults: technical 40%, news/events 35%, regime 25%. Values are read from
    ``SCORE_WEIGHT_*`` and normalized so they always sum to 1.0 (falls back to
    defaults if the configured weights sum to zero).
    """
    w_tech = max(0.0, float(settings.SCORE_WEIGHT_TECHNICAL))
    w_news = max(0.0, float(settings.SCORE_WEIGHT_NEWS))
    w_regime = max(0.0, float(settings.SCORE_WEIGHT_REGIME))
    total = w_tech + w_news + w_regime
    if total <= 0:
        return 0.40, 0.35, 0.25
    return w_tech / total, w_news / total, w_regime / total


@dataclass
class ManeuverCandidate:
    """Intermediate candidate before final ranking."""
    ticker: str
    prediction: ModelPrediction
    risk: TradeRiskResult
    news_sentiment: float = 0.0
    macro_score: float = 0.0
    event_score: float = 0.0  # per-ticker event/earnings effect (-1..1)
    news_article_count: int = 0
    hierarchy_hint: Any = None
    regime: str = "unknown"
    strategy_type: str = "momentum"
    time_horizon: str = "1–5 days"
    catalyst: str = ""
    rationale: str = ""
    atr: float = 0.0
    forecast_overlay_meta: dict[str, Any] = field(default_factory=dict)
    desk_overlay_meta: dict[str, Any] = field(default_factory=dict)
    ensemble_shadow_meta: dict[str, Any] = field(default_factory=dict)
    bocpd_meta: dict[str, Any] = field(default_factory=dict)
    microstructure_meta: dict[str, Any] = field(default_factory=dict)

    @property
    def technical_component(self) -> float:
        """0..1 technical signal: ML confidence + risk/reward + signal strength."""
        rr_score = min(self.risk.risk_reward_ratio / 3.0, 1.0)
        try:
            strength = float(getattr(self.prediction, "signal_strength", 0.0) or 0.0)
        except (TypeError, ValueError):
            strength = 0.0
        strength_bonus = 1.0 if strength > 0.3 else 0.0
        return (
            0.6 * self.prediction.confidence
            + 0.3 * rr_score
            + 0.1 * strength_bonus
        )

    @property
    def news_events_component(self) -> float | None:
        """0..1 news + events. None when there are no articles and no events."""
        if self.news_article_count <= 0 and abs(self.event_score) < 1e-9:
            return None
        blended = (self.news_sentiment + self.event_score) / 2.0
        return max(0.0, min(1.0, (blended + 1) / 2))  # normalize -1..1 -> 0..1

    @property
    def regime_component(self) -> float:
        """0..1 macro/regime signal: macro score plus regime favorability."""
        macro_norm = (self.macro_score + 1) / 2  # -1..1 -> 0..1
        favor = _REGIME_FAVORABILITY.get(self.regime, 0.5)
        return max(0.0, min(1.0, 0.7 * macro_norm + 0.3 * favor))

    @property
    def composite_score(self) -> float:
        """Weighted blend: technical + news/events + regime. Missing news is dropped, not 0.5."""
        from app.services.quant_desk.microstructure_features import blend_composite

        w_tech, w_news, w_regime = score_weights()
        news_c = self.news_events_component
        if news_c is None:
            total = w_tech + w_regime
            if total <= 0:
                base = self.technical_component
            else:
                base = (w_tech * self.technical_component + w_regime * self.regime_component) / total
        else:
            base = (
                w_tech * self.technical_component
                + w_news * news_c
                + w_regime * self.regime_component
            )
        rel = (self.microstructure_meta or {}).get("vwap_deviation_rel")
        return blend_composite(float(base), rel if rel is not None else None)


@dataclass
class ManeuverOutput:
    """Final structured maneuver ready for DB storage."""
    rank: int
    ticker: str
    strategy_type: str
    direction: str
    entry_zone_low: Optional[float]
    entry_zone_high: Optional[float]
    exit_zone_low: Optional[float]
    exit_zone_high: Optional[float]
    stop_loss: Optional[float]
    take_profit: Optional[float]
    invalidation_level: Optional[float]
    risk_percent: float
    position_size_usd: float
    expected_return_low: Optional[float]
    expected_return_high: Optional[float]
    expected_pnl_low: Optional[float]
    expected_pnl_high: Optional[float]
    confidence: float
    time_horizon: str
    catalyst: str
    rationale: str
    execution_plan: str
    source_signals: list[str] = field(default_factory=list)
    is_no_trade: bool = False
    below_confidence_threshold: bool = False
    signal_meta: dict[str, Any] = field(default_factory=dict)


def _risk_reason_ru(reason: str | None) -> str:
    """Short Russian category for a risk-engine refusal (shown in reports)."""
    r = (reason or "").lower()
    if "confidence" in r:
        return "уверенность ниже порога"
    if "daily loss" in r:
        return "достигнут дневной лимит убытка"
    if "drawdown" in r:
        return "достигнут лимит просадки"
    if "exposure" in r or "бюджет" in r or "cash buffer" in r:
        return "исчерпан бюджет на сделки"
    if "stop" in r or "atr" in r or "risk per share" in r:
        return "не удалось рассчитать стоп"
    return "ограничения риска"


class ManeuverGenerator:
    """
    Full maneuver generation pipeline.

    Steps:
    1. For each ticker: get prediction + risk computation
    2. Score and rank candidates
    3. Fill exactly MANEUVER_COUNT slots (NO_TRADE for remainder)
    """

    def __init__(
        self,
        risk_engine: RiskEngine | None = None,
        portfolio_size: float | None = None,
        confidence_threshold: float | None = None,
    ) -> None:
        self.portfolio_size = resolve_portfolio_size_usd(
            portfolio_size if portfolio_size is not None else settings.DEFAULT_PORTFOLIO_SIZE
        )
        self.confidence_threshold = (
            confidence_threshold
            if confidence_threshold is not None
            else settings.NO_TRADE_CONFIDENCE_THRESHOLD
        )
        if risk_engine is not None:
            self.risk_engine = risk_engine
        else:
            params = RiskParameters(
                portfolio_size=self.portfolio_size,
                confidence_threshold=self.confidence_threshold,
            )
            self.risk_engine = RiskEngine(params)
        self.classifier = get_classifier()
        self.last_confidence_filter: ConfidenceFilterResult | None = None
        self._reserved_tickers: set[str] = set()
        self._hierarchy_hints: dict[str, Any] = {}
        self._book_quotes: dict[str, dict[str, Any]] = {}
        self._bot_risk_snapshot: Any = None
        self._market_regime: dict[str, Any] = {}
        self._ensemble_shadow_n = 0

    def build_candidates(
        self,
        market_data: dict[str, pd.DataFrame],
        news_sentiment: dict[str, float] | None = None,
        macro_score: float = 0.0,
        events_by_ticker: dict[str, float] | None = None,
        hierarchy_hints: dict[str, Any] | None = None,
        news_article_counts: dict[str, int] | None = None,
        portfolio_state: PortfolioState | None = None,
    ) -> list[ManeuverCandidate]:
        """Analyze watchlist tickers into ranked maneuver candidates."""
        news_sentiment = news_sentiment or {}
        events_by_ticker = events_by_ticker or {}
        hints = hierarchy_hints or {}
        counts = news_article_counts or {}
        candidates: list[ManeuverCandidate] = []
        for ticker, df in market_data.items():
            if df.empty or len(df) < 30:
                logger.warning("Skipping ticker — insufficient data", ticker=ticker, rows=len(df))
                continue
            try:
                candidate = self._analyze_ticker(
                    ticker,
                    df,
                    news_sentiment.get(ticker, news_sentiment.get(ticker.upper(), 0.0)),
                    macro_score,
                    events_by_ticker.get(ticker, events_by_ticker.get(ticker.upper(), 0.0)),
                    hierarchy_hint=hints.get(ticker.upper()) or hints.get(ticker),
                    news_n=int(counts.get(ticker.upper(), counts.get(ticker, 0)) or 0),
                    portfolio_state=portfolio_state,
                )
                if candidate is not None:
                    candidates.append(candidate)
            except Exception as exc:
                logger.error("Error analyzing ticker", ticker=ticker, error=str(exc))
        candidates.sort(key=lambda c: c.composite_score, reverse=True)
        return candidates

    def _apply_market_bocpd(
        self,
        candidates: list[ManeuverCandidate],
        market_data: dict[str, pd.DataFrame],
    ) -> None:
        from app.services.pipeline.market_regime import REGIME_ANCHORS
        from app.services.risk.maneuver_regime import detect_bocpd, scale_confidence_from_bocpd

        hmm = str((self._market_regime or {}).get("regime") or "")
        closes: list[float] = []
        for sym in REGIME_ANCHORS:
            df = market_data.get(sym)
            if df is None:  # never `or` on a DataFrame: its truth value raises
                df = market_data.get(sym.lower())
            if df is None or getattr(df, "empty", True) or "close" not in getattr(df, "columns", []):
                continue
            closes = [float(x) for x in df["close"].tolist() if x is not None]
            if len(closes) >= 22:
                break
        if len(closes) < 22:
            for df in market_data.values():
                if df is None or getattr(df, "empty", True) or "close" not in getattr(df, "columns", []):
                    continue
                closes = [float(x) for x in df["close"].tolist() if x is not None]
                if len(closes) >= 22:
                    break
        meta = detect_bocpd(closes, hmm_label=hmm or None)
        for c in candidates:
            before = float(c.prediction.confidence)
            c.prediction.confidence = scale_confidence_from_bocpd(before, meta)
            c.bocpd_meta = dict(meta)
            if meta:
                c.bocpd_meta["confidence_before"] = before
                c.bocpd_meta["confidence_after"] = float(c.prediction.confidence)

    def _attach_ensemble_shadow(
        self,
        candidates: list[ManeuverCandidate],
        market_data: dict[str, pd.DataFrame],
    ) -> None:
        """Log ensemble vs classifier. Live side stays classifier unless flag is ensemble."""
        from app.services.risk.ensemble_shadow import maybe_override_from_ensemble, run_shadow

        max_shadow = int(getattr(settings, "MANEUVER_ENSEMBLE_SHADOW_MAX", 8) or 0)
        use_ensemble = str(getattr(settings, "MANEUVER_SIGNAL_SOURCE", "classifier")).lower() == "ensemble"
        n = 0
        for c in candidates:
            if n >= max_shadow:
                break
            df = market_data.get(c.ticker)
            if df is None or getattr(df, "empty", True) or "close" not in df.columns:
                continue
            closes = [float(x) for x in df["close"].tolist() if x is not None]
            row = run_shadow(
                c.ticker,
                closes,
                clf_direction=str(c.prediction.direction),
                clf_confidence=float(c.prediction.confidence),
                features=c.microstructure_meta or None,
            ) or {}
            if use_ensemble and row and "error" not in row:
                try:
                    from app.services.forecast.ensemble import get_ensemble_forecast_engine

                    fc = get_ensemble_forecast_engine().compute(closes, symbol=c.ticker)
                    new_dir, new_conf = maybe_override_from_ensemble(
                        direction=str(c.prediction.direction),
                        confidence=float(c.prediction.confidence),
                        forecast=fc,
                    )
                    c.prediction.direction = new_dir
                    c.prediction.confidence = new_conf
                    row["used_for_maneuver"] = True
                except Exception as exc:
                    logger.warning(
                        "ensemble override failed; keep classifier direction",
                        ticker=c.ticker,
                        error=str(exc)[:200],
                    )
            c.ensemble_shadow_meta = row
            n += 1

    def generate(
        self,
        market_data: dict[str, pd.DataFrame],   # ticker -> OHLCV DataFrame
        news_sentiment: dict[str, float] | None = None,  # ticker -> -1..1
        macro_score: float = 0.0,
        portfolio_state: PortfolioState | None = None,
        events_by_ticker: dict[str, float] | None = None,  # ticker -> event effect -1..1
        interval_forecasts: dict[str, "IntervalForecastLike"] | None = None,
        debate_result: dict[str, Any] | None = None,
        reserved_tickers: set[str] | list[str] | None = None,
        hierarchy_hints: dict[str, Any] | None = None,
        news_article_counts: dict[str, int] | None = None,
        user_id: str = "paper",
        book_quotes: dict[str, dict[str, Any]] | None = None,
        bot_risk_snapshot: Any = None,
        market_regime: dict[str, Any] | None = None,
    ) -> list[ManeuverOutput]:
        """
        Main entry point. Returns exactly MANEUVER_COUNT ManeuverOutput objects.

        Args:
            market_data: dict of ticker -> DataFrame(open,high,low,close,volume)
            news_sentiment: optional per-ticker sentiment score
            macro_score: aggregate macro environment score (-1 to 1)
            portfolio_state: current portfolio exposure
            events_by_ticker: optional per-ticker event/earnings effect (-1..1),
                e.g. derived from Investing.com (RapidAPI) earnings/economic
                events. Crypto has no dedicated sentiment API (ascn.ai exposes
                none), so crypto tickers rely on news + technical signals only.

        Returns:
            Exactly 10 ranked ManeuverOutput objects
        """
        news_sentiment = news_sentiment or {}
        events_by_ticker = events_by_ticker or {}
        intervals = interval_forecasts or {}
        self._hierarchy_hints = hierarchy_hints or {}
        self._macro_tilt = float(macro_score or 0.0)
        self._reserved_tickers = {str(t).strip().upper() for t in (reserved_tickers or []) if t}
        self._book_quotes = {
            str(k).strip().upper(): dict(v)
            for k, v in (book_quotes or {}).items()
            if v
        }
        self._bot_risk_snapshot = bot_risk_snapshot
        self._market_regime = dict(market_regime or {})
        self._rejects: dict[str, int] = {}
        self._ensemble_shadow_n = 0
        incoming = portfolio_state or PortfolioState()
        # New pack sizes against itself. Existing book is reserved tickers + overlay,
        # not a hard wipe of the analysis menu.
        selection_state = PortfolioState()

        market_data_cache: dict[str, pd.DataFrame] = dict(market_data)
        candidates = self.build_candidates(
            market_data,
            news_sentiment=news_sentiment,
            macro_score=macro_score,
            events_by_ticker=events_by_ticker,
            hierarchy_hints=self._hierarchy_hints,
            news_article_counts=news_article_counts,
            portfolio_state=incoming,
        )
        self._apply_market_bocpd(candidates, market_data_cache)
        self._attach_ensemble_shadow(candidates, market_data_cache)
        if debate_result:
            from app.services.risk.maneuver_debate import apply_debate_adjustments

            candidates = apply_debate_adjustments(candidates, debate_result)

        # Greedy diversification (spec A.2b)
        from app.services.risk.maneuver_diversification import select_diversified_candidates

        diversified = select_diversified_candidates(candidates, target=MANEUVER_COUNT)
        ranked_for_selection = diversified + [
            c for c in candidates if c.ticker not in {d.ticker for d in diversified}
        ]

        # Strict operator threshold — primary pass: confidence ≥ T across full watchlist.
        maneuvers = self._select_tradeable_maneuvers(
            ranked_for_selection,
            selection_state,
            confidence_threshold=self.confidence_threshold,
            interval_forecasts=intervals,
            enforce_batch_exposure=True,
            market_data=market_data_cache,
            portfolio_state_incoming=incoming,
        )

        if not maneuvers:
            max_conf = max_directional_confidence(candidates)
            if max_conf is not None and passes_confidence_threshold(
                max_conf, self.confidence_threshold
            ):
                by_confidence = sorted(
                    [
                        c
                        for c in candidates
                        if getattr(c.prediction, "direction", "neutral") != "neutral"
                    ],
                    key=lambda c: c.prediction.confidence,
                    reverse=True,
                )
                maneuvers = self._select_tradeable_maneuvers(
                    by_confidence,
                    selection_state,
                    confidence_threshold=self.confidence_threshold,
                    interval_forecasts=intervals,
                    enforce_batch_exposure=True,
                    market_data=market_data_cache,
                    portfolio_state_incoming=incoming,
                )

        used_tickers = {m.ticker for m in maneuvers if not m.is_no_trade}
        max_conf = max_directional_confidence(candidates)
        allow_backfill = (
            len(maneuvers) < MANEUVER_COUNT and max_conf is not None
        )
        if allow_backfill:
            below_pool = [
                c
                for c in candidates
                if c.ticker not in used_tickers
                and c.prediction.direction != "neutral"
                and not passes_confidence_threshold(
                    c.prediction.confidence, self.confidence_threshold
                )
                and c.prediction.confidence >= BACKFILL_CONFIDENCE_FLOOR - 1e-9
                and not getattr(self._hierarchy_hints.get(c.ticker.upper()), "is_avoid", False)
            ]
            backfill = self._select_tradeable_maneuvers(
                below_pool,
                selection_state,
                confidence_threshold=BACKFILL_CONFIDENCE_FLOOR,
                max_to_add=MANEUVER_COUNT - len(maneuvers),
                start_rank=len(maneuvers) + 1,
                interval_forecasts=intervals,
                enforce_batch_exposure=True,
                below_confidence_threshold=True,
            )
            maneuvers.extend(backfill)

        maneuvers = self._top_up_to_maneuver_count(
            candidates,
            maneuvers,
            selection_state,
            interval_forecasts=intervals,
        )

        tradeable_so_far = [m for m in maneuvers if not m.is_no_trade]
        if not tradeable_so_far and candidates:
            maneuvers = self._ensure_best_available_fallback(
                candidates,
                maneuvers,
                selection_state,
                interval_forecasts=intervals,
            )

        while len(maneuvers) < MANEUVER_COUNT:
            rank = len(maneuvers) + 1
            non_tradeable = [c for c in candidates if not c.risk.is_tradeable]
            if non_tradeable and rank <= len(non_tradeable) + len(maneuvers):
                idx = rank - len(maneuvers) - 1
                if idx < len(non_tradeable):
                    reason_candidate = non_tradeable[idx]
                    maneuvers.append(self._no_trade_output(
                        rank=rank,
                        ticker=reason_candidate.ticker,
                        reason=reason_candidate.risk.reason,
                        confidence=reason_candidate.prediction.confidence,
                    ))
                    continue
            maneuvers.append(self._no_trade_output(rank=rank, ticker="—", reason=self._rejects_summary_ru()))

        maneuvers = self._enforce_portfolio_limits(maneuvers[:MANEUVER_COUNT])
        from app.services.risk.portfolio_sizing import allocate_deploy_budget

        maneuvers = allocate_deploy_budget(maneuvers, self.portfolio_size, user_id=user_id)
        maneuvers = self._reapply_desk_size_mult(maneuvers)

        above_threshold_count = sum(
            1
            for m in maneuvers
            if not m.is_no_trade
            and not m.below_confidence_threshold
            and passes_confidence_threshold(m.confidence, self.confidence_threshold)
        )
        backfill_count = sum(
            1 for m in maneuvers if not m.is_no_trade and m.below_confidence_threshold
        )
        tradeable_count = sum(1 for m in maneuvers if not m.is_no_trade)
        self.last_confidence_filter = build_confidence_filter_result(
            self.confidence_threshold,
            max_available_confidence=max_directional_confidence(candidates),
            tradeable_count=tradeable_count,
            above_threshold_count=above_threshold_count,
            backfill_count=backfill_count,
        )

        if self._rejects:
            # Warning level so it reaches the worker log (info lines are filtered there).
            logger.warning("Maneuver rejections", tradeable=tradeable_count, reasons=dict(self._rejects))
        logger.info(
            "Maneuvers generated",
            total=len(maneuvers),
            tradeable=tradeable_count,
            portfolio_size=self.portfolio_size,
        )
        return maneuvers

    def _reject(self, reason: str) -> None:
        rejects = getattr(self, "_rejects", None)
        if rejects is None:
            rejects = self._rejects = {}
        rejects[reason] = rejects.get(reason, 0) + 1

    def _rejects_summary_ru(self) -> str:
        rejects = getattr(self, "_rejects", None) or {}
        if not rejects:
            return "Подходящих сделок не найдено"
        top = sorted(rejects.items(), key=lambda kv: -kv[1])[:3]
        return "Сделки не предложены. Причины: " + "; ".join(f"{r} — {n}" for r, n in top)

    def _technical_direction_bias(self, features: dict[str, float]) -> float:
        """Signed bias in roughly -1..1 from technical features (0 = flat)."""
        score = 0.0
        rsi = float(features.get("rsi_14", 50))
        if rsi < 42:
            score += 0.22
        elif rsi < 48:
            score += 0.10
        elif rsi > 58:
            score -= 0.22
        elif rsi > 52:
            score -= 0.10

        if features.get("macd_bullish", 0):
            score += 0.14
        else:
            score -= 0.10

        roc = float(features.get("roc_5", 0))
        if roc > 1.0:
            score += 0.12
        elif roc < -1.0:
            score -= 0.12

        if features.get("sma_cross_5_20", 0) and float(features.get("price_vs_sma20", 0)) > 0:
            score += 0.10
        elif not features.get("sma_cross_5_20", 1) and float(features.get("price_vs_sma20", 0)) < 0:
            score -= 0.10

        bb = float(features.get("bb_position", 0.5))
        if bb < 0.25:
            score += 0.08
        elif bb > 0.75:
            score -= 0.08

        return max(-1.0, min(1.0, score))

    def _resolve_weak_direction(self, candidate: ManeuverCandidate) -> None:
        """Turn clustered neutral ML outputs into weak long/short for proposal slots."""
        pred = candidate.prediction
        if pred.direction != "neutral":
            return
        raw = float(pred.raw_score if pred.raw_score else pred.confidence)
        if raw > 0.501:
            pred.direction = "long"
            pred.confidence = max(pred.confidence, raw)
        elif raw < 0.499:
            pred.direction = "short"
            pred.confidence = max(pred.confidence, 1.0 - raw)
        else:
            bias = self._technical_direction_bias(pred.features_used or {})
            if bias > 0.02:
                pred.direction = "long"
                pred.confidence = max(
                    pred.confidence,
                    min(0.45 + bias * 0.35, 0.72),
                )
            elif bias < -0.02:
                pred.direction = "short"
                pred.confidence = max(
                    pred.confidence,
                    min(0.45 + (-bias) * 0.35, 0.72),
                )
            else:
                pred.direction = "long"
                pred.confidence = max(pred.confidence, MIN_SLOT_CONFIDENCE)

    def _ensure_best_available_fallback(
        self,
        candidates: list[ManeuverCandidate],
        maneuvers: list[ManeuverOutput],
        state: PortfolioState,
        *,
        interval_forecasts: dict[str, "IntervalForecastLike"] | None = None,
    ) -> list[ManeuverOutput]:
        """When nothing passed the user threshold, return the single best directional idea."""
        pool = [
            c
            for c in candidates
            if getattr(c.prediction, "direction", "neutral") != "neutral"
        ]
        if not pool:
            return maneuvers
        pool.sort(key=lambda c: c.composite_score, reverse=True)
        best = pool[0]
        floor = max(MIN_SLOT_CONFIDENCE, float(best.prediction.confidence))
        added = self._select_tradeable_maneuvers(
            [best],
            state,
            confidence_threshold=floor,
            max_to_add=1,
            start_rank=1,
            interval_forecasts=interval_forecasts,
            enforce_batch_exposure=False,
            below_confidence_threshold=not passes_confidence_threshold(
                best.prediction.confidence, self.confidence_threshold
            ),
        )
        if not added:
            return maneuvers
        out = added[0]
        if out.below_confidence_threshold:
            pct = int(round(self.confidence_threshold * 100))
            conf_pct = int(round(out.confidence * 100))
            out.catalyst = (
                f"ниже порога {pct}% (уверенность {conf_pct}%) — лучший доступный сигнал"
                + (f"; {out.catalyst}" if out.catalyst and out.catalyst != "—" else "")
            )
        return [out]

    def _top_up_to_maneuver_count(
        self,
        candidates: list[ManeuverCandidate],
        maneuvers: list[ManeuverOutput],
        state: PortfolioState,
        *,
        interval_forecasts: dict[str, "IntervalForecastLike"] | None = None,
    ) -> list[ManeuverOutput]:
        """Fill toward MANEUVER_COUNT with decaying confidence and per-slot exposure budget."""
        tradeable = [m for m in maneuvers if not m.is_no_trade]
        if len(tradeable) >= MANEUVER_COUNT:
            return maneuvers

        used = {m.ticker for m in tradeable}
        params = self.risk_engine.params
        slot_budget = (
            params.portfolio_size * params.max_exposure_pct / 100 / max(MANEUVER_COUNT, 1)
        )
        batch_state = PortfolioState(
            daily_pnl_usd=state.daily_pnl_usd,
            current_drawdown_pct=state.current_drawdown_pct,
            total_exposure_usd=sum(m.position_size_usd for m in tradeable),
            open_positions=len(tradeable),
        )

        threshold = self.confidence_threshold
        t = threshold
        while len(tradeable) < MANEUVER_COUNT and t >= MIN_SLOT_CONFIDENCE - 1e-9:
            pool: list[ManeuverCandidate] = []
            for c in candidates:
                if c.ticker in used:
                    continue
                if c.prediction.direction == "neutral":
                    self._resolve_weak_direction(c)
                if c.prediction.direction == "neutral":
                    continue
                pool.append(c)
            pool.sort(key=lambda c: c.composite_score, reverse=True)

            added = self._select_tradeable_maneuvers(
                pool,
                batch_state,
                confidence_threshold=t,
                max_to_add=MANEUVER_COUNT - len(tradeable),
                start_rank=len(maneuvers) + 1,
                interval_forecasts=interval_forecasts,
                enforce_batch_exposure=True,
                below_confidence_threshold=t < threshold - 1e-9,
                max_position_usd=slot_budget,
            )
            if not added:
                t = round(t - 0.02, 4)
                continue
            for m in added:
                if m.is_no_trade:
                    continue
                if t < threshold - 1e-9:
                    m.below_confidence_threshold = True
                    pct = int(round(threshold * 100))
                    conf_pct = int(round(m.confidence * 100))
                    m.catalyst = (
                        f"ниже порога {pct}% (уверенность {conf_pct}%)"
                        + (f"; {m.catalyst}" if m.catalyst and m.catalyst != "—" else "")
                    )
                maneuvers.append(m)
                tradeable.append(m)
                used.add(m.ticker)
            t = round(t - 0.02, 4)

        return maneuvers

    def _enforce_portfolio_limits(self, maneuvers: list[ManeuverOutput]) -> list[ManeuverOutput]:
        """Clamp proposed sizes to the operator's portfolio — never exceed caps."""
        params = self.risk_engine.params
        per_position_cap = params.per_position_cap_usd()
        max_exposure = params.portfolio_size * params.max_exposure_pct / 100

        tradeable = [m for m in maneuvers if not m.is_no_trade]
        if not tradeable:
            return maneuvers

        for m in tradeable:
            if m.position_size_usd > per_position_cap:
                factor = per_position_cap / m.position_size_usd
                self._scale_maneuver_output(m, factor)
                m.rationale = (
                    f"{m.rationale} "
                    f"(размер уменьшен до ${m.position_size_usd:,.0f} — "
                    f"лимит {params.max_position_pct:.0f}% капитала ${params.portfolio_size:,.0f})."
                )

        total = sum(m.position_size_usd for m in tradeable)
        if total > max_exposure and total > 0:
            scale = max_exposure / total
            for m in tradeable:
                self._scale_maneuver_output(m, scale)
                m.rationale = (
                    f"{m.rationale} "
                    f"(пропорционально уменьшен — суммарная экспозиция "
                    f"≤ {params.max_exposure_pct:.0f}% портфеля)."
                )

        # Min-ticket drops happen after allocate_deploy_budget, which can
        # raise ATR dust up to a legal share of the deploy cap.
        return maneuvers

    def _reapply_desk_size_mult(self, maneuvers: list[ManeuverOutput]) -> list[ManeuverOutput]:
        """Allocate overwrites notionals; keep book_gate shrink (never increase)."""
        from app.services.risk.portfolio_sizing import apply_maneuver_notional

        for m in maneuvers:
            if getattr(m, "is_no_trade", False):
                continue
            meta = (getattr(m, "signal_meta", None) or {}).get("desk_overlay") or {}
            try:
                mult = float(meta.get("size_mult"))
            except (TypeError, ValueError):
                continue
            if mult >= 1.0 - 1e-9 or mult <= 0:
                continue
            usd = float(getattr(m, "position_size_usd", 0.0) or 0.0)
            if usd <= 0:
                continue
            apply_maneuver_notional(m, usd * mult, deploy_cap=self.portfolio_size)
            meta["applied_after_allocate"] = True
            meta["post_allocate_usd"] = float(m.position_size_usd)
        from app.services.risk.maneuver_regime import regime_size_mult

        r_mult = regime_size_mult(self._market_regime)
        if r_mult is not None and 0 < r_mult < 1.0:
            for m in maneuvers:
                if getattr(m, "is_no_trade", False):
                    continue
                usd = float(getattr(m, "position_size_usd", 0.0) or 0.0)
                if usd <= 0:
                    continue
                apply_maneuver_notional(m, usd * r_mult, deploy_cap=self.portfolio_size)
                meta = getattr(m, "signal_meta", None)
                if isinstance(meta, dict):
                    meta["regime_size_mult"] = r_mult
        return maneuvers

    @staticmethod
    def _scale_maneuver_output(m: ManeuverOutput, factor: float) -> None:
        """Scale notional and dependent PnL fields in place."""
        if factor >= 1.0 - 1e-9:
            return
        m.position_size_usd = round(m.position_size_usd * factor, 2)
        m.risk_percent = round(m.risk_percent * factor, 4)
        if m.expected_pnl_low is not None:
            m.expected_pnl_low = round(m.expected_pnl_low * factor, 2)
        if m.expected_pnl_high is not None:
            m.expected_pnl_high = round(m.expected_pnl_high * factor, 2)
        if m.execution_plan and m.position_size_usd > 0:
            m.execution_plan = (
                f"{m.execution_plan.split('Размер:')[0].rstrip()} "
                f"Размер: ${m.position_size_usd:,.0f}."
            )

    def _select_tradeable_maneuvers(
        self,
        candidates: list[ManeuverCandidate],
        state: PortfolioState,
        *,
        confidence_threshold: float,
        max_to_add: int | None = None,
        start_rank: int = 1,
        interval_forecasts: dict[str, "IntervalForecastLike"] | None = None,
        enforce_batch_exposure: bool = False,
        below_confidence_threshold: bool = False,
        max_position_usd: float | None = None,
        market_data: dict[str, pd.DataFrame] | None = None,
        portfolio_state_incoming: PortfolioState | None = None,
    ) -> list[ManeuverOutput]:
        """Pick up to MANEUVER_COUNT tradeable slots from ranked watchlist candidates."""
        from app.services.risk.portfolio_overlay import evaluate_portfolio_overlay

        limit = max_to_add if max_to_add is not None else MANEUVER_COUNT
        maneuvers: list[ManeuverOutput] = []
        seen_tickers: set[str] = set()
        batch_selected: list[ManeuverCandidate] = []

        for candidate in candidates:
            if len(maneuvers) >= limit:
                break
            if candidate.ticker in seen_tickers:
                continue
            if candidate.prediction.direction == "neutral":
                self._resolve_weak_direction(candidate)
            if candidate.prediction.direction == "neutral":
                self._reject("нет направленного сигнала")
                continue
            if candidate.ticker.upper() in self._reserved_tickers:
                self._reject("бумага уже занята ботом или открытым манёвром")
                continue
            hint = self._hierarchy_hints.get(candidate.ticker.upper())
            if getattr(hint, "is_avoid", False):
                self._reject("уточняющий анализ не рекомендует вход")
                continue
            from app.services.pipeline.market_regime import REGIME_ANCHORS

            if candidate.ticker.upper() in REGIME_ANCHORS and not below_confidence_threshold:
                others = [
                    c
                    for c in candidates
                    if c.ticker.upper() not in REGIME_ANCHORS
                    and c.ticker not in seen_tickers
                    and getattr(c.prediction, "direction", "neutral") != "neutral"
                ]
                if others:
                    continue

            risk = self.risk_engine.compute(
                ticker=candidate.ticker,
                direction=candidate.prediction.direction,
                entry_price=candidate.risk.entry_price,
                confidence=candidate.prediction.confidence,
                atr=candidate.atr or candidate.risk.entry_price * 0.02,
                portfolio_state=state,
                confidence_threshold=confidence_threshold,
                custom_risk_pct=candidate.risk.risk_percent or None,
            )

            if not risk.is_tradeable:
                self._reject(_risk_reason_ru(risk.reason))
                continue

            df_overlay = (market_data or {}).get(candidate.ticker)
            if df_overlay is not None and not df_overlay.empty and "close" in df_overlay.columns:
                from app.services.forecast.trade_overlay import apply_forecast_overlay

                closes = [float(x) for x in df_overlay["close"].tolist() if x is not None]
                overlay_fc = apply_forecast_overlay(
                    ticker=candidate.ticker,
                    direction=candidate.prediction.direction,
                    closes=closes,
                    mesh_confidence=candidate.prediction.confidence,
                )
                candidate.forecast_overlay_meta = overlay_fc.meta
                if not overlay_fc.allow:
                    self._reject("прогноз цены против направления сделки")
                    continue
                if overlay_fc.size_mult < 1.0 and overlay_fc.size_mult > 0:
                    risk.position_size_usd = round(risk.position_size_usd * overlay_fc.size_mult, 2)
                    risk.position_size_shares = round(
                        risk.position_size_shares * overlay_fc.size_mult, 4
                    )
                    risk.risk_amount_usd = round(risk.risk_amount_usd * overlay_fc.size_mult, 2)

            from app.services.quant_desk.book_quotes import quotes_for_desk
            from app.services.quant_desk.overlays import apply_to_risk, desk_overlay

            realized = None
            df_vol = (market_data or {}).get(candidate.ticker)
            if df_vol is not None and not getattr(df_vol, "empty", True) and "close" in df_vol.columns:
                try:
                    rets = df_vol["close"].pct_change().dropna()
                    if len(rets) >= 15:
                        realized = float(rets.tail(20).std() * (252**0.5))
                except Exception:
                    realized = None
            book_q = self._book_quotes.get(str(candidate.ticker).upper()) or {}
            desk_q = quotes_for_desk(book_q)
            micro = candidate.microstructure_meta or {}
            spread_z = micro.get("spread_zscore")
            try:
                spread_z_f = float(spread_z) if spread_z is not None else None
            except (TypeError, ValueError):
                spread_z_f = None
            overlay_desk = desk_overlay(
                equity_usd=float(self.portfolio_size or 0.0),
                price=float(candidate.risk.entry_price or 0.0),
                atr=float(candidate.atr or candidate.risk.entry_price * 0.02),
                current_usd=float(risk.position_size_usd or 0.0),
                direction=str(candidate.prediction.direction),
                realized_ann_vol=realized,
                bid=desk_q["bid"],
                ask=desk_q["ask"],
                bid_sz=desk_q["bid_sz"],
                ask_sz=desk_q["ask_sz"],
                atr_pct=(
                    float(candidate.atr) / float(candidate.risk.entry_price)
                    if candidate.atr and candidate.risk.entry_price
                    else None
                ),
                macro_tilt=float(getattr(self, "_macro_tilt", 0.0) or 0.0),
                spread_zscore=spread_z_f,
            )
            have_quotes = desk_q["bid"] is not None and desk_q["ask"] is not None
            candidate.desk_overlay_meta = {
                "bid": desk_q["bid"],
                "ask": desk_q["ask"],
                "bid_sz": desk_q["bid_sz"],
                "ask_sz": desk_q["ask_sz"],
                "have_quoted_spread": have_quotes,
                "source": book_q.get("source"),
                "size_mult": overlay_desk.size_mult,
                "allow": overlay_desk.allow,
                "reasons": list(overlay_desk.reasons),
                "spread_zscore": spread_z_f,
                "vwap_deviation": micro.get("vwap_deviation"),
                "vwap_deviation_rel": micro.get("vwap_deviation_rel"),
            }
            logger.info(
                "maneuver_book_gate",
                ticker=candidate.ticker,
                have_quoted_spread=have_quotes,
                bid=desk_q["bid"],
                ask=desk_q["ask"],
                size_mult=overlay_desk.size_mult,
                allow=overlay_desk.allow,
                spread_zscore=spread_z_f,
                vwap_deviation=micro.get("vwap_deviation"),
            )
            logger.info(
                "maneuver_microstructure",
                ticker=candidate.ticker,
                vwap_deviation=micro.get("vwap_deviation"),
                vwap_deviation_rel=micro.get("vwap_deviation_rel"),
                spread_zscore=spread_z_f,
                roll_reason=micro.get("roll_reason"),
                kyle=micro.get("kyle_lambda", {}).get("status"),
                alpha003=micro.get("alpha003", {}).get("status"),
                composite_score=round(float(candidate.composite_score), 6),
            )
            apply_to_risk(risk, overlay_desk)
            if not risk.is_tradeable:
                self._reject("спред или ликвидность не позволяют войти")
                continue

            from app.services.risk.maneuver_bot_guard import gate_maneuver

            allowed, guard_reason = gate_maneuver(
                candidate.ticker,
                snapshot=self._bot_risk_snapshot,
                selected=batch_selected,
            )
            if not allowed:
                self._reject("пересечение с рисками ботов")
                logger.info(
                    "maneuver_skipped_bot_risk",
                    ticker=candidate.ticker,
                    reason=guard_reason[:200],
                )
                continue

            from app.services.risk.maneuver_regime import regime_blocks_new_risk, regime_size_mult

            if regime_blocks_new_risk(self._market_regime):
                self._reject("рыночный режим не допускает новых позиций")
                logger.info(
                    "maneuver_skipped_regime_gate",
                    ticker=candidate.ticker,
                    regime=self._market_regime.get("regime_gate"),
                    size_mult=self._market_regime.get("size_mult"),
                )
                continue
            r_mult = regime_size_mult(self._market_regime)
            if r_mult is not None and 0 < r_mult < 1.0:
                risk.position_size_usd = round(risk.position_size_usd * r_mult, 2)
                risk.position_size_shares = round(risk.position_size_shares * r_mult, 4)
                risk.risk_amount_usd = round(risk.risk_amount_usd * r_mult, 2)

            if max_position_usd is not None and risk.position_size_usd > max_position_usd:
                factor = max_position_usd / risk.position_size_usd
                risk.position_size_usd = round(risk.position_size_usd * factor, 2)
                risk.position_size_shares = round(
                    risk.position_size_shares * factor, 4
                )
                risk.risk_amount_usd = round(risk.risk_amount_usd * factor, 2)

            candidate.risk = risk
            rank = start_rank + len(maneuvers)
            interval = (interval_forecasts or {}).get(candidate.ticker.upper())
            overlay = evaluate_portfolio_overlay(
                candidate,
                batch_selected,
                portfolio_state_incoming or state,
            )
            df = (market_data or {}).get(candidate.ticker)
            out = self._candidate_to_output(
                candidate,
                rank=rank,
                interval_forecast=interval,
                overlay=overlay,
                df=df,
            )
            if below_confidence_threshold:
                out.below_confidence_threshold = True
                pct = int(round(self.confidence_threshold * 100))
                conf_pct = int(round(out.confidence * 100))
                out.catalyst = (
                    f"ниже порога {pct}% (уверенность {conf_pct}%)"
                    + (f"; {out.catalyst}" if out.catalyst and out.catalyst != "—" else "")
                )
            maneuvers.append(out)
            seen_tickers.add(candidate.ticker)
            batch_selected.append(candidate)
            if enforce_batch_exposure:
                state.total_exposure_usd += risk.position_size_usd
                state.open_positions += 1

        return maneuvers

    def _analyze_ticker(
        self,
        ticker: str,
        df: pd.DataFrame,
        sentiment: float,
        macro: float,
        event_score: float = 0.0,
        hierarchy_hint: Any | None = None,
        news_n: int = 0,
        portfolio_state: PortfolioState | None = None,
    ) -> ManeuverCandidate | None:
        """Run prediction + risk computation for one ticker."""
        from app.services.ml.features import compute_features
        from app.services.risk.hierarchy_hints import apply_hint_to_confidence

        from app.services.quant_desk.microstructure_features import compute_maneuver_microstructure

        micro = compute_maneuver_microstructure(df)
        df_feat = compute_features(df)
        latest = df_feat.iloc[-1]
        entry_price = float(latest["close"])
        atr = float(latest.get("atr_14", entry_price * 0.02))
        regime = label_from_closes(df["close"].tolist(), ticker=ticker)
        if hierarchy_hint is not None and getattr(hierarchy_hint, "hmm_or_global_regime", None):
            # Keep SMA regime for technicals; surface HMM/global label in catalyst via hint.
            pass

        vols = [float(v) for v in df["volume"].tail(25).tolist()] if "volume" in df.columns else []
        vol_z = volume_zscore(vols)
        atr_pct = atr / entry_price if entry_price > 0 else 0.02

        prediction = self.classifier.predict_from_features(df_feat, ticker)
        from app.services.risk.hierarchy_hints import apply_hint_to_direction

        direction, adj_confidence = apply_hint_to_direction(
            direction=str(prediction.direction),
            confidence=float(prediction.confidence),
            hint=hierarchy_hint,
        )
        prediction.direction = direction

        news_w = 0.04 if news_n > 0 else 0.0
        adj_confidence = float(
            adj_confidence
            + sentiment * news_w
            + event_score * 0.02
            + macro * 0.03
        )
        adj_confidence = apply_hint_to_confidence(
            direction=str(prediction.direction),
            confidence=adj_confidence,
            hint=hierarchy_hint,
        )
        adj_confidence = min(max(adj_confidence, 0.0), 0.95)
        prediction.confidence = adj_confidence
        shadow_meta: dict[str, Any] = {}
        bocpd_meta: dict[str, Any] = {}

        self._resolve_weak_direction(
            ManeuverCandidate(
                ticker=ticker,
                prediction=prediction,
                risk=TradeRiskResult(
                    ticker=ticker,
                    direction=prediction.direction,
                    is_tradeable=True,
                    reason="pre-risk directional probe",
                    entry_price=entry_price,
                    risk_percent=settings.MAX_RISK_PER_TRADE_PCT,
                ),
            )
        )

        if prediction.direction == "neutral":
            return ManeuverCandidate(
                ticker=ticker,
                prediction=prediction,
                risk=TradeRiskResult(
                    ticker=ticker, direction="neutral", is_tradeable=False,
                    reason="Neutral signal — no directional edge", entry_price=entry_price,
                    risk_percent=settings.MAX_RISK_PER_TRADE_PCT,
                ),
                regime=regime,
                event_score=event_score,
                news_article_count=news_n,
                hierarchy_hint=hierarchy_hint,
                ensemble_shadow_meta=shadow_meta,
                bocpd_meta=bocpd_meta,
                microstructure_meta=micro,
            )

        risk = self.risk_engine.compute(
            ticker=ticker,
            direction=prediction.direction,
            entry_price=entry_price,
            confidence=adj_confidence,
            atr=atr,
            portfolio_state=portfolio_state or PortfolioState(),
            confidence_threshold=self.confidence_threshold,
            custom_risk_pct=conviction_risk_pct(
                base_max_risk_pct=self.risk_engine.params.max_risk_pct,
                confidence=adj_confidence,
                atr_pct=atr_pct,
                volume_z=vol_z,
            ),
        )

        strategy = self._classify_strategy(df_feat, regime, prediction.direction)
        horizon = self._pick_horizon(strategy)
        catalyst = self._build_catalyst(
            ticker,
            sentiment,
            macro,
            regime,
            hmm_label=getattr(hierarchy_hint, "hmm_or_global_regime", None),
        )
        rationale = self._build_rationale(prediction, risk, regime, sentiment, strategy)

        return ManeuverCandidate(
            ticker=ticker,
            prediction=prediction,
            risk=risk,
            news_sentiment=sentiment,
            macro_score=macro,
            event_score=event_score,
            regime=regime,
            strategy_type=strategy,
            time_horizon=horizon,
            catalyst=catalyst,
            rationale=rationale,
            atr=atr,
            news_article_count=news_n,
            hierarchy_hint=hierarchy_hint,
            ensemble_shadow_meta=shadow_meta,
            bocpd_meta=bocpd_meta,
            microstructure_meta=micro,
        )

    def _classify_strategy(
        self, df: pd.DataFrame, regime: str, direction: str
    ) -> str:
        """Classify strategy type from regime and features."""
        latest = df.iloc[-1]
        vol = float(latest.get("volatility_20d", 0.2))
        rsi = float(latest.get("rsi_14", 50))

        if regime == "sideways" and 35 < rsi < 65:
            return "mean_reversion"
        elif vol > 0.35:
            return "event_driven"
        elif float(latest.get("sma_cross_5_20", 0)) == 1.0 and direction == "long":
            return "momentum"
        elif float(latest.get("bb_position", 0.5)) > 0.9:
            return "mean_reversion"
        else:
            return "trend_following"

    def _horizon_profile(self, strategy: str) -> dict[str, str]:
        """Four holding windows, same stop and size. Clock on the book uses swing."""
        profiles = {
            "momentum": {
                "скальп": "30–90 минут",
                "день": "внутри дня",
                "свинг": "3–10 дней",
                "долго": "2–6 недель",
            },
            "mean_reversion": {
                "скальп": "минуты",
                "день": "внутри дня",
                "свинг": "1–5 дней",
                "долго": "2–4 недели",
            },
            "breakout": {
                "скальп": "30–90 минут",
                "день": "внутри дня",
                "свинг": "5–15 дней",
                "долго": "4–12 недель",
            },
            "trend_following": {
                "скальп": "час",
                "день": "1–2 дня",
                "свинг": "2–6 недель",
                "долго": "1–6 месяцев",
            },
            "event_driven": {
                "скальп": "минуты вокруг события",
                "день": "сессия",
                "свинг": "1–3 дня",
                "долго": "1–4 недели",
            },
            "grid": {
                "скальп": "час",
                "день": "1–3 дня",
                "свинг": "2–4 недели",
                "долго": "1–3 месяца",
            },
            "macro": {
                "скальп": "не для скальпа",
                "день": "1–2 дня",
                "свинг": "4–12 недель",
                "долго": "квартал и дольше",
            },
        }
        return profiles.get(
            strategy,
            {
                "скальп": "час",
                "день": "внутри дня",
                "свинг": "1–2 недели",
                "долго": "1–3 месяца",
            },
        )

    def _pick_horizon(self, strategy: str) -> str:
        return self._horizon_profile(strategy)["свинг"]

    def _build_catalyst(
        self,
        ticker: str,
        sentiment: float,
        macro: float,
        regime: str,
        hmm_label: str | None = None,
    ) -> str:
        parts = []
        if abs(sentiment) > 0.3:
            parts.append("новости скорее за идею" if sentiment > 0 else "новости скорее против идеи")
        if abs(macro) > 0.2:
            parts.append("общий рынок тоже давит в ту же сторону" if macro > 0 else "общий рынок сейчас скорее мешает")
        names = {
            "trend_up": "рынок растёт",
            "trend_down": "рынок снижается",
            "range": "рынок в коридоре",
            "volatility": "повышенная волатильность",
            "crisis": "рынок в стрессе",
            "insufficient": "режима недостаточно",
            "bull": "рынок растёт",
            "bear": "рынок снижается",
            "sideways": "рынок в коридоре",
            "volatile": "повышенная волатильность",
            "trending_up": "рынок растёт",
            "trending_down": "рынок снижается",
            "range_bound": "рынок в коридоре",
            "high_volatility": "повышенная волатильность",
        }
        parts.append(names.get(regime, "смотрим на фон рынка"))
        if hmm_label:
            parts.append(f"иерархия: {hmm_label}")
        return "; ".join(parts)

    def _build_rationale(
        self,
        prediction: ModelPrediction,
        risk: TradeRiskResult,
        regime: str,
        sentiment: float,
        strategy: str = "",
    ) -> str:
        from app.services.risk.human_copy import build_position_rationale

        return build_position_rationale(
            strategy=str(strategy or ""),
            direction=str(prediction.direction),
            confidence=float(prediction.confidence or 0.0),
            regime=regime,
            features=prediction.features_used or {},
            is_fallback=bool(prediction.is_fallback),
            risk_reward=float(risk.risk_reward_ratio) if risk.risk_reward_ratio else None,
            sentiment=float(sentiment),
        )

    def _candidate_to_output(
        self,
        c: ManeuverCandidate,
        rank: int,
        interval_forecast: "IntervalForecastLike | None" = None,
        overlay: "PortfolioOverlayResult | None" = None,
        df: pd.DataFrame | None = None,
    ) -> ManeuverOutput:
        from app.services.risk.portfolio_overlay import PortfolioOverlayResult
        from app.services.risk.maneuver_presentation import build_maneuver_presentation
        from app.services.risk.profit_projection import compute_profit_projection

        r = c.risk
        sign = 0
        if c.prediction.direction == "long":
            sign = 1
        elif c.prediction.direction == "short":
            sign = -1
        daily_vol = (c.atr / r.entry_price) if r.entry_price > 0 and c.atr else None
        fees = r.position_size_usd * (settings.COMMISSION_RATE_PCT / 100.0) * 2.0
        projection = compute_profit_projection(
            direction=c.prediction.direction,
            entry_price=r.entry_price,
            take_profit=r.take_profit,
            stop_loss=r.stop_loss,
            position_size_usd=r.position_size_usd,
            time_horizon=c.time_horizon,
            daily_vol=daily_vol,
            interval_forecast=interval_forecast,
            momentum_sign=sign if c.prediction.confidence >= 0.55 else 0,
            round_trip_fees_usd=fees,
        )
        exp_ret_lo = r.expected_return_low_pct
        exp_ret_hi = r.expected_return_high_pct
        exp_pnl_lo = r.expected_pnl_low
        exp_pnl_hi = r.expected_pnl_high
        tp_prob = 0.0
        disclosure = ""
        if projection:
            exp_ret_lo = projection.expected_return_low_pct
            exp_ret_hi = projection.expected_return_high_pct
            exp_pnl_lo = projection.expected_pnl_low
            exp_pnl_hi = projection.expected_pnl_high
            tp_prob = projection.tp_hit_probability
            disclosure = projection.disclosure_ru

        spread = r.atr_half if hasattr(r, "atr_half") else r.entry_price * 0.003
        rationale = c.rationale
        if projection:
            hit = int(round(tp_prob * 100))
            rationale = (
                f"{c.rationale} {disclosure} "
                f"Шанс дойти до цели до конца срока — около {hit}%."
            )

        overlay_result = overlay
        if overlay_result is None:
            overlay_result = PortfolioOverlayResult()
        try:
            presentation = build_maneuver_presentation(
                c,
                df,
                portfolio_size=self.portfolio_size,
                overlay_warnings=overlay_result.warnings,
                portfolio_overlay={
                    "sector": overlay_result.sector,
                    "sector_count_after_add": overlay_result.sector_count_after_add,
                    "max_factor_overlap": overlay_result.max_factor_overlap,
                },
            )
        except Exception as exc:
            logger.warning(
                "Maneuver presentation skipped",
                ticker=c.ticker,
                error=str(exc)[:200],
            )
            from app.services.macro.sector_seed import sector_for_symbol
            from app.services.risk.maneuver_presentation import ManeuverPresentation

            mapped = sector_for_symbol(c.ticker)
            presentation = ManeuverPresentation(sector=mapped[0] if mapped else "unknown")
        signal_meta = presentation.to_dict()
        signal_meta["horizon_profiles"] = self._horizon_profile(c.strategy_type)
        if c.forecast_overlay_meta:
            signal_meta["forecast_overlay"] = c.forecast_overlay_meta
        if c.desk_overlay_meta:
            signal_meta["desk_overlay"] = c.desk_overlay_meta
        if c.ensemble_shadow_meta:
            signal_meta["ensemble_shadow"] = c.ensemble_shadow_meta
        if c.bocpd_meta:
            signal_meta["bocpd"] = c.bocpd_meta
        if c.microstructure_meta:
            signal_meta["microstructure"] = c.microstructure_meta
        if df is not None and not df.empty:
            close_col = "close" if "close" in df.columns else ("Close" if "Close" in df.columns else None)
            if close_col:
                try:
                    from app.services.trading_engines.runtime.overlays import maneuver_engine_overlays

                    closes = [float(x) for x in df[close_col].tolist() if x is not None]
                    if len(closes) >= 16:
                        signal_meta["trading_engines"] = maneuver_engine_overlays(closes, symbol=c.ticker)
                except Exception as exc:  # noqa: BLE001
                    logger.debug("Maneuver engine overlay skipped", ticker=c.ticker, error=str(exc)[:160])

        return ManeuverOutput(
            rank=rank,
            ticker=c.ticker,
            strategy_type=c.strategy_type,
            direction=c.prediction.direction,
            entry_zone_low=round(r.entry_price * 0.998, 4),
            entry_zone_high=round(r.entry_price * 1.002, 4),
            exit_zone_low=round(r.take_profit * 0.99, 4),
            exit_zone_high=round(r.take_profit * 1.01, 4),
            stop_loss=r.stop_loss,
            take_profit=r.take_profit,
            invalidation_level=r.invalidation_level,
            risk_percent=r.risk_percent,
            position_size_usd=r.position_size_usd,
            expected_return_low=exp_ret_lo,
            expected_return_high=exp_ret_hi,
            expected_pnl_low=exp_pnl_lo,
            expected_pnl_high=exp_pnl_hi,
            confidence=c.prediction.confidence,
            time_horizon=c.time_horizon,
            catalyst=c.catalyst,
            rationale=rationale,
            execution_plan=(
                f"Купить по {r.entry_price:.2f}."
                if str(c.prediction.direction).lower() == "long"
                else f"Продать по {r.entry_price:.2f}."
            )
            + (
                f" Защитный стоп {r.stop_loss:.2f}, цель {r.take_profit:.2f}."
                f" Срок идеи: {c.time_horizon}. Размер около ${r.position_size_usd:,.0f}."
            ),
            source_signals=[c.prediction.model_version],
            signal_meta=signal_meta,
        )

    def _no_trade_output(
        self,
        rank: int,
        ticker: str,
        reason: str = "Условия не выполнены",
        confidence: float = 0.0,
    ) -> ManeuverOutput:
        return ManeuverOutput(
            rank=rank,
            ticker=ticker,
            strategy_type="no_trade",
            direction="neutral",
            entry_zone_low=None,
            entry_zone_high=None,
            exit_zone_low=None,
            exit_zone_high=None,
            stop_loss=None,
            take_profit=None,
            invalidation_level=None,
            risk_percent=0.0,
            position_size_usd=0.0,
            expected_return_low=None,
            expected_return_high=None,
            expected_pnl_low=None,
            expected_pnl_high=None,
            confidence=confidence,
            time_horizon="—",
            catalyst="—",
            rationale=reason,
            execution_plan="Нет действий.",
            is_no_trade=True,
        )
