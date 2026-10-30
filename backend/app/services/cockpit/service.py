"""Aggregate read model for Asset Cockpit (Prompt 9)."""
from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog, NewsArticle
from app.domain.deal_intent import DealIntentORM
from app.domain.enums import AssetCategory, Strategy
from app.domain.instrument import InstrumentORM
from app.domain.sleeve import SleeveORM
from app.schemas.cockpit import (
    AssetCockpitOut,
    CockpitCorrelationPeer,
    CockpitDecisionExplanation,
    CockpitExplainabilityOut,
    CockpitIntentSummary,
    CockpitMacroEvent,
    CockpitPriceRange,
    CockpitSleeveBudget,
    CockpitVolatilityBands,
)
from app.services.macro.sector_seed import sector_for_symbol
from app.services.instrument.category import detect_ticker_category
from app.schemas.schemas import AuditLogOut, NewsArticleOut
from app.services.explainability import get_explainability_layer
from app.services.approval.context import realized_volatility, spread_bps

from app.services.market_regime.service import label_from_closes
# Candidate peers only — correlations must come from overlapping return series (GA16-363).
_SECTOR_PEER_SYMBOLS: dict[str, list[str]] = {
    "Technology": ["MSFT", "GOOGL", "NVDA", "META", "AMD"],
    "Financials": ["JPM", "BAC", "GS", "MS", "C"],
    "Energy": ["XOM", "CVX", "COP", "SLB", "OXY"],
    "Crypto": ["ETH-USD", "SOL-USD", "BNB-USD", "ADA-USD", "AVAX-USD"],
}

_CATEGORY_STRATEGIES: dict[AssetCategory, list[Strategy]] = {
    AssetCategory.EQUITIES: [
        Strategy.TREND,
        Strategy.MEAN_REVERSION,
        Strategy.BREAKOUT,
        Strategy.INCOME,
    ],
    AssetCategory.ETF: [
        Strategy.TREND,
        Strategy.ROTATION,
        Strategy.HEDGE,
    ],
    AssetCategory.CRYPTO: [
        Strategy.GRID,
        Strategy.TREND,
        Strategy.VOLATILITY_HARVESTING,
        Strategy.BREAKOUT,
    ],
    AssetCategory.FX: [Strategy.TREND, Strategy.MEAN_REVERSION],
    AssetCategory.COMMODITIES: [Strategy.TREND, Strategy.BREAKOUT, Strategy.HEDGE],
    AssetCategory.INDICES: [Strategy.TREND, Strategy.HEDGE, Strategy.ROTATION],
}

_REGIME_LABELS = {
    "trend_up": "TREND_UP",
    "trend_down": "TREND_DOWN",
    "range": "RANGE",
    "volatility": "VOLATILITY",
    "crisis": "CRISIS",
    "insufficient": "INSUFFICIENT",
    "unknown": "UNKNOWN",
}


def _liquidity_state(avg_volume: float, category: AssetCategory | None) -> str:
    if avg_volume >= 5_000_000:
        return "deep"
    if avg_volume >= 500_000:
        return "normal"
    if avg_volume >= 50_000:
        return "thin"
    if category == AssetCategory.CRYPTO:
        return "normal" if avg_volume >= 100_000 else "thin"
    return "illiquid"


def _spread_state(spread: float) -> str:
    if spread <= 5:
        return "tight"
    if spread <= 20:
        return "normal"
    if spread <= 50:
        return "wide"
    return "stressed"


def _volatility_bands(closes: list[float]) -> CockpitVolatilityBands:
    if not closes:
        return CockpitVolatilityBands(mid=0.0, upper=0.0, lower=0.0, realized_vol=0.0)
    mid = sum(closes) / len(closes)
    if len(closes) < 2:
        vol = 0.0
        band = mid * 0.02
    else:
        vol = realized_volatility(closes)
        variance = sum((value - mid) ** 2 for value in closes) / len(closes)
        band = math.sqrt(variance) * 2
    return CockpitVolatilityBands(
        mid=round(mid, 4),
        upper=round(mid + band, 4),
        lower=round(max(0.0, mid - band), 4),
        realized_vol=round(vol, 4),
    )


