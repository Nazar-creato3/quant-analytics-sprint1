"""Section 7.1 structured input contract — adapter over market_analysis assembler."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.schemas.ticker_analysis import TickerAnalysisPayload as TickerAnalysisPayloadSchema
from app.services.analysis.context import AnalysisContext, NewsSentimentSummary
from app.services.market_analysis.assembler import build_ticker_analysis_payload
from app.services.prediction_hierarchy.types import ForecastOutput

logger = get_logger(__name__)

_PAYLOAD_CACHE: dict[str, tuple[float, TickerAnalysisPayloadSchema]] = {}
_CACHE_TTL_SECONDS = 300


@dataclass(frozen=True, slots=True)
class ShapFactor:
    feature: str
    contribution: float


@dataclass(frozen=True, slots=True)
class TickerAnalysisPayload:
    """Chat-layer view of Section 7.1 payload (mirrors pydantic schema)."""

    ticker: str
    ml_score: float | None
    shap_top_factors: tuple[ShapFactor, ...]
    factor_exposures: dict[str, float | None]
    risk_metrics: dict[str, float | None]
    scenario_results: dict[str, float | None] | None
    peer_comparison: dict[str, float | None] | None
    as_of: str = ""
    news_titles: tuple[str, ...] = ()
    news_sentiment_positive: int = 0
    news_sentiment_negative: int = 0
    news_sentiment_neutral: int = 0
    news_sentiment_avg: float | None = None
    data_gaps: tuple[str, ...] = ()
    shap_available: bool = False
    factor_implied_covariance: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ticker": self.ticker,
            "ml_score": self.ml_score,
            "shap_top_factors": [
                {"feature": f.feature, "contribution": f.contribution}
                for f in self.shap_top_factors
            ],
            "factor_exposures": self.factor_exposures,
            "risk_metrics": self.risk_metrics,
            "scenario_results": self.scenario_results,
            "peer_comparison": self.peer_comparison,
            "as_of": self.as_of,
            "news_titles": list(self.news_titles),
            "news_sentiment_positive": self.news_sentiment_positive,
            "news_sentiment_negative": self.news_sentiment_negative,
            "news_sentiment_neutral": self.news_sentiment_neutral,
            "news_sentiment_avg": self.news_sentiment_avg,
            "data_gaps": list(self.data_gaps),
            "shap_available": self.shap_available,
            "factor_implied_covariance": self.factor_implied_covariance,
        }


def _schema_to_dataclass(
    schema: TickerAnalysisPayloadSchema,
    *,
    news_titles: tuple[str, ...] = (),
    news_sentiment: NewsSentimentSummary | None = None,
    as_of: str = "",
) -> TickerAnalysisPayload:
    shap = tuple(
        ShapFactor(feature=item.feature, contribution=item.contribution)
        for item in (schema.shap_top_factors or [])
    )
    peer: dict[str, float | None] | None = None
    if schema.peer_comparison:
        peer = {
            "sector_avg_score": schema.peer_comparison.sector_avg_score,
            "sector": schema.peer_comparison.sector,
            "peer_count": float(schema.peer_comparison.peer_count)
            if schema.peer_comparison.peer_count is not None
            else None,
        }
    return TickerAnalysisPayload(
        ticker=schema.ticker,
        ml_score=schema.ml_score,
        shap_top_factors=shap,
        factor_exposures=dict(schema.factor_exposures),
        risk_metrics=dict(schema.risk_metrics),
        scenario_results=dict(schema.scenario_results) if schema.scenario_results else None,
        peer_comparison=peer,
        as_of=as_of,
        news_titles=news_titles,
        news_sentiment_positive=news_sentiment.positive if news_sentiment else 0,
        news_sentiment_negative=news_sentiment.negative if news_sentiment else 0,
        news_sentiment_neutral=news_sentiment.neutral if news_sentiment else 0,
        news_sentiment_avg=news_sentiment.avg_score if news_sentiment else None,
        data_gaps=tuple(schema.data_gaps),
        shap_available=schema.shap_available,
        factor_implied_covariance=schema.factor_implied_covariance,
    )


def assemble_ticker_analysis_payload(
    *,
    output: ForecastOutput,
    analysis: AnalysisContext,
    fundamentals: dict[str, Any] | None = None,
) -> TickerAnalysisPayload:
    """Build chat payload from pre-loaded analysis context (no extra DB round-trip)."""
    if analysis.ticker_analysis is not None:
        return _schema_to_dataclass(
            analysis.ticker_analysis,
            news_titles=tuple(h.title for h in analysis.news_headlines),
            news_sentiment=analysis.news_sentiment,
            as_of=getattr(output, "as_of", "") or "",
        )

    from app.services.market_analysis.style_factors import STYLE_FACTOR_NAMES

    factor_exposures: dict[str, float | None] = {name: None for name in STYLE_FACTOR_NAMES}
    for key, val in analysis.factor_exposures.items():
        factor_exposures[key] = round(float(val), 4) if val is not None else None

    ml_score = round(float(output.calibrated_confidence), 4)
    return TickerAnalysisPayload(
        ticker=output.symbol,
        ml_score=ml_score,
        shap_top_factors=(),
        factor_exposures=factor_exposures,
        risk_metrics={k: None for k in ("var_95", "cvar_95", "beta", "volatility", "sharpe", "max_drawdown", "tracking_error")},
        scenario_results=None,
        peer_comparison=None,
        as_of=getattr(output, "as_of", "") or "",
        news_titles=tuple(h.title for h in analysis.news_headlines),
        news_sentiment_positive=analysis.news_sentiment.positive if analysis.news_sentiment else 0,
        news_sentiment_negative=analysis.news_sentiment.negative if analysis.news_sentiment else 0,
        news_sentiment_neutral=analysis.news_sentiment.neutral if analysis.news_sentiment else 0,
        news_sentiment_avg=analysis.news_sentiment.avg_score if analysis.news_sentiment else None,
        data_gaps=tuple(analysis.data_gaps),
        shap_available=False,
    )


async def get_ticker_analysis_payload(
    db: AsyncSession,
    *,
    instrument_id: int,
    symbol: str,
    output: ForecastOutput | None = None,
    analysis: AnalysisContext | None = None,
    fundamentals: dict[str, Any] | None = None,
    use_cache: bool = True,
) -> TickerAnalysisPayload:
    """Fresh payload per turn; delegates to ``build_ticker_analysis_payload``."""
    cache_key = f"{instrument_id}:{symbol.strip().upper()}"
    now = time.monotonic()
    if use_cache and cache_key in _PAYLOAD_CACHE:
        cached_at, cached = _PAYLOAD_CACHE[cache_key]
        if now - cached_at < _CACHE_TTL_SECONDS:
            return _schema_to_dataclass(
                cached,
                news_titles=tuple(h.title for h in (analysis.news_headlines if analysis else [])),
                news_sentiment=analysis.news_sentiment if analysis else None,
                as_of=getattr(output, "as_of", "") if output else "",
            )

    schema = await build_ticker_analysis_payload(
        symbol,
        db,
        instrument_id=instrument_id,
        hierarchy=output,
    )
    _PAYLOAD_CACHE[cache_key] = (now, schema)

    if analysis is None:
        from app.services.analysis.context import gather_analysis_context

        analysis = await gather_analysis_context(
            db,
            instrument_id=instrument_id,
            symbol=symbol,
            output=output,
            include_structured=False,
        )

    return _schema_to_dataclass(
        schema,
        news_titles=tuple(h.title for h in analysis.news_headlines),
        news_sentiment=analysis.news_sentiment,
        as_of=getattr(output, "as_of", "") if output else "",
    )


def clear_payload_cache() -> None:
    """Test helper — drop cached payloads."""
    _PAYLOAD_CACHE.clear()
