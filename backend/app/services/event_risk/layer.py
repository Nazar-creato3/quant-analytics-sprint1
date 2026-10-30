"""EventRiskLayer — subscribe to news/calendar streams and enforce TTL locks."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import desc, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.models import NewsArticle
from app.domain.active_lock import ActiveLockCreate, ActiveLockType
from app.domain.instrument import InstrumentORM
from app.domain.news_impact import NewsImpactHistoryCreate
from app.domain.sleeve import SleeveORM
from app.services.event_risk.alerts import emit_news_shock_alert
from app.services.event_risk.calendar import EventCalendarAdapter
from app.services.event_risk.factor_exposure_reader import FactorExposureReader
from app.services.event_risk.feedback import NewsImpactFeedbackService
from app.services.event_risk.news_impact import compute_daily_volatility_from_prices, extract_topic_tags
from app.services.event_risk.news_impact_repository import NewsImpactHistoryRepository
from app.services.event_risk.repository import ActiveLockRepository
from app.services.event_risk.scoring import compute_news_shock_score
from app.services.event_risk.types import NewsShockAssessment, NewsShockTarget
from app.services.news.client import extract_tickers_from_text


class EventRiskLayer:
    """Realtime news_shock monitor backed by news_articles, connector news, and calendar."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        repository: ActiveLockRepository | None = None,
        calendar: EventCalendarAdapter | None = None,
        equity_service: object | None = None,
        impact_repository: NewsImpactHistoryRepository | None = None,
        factor_reader: FactorExposureReader | None = None,
        feedback_service: NewsImpactFeedbackService | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._repository = repository or ActiveLockRepository()
        self._calendar = calendar or EventCalendarAdapter(equity_service=equity_service)
        self._equity = equity_service
        if self._equity is None:
            try:
                from app.services.equity.analytics import get_equity_analytics_service

                self._equity = get_equity_analytics_service()
            except ImportError:
                self._equity = None
        self._impact_repository = impact_repository or NewsImpactHistoryRepository()
        self._factor_reader = factor_reader or FactorExposureReader()
        self._feedback = feedback_service or NewsImpactFeedbackService(repository=self._impact_repository)
        self._last_news_poll_at: datetime | None = None

    async def expire_stale_locks(self, db: AsyncSession, *, as_of: datetime | None = None) -> int:
        return await self._repository.expire_stale(db, as_of=as_of)

    async def process_feedback(self, db: AsyncSession, *, as_of: datetime | None = None) -> int:
        return await self._feedback.process_pending(db, as_of=as_of)

    async def get_active_locks(self, db: AsyncSession, *, as_of: datetime | None = None):
        return await self._repository.list_active(db, as_of=as_of)

    async def locked_instrument_ids(
        self,
        db: AsyncSession,
        *,
        as_of: datetime | None = None,
    ) -> frozenset[int]:
        sector_ids = await self._sector_locked_instrument_ids(db, as_of=as_of)
        direct = await self._repository.locked_instrument_ids(db, as_of=as_of)
        return frozenset(set(direct) | set(sector_ids))

    async def locked_sleeve_ids(
        self,
        db: AsyncSession,
        *,
        as_of: datetime | None = None,
    ) -> frozenset[str]:
        return await self._repository.locked_sleeve_ids(db, as_of=as_of)

    async def process_cycle(self, db: AsyncSession, *, as_of: datetime | None = None) -> list[NewsShockAssessment]:
        """Poll news + calendar, create TTL locks when threshold breached."""
        now = self._utc(as_of)
        await self.expire_stale_locks(db, as_of=now)

        articles = await self._poll_news_stream(db, as_of=now)
        macro_events = await self._calendar.load_macro_events(db, as_of=now)
        instruments = await self._load_instruments(db)
        sleeve_map = await self._load_sleeves_by_category(db)

        triggered: list[NewsShockAssessment] = []
        for instrument in instruments:
            symbol = instrument.symbol.upper()
            sector = self._instrument_sector(instrument)
            proximity = await self._calendar.load_proximity(db, symbol, as_of=now)
            symbol_articles = self._articles_for_symbol(articles, symbol)
            assessment = await self._assess_instrument(
                db,
                instrument=instrument,
                symbol=symbol,
                sector=sector,
                articles=symbol_articles,
                macro_events=macro_events,
                proximity=proximity,
                sleeve_ids=sleeve_map.get(instrument.category or "", frozenset()),
                as_of=now,
            )
            if assessment.score < self._settings.EVENT_RISK_NEWS_SHOCK_THRESHOLD:
                continue

            created = await self._apply_lock(db, assessment, as_of=now)
            if created:
                triggered.append(assessment)
                await emit_news_shock_alert(assessment, settings=self._settings)

        self._last_news_poll_at = now
        return triggered

    async def assess_target(
        self,
        db: AsyncSession,
        symbol: str,
        *,
        instrument_id: int | None = None,
        sector: str | None = None,
        as_of: datetime | None = None,
    ) -> NewsShockAssessment:
        now = self._utc(as_of)
        symbol = symbol.upper()
        articles = await self._poll_news_stream(db, as_of=now)
        macro_events = await self._calendar.load_macro_events(db, as_of=now)
        proximity = await self._calendar.load_proximity(db, symbol, as_of=now)
        instrument = SimpleInstrument(id=instrument_id, symbol=symbol, metadata_= {"sector": sector} if sector else {})
        return await self._assess_instrument(
            db,
            instrument=instrument,
            symbol=symbol,
            sector=sector,
            articles=self._articles_for_symbol(articles, symbol),
            macro_events=macro_events,
            proximity=proximity,
            sleeve_ids=frozenset(),
            as_of=now,
        )

    async def _assess_instrument(
        self,
        db: AsyncSession,
        *,
        instrument: Any,
        symbol: str,
        sector: str | None,
        articles: list[Any],
        macro_events: list[Any],
        proximity: Any,
        sleeve_ids: frozenset[str],
        as_of: datetime,
    ) -> NewsShockAssessment:
        instrument_id = getattr(instrument, "id", None)
        daily_volatility = 0.0
        impact_history = []
        factor_exposures: dict[str, float] = {}

        if instrument_id is not None:
            daily_volatility = await self._load_daily_volatility(db, instrument_id=instrument_id)
            history_rows = await self._impact_repository.list_for_instrument(db, instrument_id)
            impact_history = self._impact_repository.to_analogs(history_rows)
            factor_exposures = await self._factor_reader.load_exposures(
                db,
                instrument_id,
                sector=sector,
                instrument_metadata=getattr(instrument, "metadata_", None) or {},
            )

        score, news_impact, calendar_boost, macro_boost, article_count, reason, impact_probability = (
            compute_news_shock_score(
                articles,
                as_of=as_of,
                nearest_event_at=proximity.nearest_event_at,
                calendar_at_risk=proximity.is_at_risk,
                macro_events=macro_events,
                symbol=symbol,
                sector=sector,
                lookback_hours=self._settings.NEWS_LOOKBACK_HOURS,
                factor_exposures=factor_exposures,
                impact_history=impact_history,
                daily_volatility=daily_volatility,
                sigma_threshold=self._settings.NEWS_IMPACT_SIGMA_THRESHOLD,
            )
        )

        if instrument_id is not None and articles:
            await self._record_prediction(
                db,
                instrument_id=instrument_id,
                sector=sector,
                articles=articles,
                as_of=as_of,
                impact_probability=impact_probability,
            )

        return NewsShockAssessment(
            target=NewsShockTarget(
                symbol=symbol,
                instrument_id=instrument_id,
                sector=sector,
                sleeve_ids=sleeve_ids,
            ),
            score=score,
            news_impact=news_impact,
            calendar_boost=calendar_boost,
            macro_boost=macro_boost,
            article_count=article_count,
            reason=reason,
            news_impact_probability=impact_probability.probability,
            analog_probability=impact_probability.analog_probability,
            factor_alignment=impact_probability.factor_alignment,
            daily_volatility=impact_probability.daily_volatility,
            topic_tags=impact_probability.topic_tags,
            triggered_at=as_of,
        )

    async def _record_prediction(
        self,
        db: AsyncSession,
        *,
        instrument_id: int,
        sector: str | None,
        articles: list[Any],
        as_of: datetime,
        impact_probability: Any,
    ) -> None:
        primary = articles[0]
        news_id = getattr(primary, "id", None)
        topic_tags = list(impact_probability.topic_tags) or list(extract_topic_tags(primary))
        await self._impact_repository.create(
            db,
            NewsImpactHistoryCreate(
                news_id=str(news_id) if news_id is not None else None,
                instrument_id=instrument_id,
                sector=sector,
                topic_tags=topic_tags,
                predicted_probability=impact_probability.probability,
                predicted_at=as_of,
                daily_volatility=impact_probability.daily_volatility,
                sigma_threshold=impact_probability.sigma_threshold,
                metadata={
                    "analog_probability": impact_probability.analog_probability,
                    "factor_alignment": impact_probability.factor_alignment,
                    "matched_factors": list(impact_probability.matched_factors),
                },
            ),
        )

    async def _load_daily_volatility(self, db: AsyncSession, *, instrument_id: int) -> float:
        query = text(
            """
            SELECT close
            FROM ohlcv
            WHERE instrument_id = :instrument_id
              AND timeframe = '1d'
            ORDER BY time DESC
            LIMIT 31
            """
        )
        try:
            result = await db.execute(query, {"instrument_id": instrument_id})
        except Exception:
            return 0.0

        prices = [float(row["close"]) for row in result.mappings().all() if row.get("close") is not None]
        if len(prices) < 2:
            return 0.0
        prices.reverse()
        return compute_daily_volatility_from_prices(prices)

    async def _apply_lock(
        self,
        db: AsyncSession,
        assessment: NewsShockAssessment,
        *,
        as_of: datetime,
    ) -> bool:
        target = assessment.target
        if target.instrument_id is not None:
            exists = await self._repository.has_active_lock(
                db,
                instrument_id=target.instrument_id,
                as_of=as_of,
            )
            if exists:
                return False

        expires_at = as_of + timedelta(minutes=self._settings.EVENT_RISK_LOCK_TTL_MINUTES)
        lock_type = ActiveLockType.NEWS_SHOCK
        if assessment.calendar_boost >= assessment.news_impact and assessment.calendar_boost > 0:
            lock_type = ActiveLockType.CALENDAR_PROXIMITY
        elif assessment.macro_boost >= max(assessment.news_impact, assessment.calendar_boost):
            lock_type = ActiveLockType.MACRO_EVENT

        await self._repository.create(
            db,
            ActiveLockCreate(
                lock_type=lock_type,
                instrument_id=target.instrument_id,
                sector=target.sector,
                news_shock_score=assessment.score,
                reason=assessment.reason,
                source_event_id=assessment.source_event_id,
                expires_at=expires_at,
                metadata={
                    "symbol": target.symbol,
                    "news_impact": assessment.news_impact,
                    "news_impact_probability": assessment.news_impact_probability,
                    "analog_probability": assessment.analog_probability,
                    "factor_alignment": assessment.factor_alignment,
                    "daily_volatility": assessment.daily_volatility,
                    "topic_tags": list(assessment.topic_tags),
                    "calendar_boost": assessment.calendar_boost,
                    "macro_boost": assessment.macro_boost,
                },
            ),
        )

        for sleeve_id in target.sleeve_ids:
            if await self._repository.has_active_lock(db, sleeve_id=sleeve_id, as_of=as_of):
                continue
            await self._repository.create(
                db,
                ActiveLockCreate(
                    lock_type=lock_type,
                    sleeve_id=sleeve_id,
                    news_shock_score=assessment.score,
                    reason=f"sleeve lock for {target.symbol}: {assessment.reason}",
                    expires_at=expires_at,
                    metadata={
                        "symbol": target.symbol,
                        "instrument_id": target.instrument_id,
                        "news_impact_probability": assessment.news_impact_probability,
                    },
                ),
            )
        return True

    async def _poll_news_stream(self, db: AsyncSession, *, as_of: datetime) -> list[Any]:
        lookback = as_of - timedelta(minutes=self._settings.EVENT_RISK_POLL_LOOKBACK_MINUTES)
        if self._last_news_poll_at is not None and self._last_news_poll_at > lookback:
            lookback = self._last_news_poll_at

        app_news = await self._load_news_articles(db, since=lookback)
        connector_news = await self._load_connector_news(db, since=lookback)
        return app_news + connector_news

    async def _load_news_articles(self, db: AsyncSession, *, since: datetime) -> list[NewsArticle]:
        result = await db.execute(
            select(NewsArticle)
            .where(NewsArticle.published_at >= since)
            .order_by(desc(NewsArticle.published_at))
            .limit(500)
        )
        return list(result.scalars().all())

    async def _load_connector_news(self, db: AsyncSession, *, since: datetime) -> list[Any]:
        """Read RSS rows written by connectors/news_aggregator into ``news`` table."""
        query = text(
            """
            SELECT id, published_at, source, title, url, summary, sentiment, tags
            FROM news
            WHERE published_at >= :since
            ORDER BY published_at DESC
            LIMIT 500
            """
        )
        try:
            result = await db.execute(query, {"since": since})
        except Exception:
            return []

        rows: list[Any] = []
        for row in result.mappings().all():
            tickers = extract_tickers_from_text(f"{row.get('title', '')} {row.get('summary', '')}")
            sentiment = row.get("sentiment")
            rows.append(
                _ConnectorNewsItem(
                    id=str(row.get("id")),
                    published_at=row.get("published_at"),
                    title=row.get("title") or "",
                    summary=row.get("summary") or "",
                    sentiment_score=float(sentiment) if sentiment is not None else None,
                    tickers_mentioned=tickers,
                    tags=row.get("tags") or [],
                    source=row.get("source") or "connector",
                )
            )
        return rows

    async def _load_instruments(self, db: AsyncSession) -> list[InstrumentORM]:
        result = await db.execute(select(InstrumentORM).order_by(InstrumentORM.symbol))
        return list(result.scalars().all())

    async def _load_sleeves_by_category(self, db: AsyncSession) -> dict[str, frozenset[str]]:
        result = await db.execute(select(SleeveORM))
        mapping: dict[str, set[str]] = {}
        for sleeve in result.scalars().all():
            mapping.setdefault(sleeve.category, set()).add(sleeve.id)
        return {key: frozenset(values) for key, values in mapping.items()}

    async def _sector_locked_instrument_ids(
        self,
        db: AsyncSession,
        *,
        as_of: datetime | None = None,
    ) -> frozenset[int]:
        sectors = await self._repository.locked_sectors(db, as_of=as_of)
        if not sectors:
            return frozenset()
        result = await db.execute(select(InstrumentORM))
        locked: set[int] = set()
        for instrument in result.scalars().all():
            sector = self._instrument_sector(instrument)
            if sector and sector in sectors:
                locked.add(instrument.id)
        return frozenset(locked)

    @staticmethod
    def _instrument_sector(instrument: InstrumentORM) -> str | None:
        metadata = instrument.metadata_ or {}
        sector = metadata.get("sector")
        return str(sector) if sector else None

    @staticmethod
    def _articles_for_symbol(articles: list[Any], symbol: str) -> list[Any]:
        symbol_upper = symbol.upper()
        matched: list[Any] = []
        for article in articles:
            tickers = [value.upper() for value in (getattr(article, "tickers_mentioned", None) or [])]
            if symbol_upper in tickers:
                matched.append(article)
                continue
            title = getattr(article, "title", "") or ""
            summary = getattr(article, "summary", "") or getattr(article, "description", "") or ""
            if symbol_upper in extract_tickers_from_text(f"{title} {summary}"):
                matched.append(article)
        return matched

    @staticmethod
    def _utc(value: datetime | None) -> datetime:
        if value is None:
            return datetime.now(timezone.utc)
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class SimpleInstrument:
    def __init__(self, *, id: int | None, symbol: str, metadata_: dict[str, Any]) -> None:
        self.id = id
        self.symbol = symbol
        self.metadata_ = metadata_


class _ConnectorNewsItem:
    def __init__(
        self,
        *,
        id: str,
        published_at: datetime,
        title: str,
        summary: str,
        sentiment_score: float | None,
        tickers_mentioned: list[str],
        tags: list[str] | None = None,
        source: str,
    ) -> None:
        self.id = id
        self.published_at = published_at
        self.title = title
        self.summary = summary
        self.sentiment_score = sentiment_score
        self.tickers_mentioned = tickers_mentioned
        self.tags = tags or []
        self.source = source


_layer = EventRiskLayer()


def get_event_risk_layer() -> EventRiskLayer:
    return _layer