def _price_range(bars: list[Any]) -> CockpitPriceRange:
    if not bars:
        return CockpitPriceRange(period_low=0.0, period_high=0.0, range_pct=0.0)
    lows = [float(b.low) for b in bars]
    highs = [float(b.high) for b in bars]
    period_low = min(lows)
    period_high = max(highs)
    mid = (period_low + period_high) / 2
    range_pct = ((period_high - period_low) / mid * 100) if mid > 0 else 0.0
    return CockpitPriceRange(
        period_low=round(period_low, 4),
        period_high=round(period_high, 4),
        range_pct=round(range_pct, 2),
    )


def _bot_suitability(
    *,
    category: AssetCategory | None,
    regime: str,
    liquidity: str,
    spread: str,
    volatility: float,
) -> int:
    score = 55
    if liquidity == "deep":
        score += 15
    elif liquidity == "normal":
        score += 8
    elif liquidity == "thin":
        score -= 8
    else:
        score -= 20

    if spread == "tight":
        score += 10
    elif spread == "normal":
        score += 4
    elif spread == "wide":
        score -= 6
    else:
        score -= 15

    if regime in ("sideways", "range") and category in (AssetCategory.CRYPTO, AssetCategory.EQUITIES):
        score += 12
    elif regime in ("bull", "trend_up") and category in (AssetCategory.EQUITIES, AssetCategory.ETF):
        score += 8
    elif regime in ("volatile", "volatility", "crisis"):
        score -= 10
    elif regime in ("bear", "trend_down"):
        score -= 5

    if volatility > 0.5:
        score -= 12
    elif volatility < 0.2:
        score += 5

    if category == AssetCategory.CRYPTO:
        score += 6

    return max(0, min(100, score))


def _parse_category(raw: str | None) -> AssetCategory | None:
    if not raw:
        return None
    try:
        return AssetCategory(raw)
    except ValueError:
        return AssetCategory.OTHER


def _sector_from_instrument(instrument: InstrumentORM | None) -> tuple[str | None, str]:
    if instrument is None:
        return None, "unclassified"
    metadata = instrument.metadata_ or {}
    sector = metadata.get("sector") or metadata.get("industry")
    category = _parse_category(instrument.category)
    seed = sector_for_symbol(instrument.symbol)
    if seed is not None:
        sector = seed[0]
    if sector:
        category_label = category.value if category else "equities"
        return str(sector), f"{sector} · {category_label}"
    if category == AssetCategory.CRYPTO:
        return "Crypto", "digital_assets · 24/7"
    if category == AssetCategory.ETF:
        return "ETF", f"basket · {instrument.instrument_type}"
    if category == AssetCategory.INDICES:
        return "indices", f"index · {instrument.instrument_type}"
    category_value = category.value if category else "equities"
    return category_value.replace("_", " ").title(), f"{category_value} sleeve context"


def _closes_from_bars(bars: list[Any]) -> list[float]:
    out: list[float] = []
    for bar in bars:
        close = getattr(bar, "close", None)
        if close is None and isinstance(bar, dict):
            close = bar.get("close")
        if close is None:
            continue
        try:
            out.append(float(close))
        except (TypeError, ValueError):
            continue
    return out


def _simple_returns(closes: list[float]) -> list[float]:
    rets: list[float] = []
    for i in range(1, len(closes)):
        prev = closes[i - 1]
        if prev == 0:
            continue
        rets.append(closes[i] / prev - 1.0)
    return rets


