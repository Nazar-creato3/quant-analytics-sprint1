"""
Macro event ingestion and scoring.

Sources (in priority order):
1. Finnhub economic calendar (if FINNHUB_API_KEY set)
2. High-impact keywords from recent news articles in DB
3. Deterministic regime-based fallback score
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

TIMEOUT = httpx.Timeout(15.0, connect=5.0)

# High-impact macro catalyst keywords
MACRO_KEYWORDS: dict[str, float] = {
    "rate decision": 0.8,
    "interest rate": 0.7,
    "federal reserve": 0.7,
    "fed ": 0.6,
    "cpi": 0.75,
    "inflation": 0.6,
    "gdp": 0.55,
    "nonfarm": 0.65,
    "payroll": 0.6,
    "unemployment": 0.55,
    "sanction": -0.7,
    "tariff": -0.6,
    "war": -0.8,
    "escalation": -0.5,
    "earnings": 0.4,
    "fomc": 0.75,
    "ecb": 0.5,
    "opec": 0.45,
}


async def fetch_finnhub_calendar(
    days_ahead: int = 7,
) -> list[dict[str, Any]]:
    """Fetch economic calendar from Finnhub (free tier)."""
    api_key = getattr(settings, "FINNHUB_API_KEY", "") or ""
    if not api_key:
        return []

    today = datetime.now(timezone.utc).date()
    end = today + timedelta(days=days_ahead)
    events: list[dict[str, Any]] = []

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(
                "https://finnhub.io/api/v1/calendar/economic",
                params={
                    "from": today.isoformat(),
                    "to": end.isoformat(),
                    "token": api_key,
                },
            )
            if resp.status_code == 401:
                logger.warning("Finnhub calendar unauthorized — check FINNHUB_API_KEY")
                return []
            if resp.status_code == 403:
                logger.warning("Finnhub calendar forbidden — tier or key issue")
                return []
            resp.raise_for_status()
            data = resp.json()
            for item in data.get("economicCalendar", []):
                impact = (item.get("impact") or "").lower()
                if impact not in ("high", "medium"):
                    continue
                events.append({
                    "event_name": item.get("event", "Unknown"),
                    "event_date": item.get("time") or item.get("date"),
                    "country": item.get("country", "US"),
                    "impact": impact,
                    "actual": item.get("actual"),
                    "estimate": item.get("estimate"),
                    "previous": item.get("prev"),
                    "source": "finnhub",
                    "market_effect": _impact_to_score(impact, item.get("event", "")),
                    "confidence": 0.85 if impact == "high" else 0.65,
                    "tickers_affected": _default_tickers_for_event(item.get("event", "")),
                })
    except httpx.HTTPStatusError as exc:
        from app.utils.secret_redact import redact_secrets

        logger.warning(
            "Finnhub calendar HTTP error",
            status=exc.response.status_code,
            error=redact_secrets(str(exc)),
        )
    except Exception as exc:
        from app.utils.secret_redact import redact_secrets

        logger.warning("Finnhub calendar fetch failed", error=redact_secrets(str(exc)))

    return events


async def fetch_finnhub_earnings(
    days_ahead: int = 14,
) -> list[dict[str, Any]]:
    """Finnhub company earnings calendar — complements economic calendar in cockpit."""
    api_key = getattr(settings, "FINNHUB_API_KEY", "") or ""
    if not api_key:
        return []

    today = datetime.now(timezone.utc).date()
    end = today + timedelta(days=days_ahead)
    events: list[dict[str, Any]] = []

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.get(
                "https://finnhub.io/api/v1/calendar/earnings",
                params={
                    "from": today.isoformat(),
                    "to": end.isoformat(),
                    "token": api_key,
                },
            )
            if resp.status_code in (401, 403):
                logger.warning("Finnhub earnings calendar unauthorized/forbidden")
                return []
            resp.raise_for_status()
            data = resp.json()
            rows = data.get("earningsCalendar") if isinstance(data, dict) else None
            if not isinstance(rows, list):
                rows = data if isinstance(data, list) else []
            for item in rows:
                if not isinstance(item, dict):
                    continue
                sym = str(item.get("symbol") or "").strip().upper()
                if not sym:
                    continue
                when = item.get("date") or item.get("hour")
                events.append(
                    {
                        "event_name": f"{sym} earnings",
                        "event_date": when,
                        "country": "US",
                        "impact": "medium",
                        "actual": item.get("epsActual"),
                        "estimate": item.get("epsEstimate"),
                        "previous": item.get("revenueActual"),
                        "source": "finnhub_earnings",
                        "tickers_affected": [sym],
                    }
                )
    except httpx.HTTPStatusError as exc:
        from app.utils.secret_redact import redact_secrets

        logger.warning(
            "Finnhub earnings HTTP error",
            status=exc.response.status_code,
            error=redact_secrets(str(exc)),
        )
    except Exception as exc:
        from app.utils.secret_redact import redact_secrets

        logger.warning("Finnhub earnings fetch failed", error=redact_secrets(str(exc)))

    return events


def _impact_to_score(impact: str, event_name: str) -> float:
    base = 0.5 if impact == "high" else 0.25
    name_lower = event_name.lower()
    for kw, score in MACRO_KEYWORDS.items():
        if kw in name_lower:
            return score
    return base


def _default_tickers_for_event(event_name: str) -> list[str]:
    name = event_name.lower()
    if any(k in name for k in ("oil", "opec", "energy")):
        return ["XLE", "USO", "CVX"]
    if any(k in name for k in ("rate", "fed", "fomc", "cpi", "inflation")):
        return ["SPY", "TLT", "GLD", "QQQ"]
    if "gdp" in name or "payroll" in name or "employment" in name:
        return ["SPY", "DIA", "IWM"]
    return ["SPY", "QQQ"]


async def extract_macro_from_news(
    session: AsyncSession,
    lookback_hours: int = 48,
) -> list[dict[str, Any]]:
    """Derive macro events from recent news articles with extracted events."""
    from app.db.models import NewsArticle

    since = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    result = await session.execute(
        select(NewsArticle)
        .where(NewsArticle.published_at >= since)
        .order_by(NewsArticle.published_at.desc())
        .limit(100)
    )
    articles = result.scalars().all()
    events: list[dict[str, Any]] = []

    for article in articles:
        text = f"{article.title} {article.description or ''}".lower()
        matched_score = 0.0
        matched_kw = ""
        for kw, score in MACRO_KEYWORDS.items():
            if kw in text and abs(score) > abs(matched_score):
                matched_score = score
                matched_kw = kw

        if matched_kw:
            events.append({
                "event_name": f"News: {matched_kw.title()}",
                "event_date": article.published_at.isoformat(),
                "country": "GLOBAL",
                "impact": "high" if abs(matched_score) >= 0.6 else "medium",
                "source": article.source,
                "source_url": article.url,
                "market_effect": matched_score,
                "confidence": min(0.9, 0.5 + abs(matched_score) * 0.3),
                "tickers_affected": article.tickers_mentioned or ["SPY"],
                "article_id": article.id,
            })

        for ev in article.extracted_events or []:
            if isinstance(ev, dict) and ev.get("event_type") in (
                "rate_decision", "cpi", "gdp", "sanctions", "tariffs", "earnings", "geopolitical"
            ):
                events.append({
                    "event_name": ev.get("description", ev.get("event_type", "event")),
                    "event_date": ev.get("date") or article.published_at.isoformat(),
                    "country": ev.get("country", "GLOBAL"),
                    "impact": "high",
                    "source": article.source,
                    "source_url": article.url,
                    "market_effect": float(ev.get("market_effect", 0.0)),
                    "confidence": float(ev.get("confidence", 0.6)),
                    "tickers_affected": ev.get("tickers", article.tickers_mentioned or []),
                    "article_id": article.id,
                })

    return events


async def fetch_investing_events() -> list[dict[str, Any]]:
    """Fetch economic + earnings events from Investing.com (RapidAPI), if configured."""
    try:
        from app.services.data import investing_rapidapi

        if not investing_rapidapi.is_configured():
            return []
        intel = await investing_rapidapi.fetch_market_intelligence()
        return list(intel.get("events", [])) + list(intel.get("earnings", []))
    except Exception as exc:  # noqa: BLE001 - never break macro on provider error
        logger.warning("Investing.com event fetch failed", error=str(exc))
        return []


async def fetch_and_store_macro_events(
    session: AsyncSession,
) -> list[dict[str, Any]]:
    """Fetch macro events from all sources and persist to DB."""
    from app.db.models import MacroEvent

    finnhub_events = await fetch_finnhub_calendar()
    investing_events = await fetch_investing_events()
    news_events = await extract_macro_from_news(session)
    all_events = finnhub_events + investing_events + news_events

    stored: list[dict[str, Any]] = []
    for ev in all_events:
        macro = MacroEvent(
            event_name=ev["event_name"],
            event_date=_parse_dt(ev.get("event_date")),
            country=ev.get("country", "US"),
            impact=ev.get("impact", "medium"),
            source=ev.get("source", "system"),
            source_url=ev.get("source_url"),
            market_effect=float(ev.get("market_effect", 0.0)),
            confidence=float(ev.get("confidence", 0.5)),
            tickers_affected=ev.get("tickers_affected", []),
            raw_data=ev,
        )
        session.add(macro)
        stored.append(ev)

    if stored:
        await session.commit()
        logger.info("Macro events stored", count=len(stored))

    return stored


def compute_macro_score(events: list[dict[str, Any]]) -> float:
    """
    Aggregate macro events into a single score in [-1, 1].
    Weighted by confidence and recency.
    """
    if not events:
        return 0.0

    now = datetime.now(timezone.utc)
    total_weight = 0.0
    weighted_sum = 0.0

    for ev in events:
        effect = float(ev.get("market_effect", 0.0))
        conf = float(ev.get("confidence", 0.5))
        event_dt = _parse_dt(ev.get("event_date"))
        age_hours = max(0.0, (now - event_dt).total_seconds() / 3600)
        recency = max(0.1, 1.0 - age_hours / 168)  # decay over 1 week
        weight = conf * recency
        weighted_sum += effect * weight
        total_weight += weight

    if total_weight == 0:
        return 0.0
    return max(-1.0, min(1.0, weighted_sum / total_weight))


async def maybe_refresh_macro_events(session: AsyncSession) -> list[dict[str, Any]]:
    """Refresh macro calendars when cache TTL expired (or always when TTL=0)."""
    from app.core.config import settings
    from app.db.models import MacroEvent

    ttl_min = int(settings.PIPELINE_MACRO_REFRESH_TTL_MINUTES)
    if not settings.PIPELINE_SKIP_MACRO_REFRESH and ttl_min > 0:
        from sqlalchemy import func

        result = await session.execute(select(func.max(MacroEvent.created_at)))
        last_refresh = result.scalar_one_or_none()
        if last_refresh is not None:
            if last_refresh.tzinfo is None:
                last_refresh = last_refresh.replace(tzinfo=timezone.utc)
            age_min = (datetime.now(timezone.utc) - last_refresh).total_seconds() / 60.0
            if age_min < ttl_min:
                logger.debug(
                    "Macro refresh skipped — cache fresh",
                    age_minutes=round(age_min, 1),
                    ttl_minutes=ttl_min,
                )
                return []

    if settings.PIPELINE_SKIP_MACRO_REFRESH:
        return []

    return await fetch_and_store_macro_events(session)


async def get_macro_score(
    session: AsyncSession | None = None,
    lookback_hours: int = 72,
    *,
    live_calendar: bool = True,
) -> tuple[float, list[dict[str, Any]]]:
    """
    Return (macro_score, events) for pipeline consumption.

    When ``live_calendar=False`` (after a fresh DB refresh), skip redundant
    Finnhub/Investing round-trips and read from DB + news-derived events only.
    """
    events: list[dict[str, Any]] = []

    if live_calendar:
        events.extend(await fetch_finnhub_calendar())
        events.extend(await fetch_investing_events())

    if session:
        from app.db.models import MacroEvent

        since = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
        result = await session.execute(
            select(MacroEvent)
            .where(MacroEvent.event_date >= since)
            .order_by(MacroEvent.event_date.desc())
            .limit(50)
        )
        for row in result.scalars().all():
            events.append({
                "event_name": row.event_name,
                "event_date": row.event_date.isoformat(),
                "market_effect": row.market_effect,
                "confidence": row.confidence,
                "tickers_affected": row.tickers_affected,
                "source": row.source,
            })

        news_derived = await extract_macro_from_news(session, lookback_hours)
        events.extend(news_derived)

    score = compute_macro_score(events)
    return score, events


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(timezone.utc)