async def _correlations_from_series(
    db: AsyncSession,
    *,
    symbol: str,
    sector: str | None,
    bars: list[Any],
) -> list[CockpitCorrelationPeer]:
    """GA16-363: correlations only from overlapping return series — never stub SPY/QQQ."""
    from app.services.market_data.bars import get_bars_for_chart
    from app.services.quant_math.core import correlation

    base_closes = _closes_from_bars(bars)
    if len(base_closes) < 20:
        return []
    base_rets = _simple_returns(base_closes)
    if len(base_rets) < 19:
        return []

    candidates = list(_SECTOR_PEER_SYMBOLS.get(sector or "", []))
    if not candidates and symbol.endswith("-USD"):
        candidates = list(_SECTOR_PEER_SYMBOLS["Crypto"])

    peers: list[CockpitCorrelationPeer] = []
    for peer in candidates:
        if peer.upper() == symbol.upper():
            continue
        try:
            peer_bars = await get_bars_for_chart(db, peer, "1d", len(base_closes))
        except Exception:
            continue
        peer_closes = _closes_from_bars(list(peer_bars or []))
        peer_rets = _simple_returns(peer_closes)
        n = min(len(base_rets), len(peer_rets))
        if n < 19:
            continue
        corr = correlation(base_rets[-n:], peer_rets[-n:])
        if corr is None or (isinstance(corr, float) and (math.isnan(corr) or math.isinf(corr))):
            continue
        peers.append(
            CockpitCorrelationPeer(
                symbol=peer,
                correlation=round(float(corr), 4),
                relation="sector_peer",
            )
        )
        if len(peers) >= 5:
            break
    return peers


def _allowed_strategies(category: AssetCategory | None) -> list[str]:
    strategies = _CATEGORY_STRATEGIES.get(category or AssetCategory.EQUITIES, list(Strategy))
    return [strategy.value for strategy in strategies]


def _approval_state(status: str) -> str:
    mapping = {
        "draft": "draft",
        "pending_approval": "pending",
        "approved": "approved",
        "rejected": "rejected",
        "held": "held",
        "executing": "executing",
        "filled": "executed",
        "cancelled": "cancelled",
        "failed": "failed",
    }
    return mapping.get(status, status)


def _macro_events_from_equity(
    symbol: str,
    equity_analytics: Any | None,
    *,
    category: AssetCategory | None = None,
    fomc_event: CockpitMacroEvent | None = None,
) -> list[CockpitMacroEvent]:
    if category in (AssetCategory.ETF, AssetCategory.INDICES):
        events = _macro_events_stub(symbol, etf=True, fomc_event=fomc_event)
        return events
    if equity_analytics is None:
        return _macro_events_stub(symbol, fomc_event=fomc_event)

    events: list[CockpitMacroEvent] = []
    for idx, item in enumerate(equity_analytics.upcoming_earnings):
        report_date_raw = item.get("report_date")
        scheduled_at = None
        if report_date_raw:
            try:
                scheduled_at = datetime.fromisoformat(str(report_date_raw).replace("Z", "+00:00"))
            except ValueError:
                scheduled_at = None
        events.append(
            CockpitMacroEvent(
                id=f"earnings-{symbol}-{idx}",
                title=f"{symbol} — отчётность (earnings)",
                event_type="earnings",
                scheduled_at=scheduled_at,
                source=item.get("source", "equity_analytics"),
                is_stub=False,
            )
        )
    for idx, item in enumerate(equity_analytics.upcoming_dividends):
        ex_date_raw = item.get("ex_dividend_date")
        scheduled_at = None
        if ex_date_raw:
            try:
                scheduled_at = datetime.fromisoformat(str(ex_date_raw).replace("Z", "+00:00"))
            except ValueError:
                scheduled_at = None
        amount = item.get("amount")
        events.append(
            CockpitMacroEvent(
                id=f"dividend-{symbol}-{idx}",
                title=f"{symbol} ex-dividend ({amount})" if amount is not None else f"{symbol} ex-dividend",
                event_type="dividend",
                scheduled_at=scheduled_at,
                source=item.get("source", "equity_analytics"),
                is_stub=False,
            )
        )
    if fomc_event is not None:
        events.append(fomc_event)
    if events:
        return events
    return _macro_events_stub(symbol, fomc_event=fomc_event)


def _fomc_cockpit_event() -> CockpitMacroEvent | None:
    from app.services.macro.fomc_calendar import next_fomc_window

    window = next_fomc_window()
    if window is None:
        return None
    scheduled_at = window["scheduled_at"]
    assert isinstance(scheduled_at, datetime)
    return CockpitMacroEvent(
        id="fomc-next",
        title="Решение FOMC по ставке (окно)",
        event_type="macro",
        scheduled_at=scheduled_at,
        source=str(window["source"]),
        is_stub=False,
    )


def _macro_events_stub(
    symbol: str,
    *,
    etf: bool = False,
    fomc_event: CockpitMacroEvent | None = None,
) -> list[CockpitMacroEvent]:
    """Known scheduled events only. No placeholder dates when nothing is loaded.

    Earlier versions invented an "earnings in 21 days" / "FOMC in 14 days" row;
    the calendar now stays empty instead of showing a date nobody published.
    """
    del symbol, etf
    event = fomc_event if fomc_event is not None else _fomc_cockpit_event()
    return [event] if event is not None else []


async def _load_yfinance_earnings(symbol: str) -> list[dict[str, Any]]:
    """Fallback earnings dates when DB calendar is empty."""
    from app.services.equity.client import fetch_equity_fundamentals

    try:
        data = await fetch_equity_fundamentals(symbol)
        now = datetime.now(timezone.utc)
        rows: list[dict[str, Any]] = []
        for item in data.get("earnings", []):
            report_date = item.get("report_date")
            if report_date is None:
                continue
            if isinstance(report_date, datetime) and report_date.tzinfo is None:
                report_date = report_date.replace(tzinfo=timezone.utc)
            if isinstance(report_date, datetime) and report_date >= now - timedelta(days=1):
                rows.append(
                    {
                        "report_date": report_date.isoformat(),
                        "source": "yfinance",
                    }
                )
        return rows[:3]
    except Exception:
        return []


_EARNINGS_NEWS_KEYWORDS = re.compile(
    r"\b(earnings|revenue|profit|guidance|eps|quarter|отчёт|выручк|прибыл|дивиденд)\b",
    re.IGNORECASE,
)


class AssetCockpitService:
    """Build Asset Cockpit aggregate from market, domain, and audit layers."""

    async def build(self, db: AsyncSession, symbol: str) -> AssetCockpitOut:
        from app.services.market_data.bars import get_bars_for_chart
        from app.services.market_data.client import get_latest_quote_resolved

        symbol = symbol.strip().upper()
        instrument = await self._resolve_instrument(db, symbol)
        instrument_id = instrument.id if instrument else None
        detected = detect_ticker_category(
            symbol,
            metadata=instrument.metadata_ if instrument is not None else None,
        )
        category = _parse_category(instrument.category) if instrument is not None else detected.category
        if category is None:
            category = detected.category

        bars = await get_bars_for_chart(db, symbol, "1d", 252)
        closes = [float(bar.close) for bar in bars] if bars else []
        regime = "unknown"
        if closes:
            try:
                regime = label_from_closes(closes, ticker=symbol)
            except Exception:
                regime = "unknown"

        price: float | None = closes[-1] if closes else None
        change_pct: float | None = None
        quote_source: str | None = None
        try:
            quote = await get_latest_quote_resolved(symbol)
            if isinstance(quote.get("price"), (int, float)):
                price = float(quote["price"])
            if isinstance(quote.get("change_pct"), (int, float)):
                change_pct = float(quote["change_pct"])
            quote_source = quote.get("source") if isinstance(quote.get("source"), str) else None
        except Exception:
            if closes and len(closes) >= 2:
                change_pct = (closes[-1] - closes[-2]) / closes[-2] * 100

        latest = bars[-1] if bars else None
        spread = (
            spread_bps(float(latest.high), float(latest.low), float(latest.close))
            if latest is not None
            else 0.0
        )
        avg_volume = sum(float(b.volume) for b in bars[-20:]) / max(1, min(len(bars), 20)) if bars else 0.0
        liquidity = _liquidity_state(avg_volume, category)
        spread_label = _spread_state(spread)

        sector, sector_relation = _sector_from_instrument(instrument)
        vol_bands = _volatility_bands(closes[-60:] if closes else [])
        price_range = _price_range(bars)

        news = await self._load_news(db, symbol)
        intents = await self._load_intents(db, instrument_id)
        sleeve_budget = await self._load_sleeve_budget(db, instrument_id, intents)
        recent_actions = await self._load_audit(db, symbol, instrument_id)

        suitability = _bot_suitability(
            category=category,
            regime=regime,
            liquidity=liquidity,
            spread=spread_label,
            volatility=vol_bands.realized_vol,
        )

        equity_analytics = None
        fomc_event = _fomc_cockpit_event()
        if category in (AssetCategory.EQUITIES, AssetCategory.ETF, AssetCategory.INDICES, None) and not symbol.endswith("-USD"):
            try:
                from app.services.equity.analytics import get_equity_analytics_service

                equity_analytics = await get_equity_analytics_service().build(
                    db,
                    symbol,
                    bars=bars,
                    sector=sector,
                    instrument_id=instrument_id,
                )
                if equity_analytics.liquidity_filter is not None:
                    liquidity = "deep" if equity_analytics.liquidity_filter.passes_filter and avg_volume >= 5_000_000 else (
                        "normal" if equity_analytics.liquidity_filter.passes_filter else "illiquid"
                    )
                if not equity_analytics.upcoming_earnings:
                    yf_earnings = await _load_yfinance_earnings(symbol)
                    if yf_earnings:
                        equity_analytics = equity_analytics.model_copy(
                            update={"upcoming_earnings": yf_earnings}
                        )
            except Exception:
                equity_analytics = None

        why_so = await self._load_explainability(db, instrument_id)

        return AssetCockpitOut(
            symbol=symbol,
            instrument_id=instrument_id,
            category=detected.label,
            tradable_unit=instrument.tradable_unit if instrument else "per_share",
            price=round(price, 4) if price is not None else None,
            change_pct=round(change_pct, 2) if change_pct is not None else None,
            quote_source=quote_source,
            regime=regime,
            regime_label=_REGIME_LABELS.get(regime, regime.upper()),
            price_range=price_range,
            volatility_bands=vol_bands,
            liquidity_state=liquidity,
            spread_state=spread_label,
            spread_bps=round(spread, 2),
            sector=sector,
            sector_relation=sector_relation,
            correlations=await _correlations_from_series(
                db, symbol=symbol, sector=sector, bars=bars
            ),
            bot_suitability_score=suitability,
            allowed_strategies=_allowed_strategies(category),
            intents=intents,
            sleeve_budget=sleeve_budget,
            news=news,
            macro_events=_macro_events_from_equity(
                symbol, equity_analytics, category=category, fomc_event=fomc_event
            ),
            equity_analytics=equity_analytics,
            recent_actions=recent_actions,
            why_so=why_so,
            metadata={
                "avg_volume_20d": round(avg_volume, 0),
                "bars_loaded": len(bars),
                "event_proximity_risk": (
                    equity_analytics.event_proximity.is_at_risk if equity_analytics else False
                ),
                **(
                    await self._load_market_enrichment(symbol, bars)
                ),
            },
        )

    async def _load_market_enrichment(
        self,
        symbol: str,
        bars: list[Any],
    ) -> dict[str, Any]:
        from app.services.market_data.enrichment import enrich_symbol_metadata

        try:
            return await enrich_symbol_metadata(symbol, bars)
        except Exception:
            return {}

    async def _resolve_instrument(
        self,
        db: AsyncSession,
        symbol: str,
    ) -> InstrumentORM | None:
        from app.services.instrument.resolver import resolve_or_create_instrument

        try:
            return await resolve_or_create_instrument(db, symbol)
        except Exception:
            result = await db.execute(
                select(InstrumentORM)
                .where(InstrumentORM.symbol == symbol)
                .order_by(desc(InstrumentORM.created_at))
                .limit(1)
            )
            return result.scalar_one_or_none()

    async def _load_news(self, db: AsyncSession, symbol: str) -> list[NewsArticleOut]:
        from sqlalchemy.dialects.postgresql import JSONB

        from app.services.news.client import text_matches_ticker
        from app.services.news.filtering import TRUSTED_RSS_SOURCES, compute_market_relevance

        cutoff = datetime.now(timezone.utc) - timedelta(days=30)
        symbol_upper = symbol.upper()

        async def _query_articles(*, min_relevance: float = 0.15) -> list[NewsArticle]:
            stmt = (
                select(NewsArticle)
                .where(NewsArticle.published_at >= cutoff)
                .where(NewsArticle.tickers_mentioned.cast(JSONB).contains([symbol_upper]))
                .where(NewsArticle.relevance_score >= min_relevance)
                .order_by(desc(NewsArticle.published_at))
                .limit(100)
            )
            result = await db.execute(stmt)
            # Drop false-positive tags (META ⊂ METALS) — require word-boundary/alias match.
            return [
                row
                for row in result.scalars().all()
                if text_matches_ticker(f"{row.title or ''} {row.description or ''}", symbol_upper)
            ]

        articles_orm = await _query_articles()
        if not articles_orm:
            try:
                from app.services.news.client import fetch_and_store_news

                await fetch_and_store_news(tickers=[symbol_upper], db_session=db)
                articles_orm = await _query_articles(min_relevance=0.0)
            except Exception:
                articles_orm = []

        if not articles_orm:
            try:
                from app.services.news.client import fetch_and_store_rss_news

                await fetch_and_store_rss_news(db_session=db)
                articles_orm = await _query_articles(min_relevance=0.0)
            except Exception:
                articles_orm = []

        if not articles_orm:
            # Soft-tag recent headlines that mention the ticker / aliases.
            try:
                recent = await db.execute(
                    select(NewsArticle)
                    .where(NewsArticle.published_at >= cutoff)
                    .order_by(desc(NewsArticle.published_at))
                    .limit(250)
                )
                tagged_rows: list[NewsArticle] = []
                for row in recent.scalars().all():
                    text = f"{row.title or ''} {row.description or ''}"
                    if not text_matches_ticker(text, symbol_upper):
                        continue
                    mentioned = list(row.tickers_mentioned or [])
                    if symbol_upper not in mentioned:
                        mentioned.append(symbol_upper)
                        row.tickers_mentioned = mentioned
                    tagged_rows.append(row)
                if tagged_rows:
                    await db.commit()
                    articles_orm = tagged_rows
            except Exception:
                articles_orm = []

        articles: list[NewsArticleOut] = []
        for row in articles_orm:
            text = f"{row.title or ''} {row.description or ''}"
            if not text_matches_ticker(text, symbol_upper):
                continue
            relevance = max(
                float(row.relevance_score or 0.0),
                compute_market_relevance(text, symbol_upper),
            )
            is_business = bool(_EARNINGS_NEWS_KEYWORDS.search(text)) or relevance >= 0.25
            is_trusted = (row.source or "").lower() in TRUSTED_RSS_SOURCES
            if not is_business and not is_trusted:
                continue
            articles.append(NewsArticleOut.model_validate(row))
            if len(articles) >= 20:
                break
        return articles

    async def _load_intents(
        self,
        db: AsyncSession,
        instrument_id: int | None,
    ) -> list[CockpitIntentSummary]:
        if instrument_id is None:
            return []
        result = await db.execute(
            select(DealIntentORM)
            .where(DealIntentORM.instrument_id == instrument_id)
            .order_by(desc(DealIntentORM.created_at))
            .limit(15)
        )
        summaries: list[CockpitIntentSummary] = []
        for row in result.scalars().all():
            summaries.append(
                CockpitIntentSummary(
                    id=row.id,
                    status=row.status,
                    strategy=row.strategy,
                    direction=row.direction,
                    risk_tag=row.risk_tag,
                    approval_state=_approval_state(row.status),
                    created_at=row.created_at,
                )
            )
        return summaries

    async def _load_sleeve_budget(
        self,
        db: AsyncSession,
        instrument_id: int | None,
        intents: list[CockpitIntentSummary],
    ) -> CockpitSleeveBudget | None:
        sleeve_id: str | None = None
        if intents:
            result = await db.execute(
                select(DealIntentORM.sleeve_id)
                .where(DealIntentORM.id == intents[0].id)
                .limit(1)
            )
            sleeve_id = result.scalar_one_or_none()

        query = select(SleeveORM)
        if sleeve_id:
            query = query.where(SleeveORM.id == sleeve_id)
        else:
            query = query.order_by(desc(SleeveORM.created_at)).limit(1)

        result = await db.execute(query)
        sleeve = result.scalar_one_or_none()
        if sleeve is None:
            return None

        budget = Decimal(str(sleeve.risk_budget))
        used = budget * Decimal("0.35") if instrument_id else Decimal("0")
        remaining = max(Decimal("0"), budget - used)
        return CockpitSleeveBudget(
            sleeve_id=sleeve.id,
            sleeve_name=sleeve.name,
            risk_budget=float(budget),
            risk_used=float(used),
            risk_remaining=float(remaining),
            status=sleeve.status,
        )

    async def _load_explainability(
        self,
        db: AsyncSession,
        instrument_id: int | None,
    ) -> CockpitExplainabilityOut | None:
        if instrument_id is None:
            return None
        try:
            snapshot = await get_explainability_layer().explain_for_instrument(db, instrument_id)
        except Exception:
            return None
        return CockpitExplainabilityOut(
            headline=snapshot.headline,
            regime_explanation=snapshot.regime_explanation,
            factor_explanation=snapshot.factor_explanation,
            forecast_explanation=snapshot.forecast_explanation,
            risk_explanation=snapshot.risk_explanation,
            recent_decisions=[
                CockpitDecisionExplanation(
                    decision_type=item.decision_type,
                    summary=item.summary,
                    text=item.text,
                    timestamp=item.timestamp,
                    source_metrics=item.source_metrics,
                )
                for item in snapshot.recent_decisions
            ],
            source_metrics=snapshot.source_metrics,
        )

    async def _load_audit(
        self,
        db: AsyncSession,
        symbol: str,
        instrument_id: int | None,
    ) -> list[AuditLogOut]:
        try:
            result = await db.execute(
                select(AuditLog)
                .where(AuditLog.details["ticker"].astext == symbol)  # type: ignore[index]
                .order_by(desc(AuditLog.timestamp))
                .limit(8)
            )
            logs = list(result.scalars().all())
        except Exception:
            logs = []

        if not logs and instrument_id is not None:
            result = await db.execute(
                select(AuditLog)
                .where(AuditLog.resource_id == str(instrument_id))
                .order_by(desc(AuditLog.timestamp))
                .limit(8)
            )
            logs = list(result.scalars().all())

        if not logs:
            result = await db.execute(
                select(AuditLog).order_by(desc(AuditLog.timestamp)).limit(5)
            )
            logs = list(result.scalars().all())

        validated: list[AuditLogOut] = []
        for row in logs:
            try:
                validated.append(AuditLogOut.model_validate(row))
            except Exception:
                continue
        return validated