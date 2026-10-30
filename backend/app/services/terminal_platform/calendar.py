"""Terminal economic calendar — FMP primary, RapidAPI/free curated fallbacks."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from app.core.logging import get_logger
from app.services.terminal_platform.models import CalendarEvent, FetchResult

logger = get_logger(__name__)

# Public CBR board schedule (same source as macro_registry calendar adapter).
_CBR_MEETING_DATES: tuple[str, ...] = (
    "2026-09-11",
    "2026-10-23",
    "2026-12-18",
    "2027-02-12",
    "2027-03-19",
    "2027-04-23",
    "2027-06-11",
    "2027-07-23",
    "2027-09-10",
    "2027-10-22",
    "2027-12-17",
)


def _importance(raw: Any) -> Optional[str]:
    text = str(raw or "").strip().lower()
    if not text:
        return None
    if text in {"3", "high"} or text.startswith("h"):
        return "high"
    if text in {"2", "medium"} or text.startswith("m"):
        return "medium"
    if text in {"1", "low"} or text.startswith("l"):
        return "low"
    return None


def _parse_when(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    if isinstance(value, str) and value.strip():
        text = value.strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(text[:19], fmt)
                return dt.replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return datetime.now(timezone.utc)


def _free_policy_calendar(limit: int = 40) -> list[CalendarEvent]:
    """FOMC + CBR curated free path when paid calendar APIs are unavailable."""
    from app.services.macro.fomc_calendar import _FOMC_MEETING_STARTS

    now = datetime.now(timezone.utc)
    events: list[CalendarEvent] = []
    for start in _FOMC_MEETING_STARTS:
        decision = datetime(start.year, start.month, start.day, 19, 0, tzinfo=timezone.utc) + timedelta(
            days=1
        )
        if decision <= now:
            continue
        events.append(
            CalendarEvent(
                id=f"fomc-{decision.date().isoformat()}",
                title="FOMC rate decision",
                when=decision,
                region="US",
                importance="high",
                expected=None,
                provider="fomc_calendar",
            )
        )
    for date_str in _CBR_MEETING_DATES:
        y, m, d = (int(x) for x in date_str.split("-"))
        # CBR decisions at 10:30 Moscow (UTC+3) → 07:30 UTC
        when = datetime(y, m, d, 7, 30, tzinfo=timezone.utc)
        if when <= now:
            continue
        events.append(
            CalendarEvent(
                id=f"cbr-{date_str}",
                title="CBR Board meeting",
                when=when,
                region="RU",
                importance="high",
                expected=None,
                provider="cbr_calendar",
            )
        )
    events.sort(key=lambda e: e.when)
    return events[:limit]


async def _from_fred(limit: int = 40) -> list[CalendarEvent]:
    """FRED release dates — free with FRED_API_KEY; no consensus/actual fields."""
    from app.core.config import settings

    api_key = (settings.FRED_API_KEY or "").strip()
    if not api_key:
        return []

    import httpx

    today = datetime.now(timezone.utc).date()
    end = today + timedelta(days=14)
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                "https://api.stlouisfed.org/fred/releases/dates",
                params={
                    "api_key": api_key,
                    "file_type": "json",
                    "realtime_start": today.isoformat(),
                    "realtime_end": end.isoformat(),
                    "order_by": "release_date",
                    "sort_order": "asc",
                    "limit": min(limit * 2, 200),
                },
            )
            if resp.status_code != 200:
                logger.warning("FRED calendar HTTP error", status=resp.status_code)
                return []
            data = resp.json()
    except Exception as exc:  # noqa: BLE001
        logger.warning("FRED calendar fetch failed", error=str(exc))
        return []

    rows = data.get("release_dates") if isinstance(data, dict) else []
    if not isinstance(rows, list):
        return []

    _HIGH_IMPACT = (
        "consumer price index",
        "employment situation",
        "gdp",
        "fomc",
        "producer price",
        "retail sales",
        "industrial production",
        "housing starts",
        "personal income",
        "trade balance",
    )
    now = datetime.now(timezone.utc)
    events: list[CalendarEvent] = []
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        title = str(row.get("release_name") or "").strip()
        if not title:
            continue
        when = _parse_when(row.get("date"))
        if when < now - timedelta(hours=6):
            continue
        lower = title.lower()
        importance = "high" if any(k in lower for k in _HIGH_IMPACT) else "medium"
        events.append(
            CalendarEvent(
                id=f"fred-{row.get('release_id', i)}-{when.date().isoformat()}",
                title=title,
                when=when,
                region="US",
                importance=importance,
                expected=None,
                actual=None,
                previous=None,
                provider="fred",
            )
        )
    events.sort(key=lambda e: e.when)
    return events[:limit]


def _value_present(value: Any) -> bool:
    if value is None:
        return False
    text = str(value).strip()
    return bool(text) and text.lower() not in {"—", "-", "n/a", "null", "none"}


def _calendar_value_score(events: list[CalendarEvent]) -> int:
    return sum(
        1
        for event in events
        if _value_present(event.actual)
        or _value_present(event.expected)
        or _value_present(event.previous)
    )


def _norm_calendar_title(title: str) -> str:
    return " ".join(title.lower().split())


def _merge_calendar_events(
    primary: list[CalendarEvent],
    enrich: list[CalendarEvent],
) -> list[CalendarEvent]:
    """Fill missing ACT/FCST/PREV on primary rows from richer fallback sources."""
    by_title: dict[str, CalendarEvent] = {}
    for event in enrich:
        key = _norm_calendar_title(event.title)
        prev = by_title.get(key)
        if prev is None or _calendar_value_score([event]) > _calendar_value_score([prev]):
            by_title[key] = event

    merged: list[CalendarEvent] = []
    for event in primary:
        donor = by_title.get(_norm_calendar_title(event.title))
        if donor is None:
            merged.append(event)
            continue
        merged.append(
            event.model_copy(
                update={
                    "actual": event.actual if _value_present(event.actual) else donor.actual,
                    "expected": event.expected if _value_present(event.expected) else donor.expected,
                    "previous": event.previous if _value_present(event.previous) else donor.previous,
                    "importance": event.importance or donor.importance,
                    "region": event.region or donor.region,
                }
            )
        )
    return merged


async def _from_finnhub(limit: int = 40) -> list[CalendarEvent]:
    """Finnhub economic calendar only (no per-ticker earnings).

    Root cause fix (2026-08): mixing ``fetch_finnhub_earnings`` into the terminal
    economic-calendar widget flooded the panel with obscure ``{TICKER} earnings``
    rows when FMP was plan-gated — looked like mock/placeholder data.
    Earnings stay in cockpit/macro paths via ``fetch_finnhub_earnings`` directly.
    """
    from app.services.macro.client import fetch_finnhub_calendar

    rows = await fetch_finnhub_calendar(days_ahead=14)
    if not rows:
        return []
    now = datetime.now(timezone.utc)
    events: list[CalendarEvent] = []
    for i, row in enumerate(rows):
        title = str(row.get("event_name") or "").strip()
        if not title:
            continue
        when = _parse_when(row.get("event_date"))
        if when < now - timedelta(hours=6):
            continue
        prev = row.get("previous")
        if prev is None:
            prev = row.get("prev")
        estimate = row.get("estimate")
        if estimate is None:
            estimate = row.get("forecast")
        events.append(
            CalendarEvent(
                id=f"finnhub-{i}-{when.isoformat()}-{title[:32]}",
                title=title,
                when=when,
                region=str(row.get("country") or "").upper() or None,
                importance=_importance(row.get("impact")),
                expected=None if estimate is None else str(estimate),
                actual=None if row.get("actual") is None else str(row.get("actual")),
                previous=None if prev is None else str(prev),
                provider="finnhub",
            )
        )
    events.sort(key=lambda e: e.when)
    return events[:limit]


async def _from_investing(limit: int = 40) -> list[CalendarEvent]:
    from app.services.data import investing_rapidapi

    if not investing_rapidapi.is_configured():
        return []
    rows = await investing_rapidapi.fetch_economic_events()
    now = datetime.now(timezone.utc)
    events: list[CalendarEvent] = []
    for i, row in enumerate(rows):
        title = str(row.get("event_name") or row.get("title") or "").strip()
        if not title:
            continue
        when = _parse_when(row.get("event_date"))
        if when < now - timedelta(hours=6):
            continue
        events.append(
            CalendarEvent(
                id=f"inv-{i}-{when.isoformat()}-{title[:32]}",
                title=title,
                when=when,
                region=str(row.get("country") or row.get("currency") or "").upper() or None,
                importance=_importance(row.get("impact")),
                expected=None if row.get("estimate") is None else str(row.get("estimate")),
                actual=None if row.get("actual") is None else str(row.get("actual")),
                previous=None if row.get("previous") is None else str(row.get("previous")),
                provider="investing_rapidapi",
                currency=str(row["currency"]) if row.get("currency") else None,
            )
        )
    events.sort(key=lambda e: e.when)
    return events[:limit]


async def fetch_terminal_calendar(
    *,
    from_date: Optional[date] = None,
    to_date: Optional[date] = None,
    limit: int = 40,
) -> FetchResult:
    """
    Resolve economic calendar with graceful degrade:
    1) FMP stable economic-calendar (may be plan-gated — 402)
    2) Finnhub economic calendar only (if FINNHUB_API_KEY valid)
    3) Investing.com RapidAPI (if RAPIDAPI_KEY + subscription)
    4) FRED release dates (event titles only — no ACT/FCST)
    5) Free FOMC + CBR curated schedule
    """
    attempts: list[str] = []
    candidates: list[tuple[str, list[CalendarEvent], dict[str, Any]]] = []

    try:
        from app.services.terminal_platform.factory import get_terminal_router

        fmp = get_terminal_router().get_provider("fmp")
        if fmp is not None and hasattr(fmp, "fetch_economic_calendar"):
            result = await fmp.fetch_economic_calendar(
                from_date=from_date,
                to_date=to_date,
                limit=limit,
            )
            if result.success and result.data:
                candidates.append(
                    (
                        "fmp",
                        list(result.data),
                        {**(result.metadata or {}), "source": "fmp"},
                    )
                )
            else:
                attempts.append(f"fmp:{result.error_code or result.error}")
        else:
            attempts.append("fmp:unavailable")
    except Exception as exc:  # noqa: BLE001
        attempts.append(f"fmp:exc:{exc}")
        logger.warning("terminal calendar FMP failed", error=str(exc))

    try:
        finnhub = await _from_finnhub(limit=limit)
        if finnhub:
            candidates.append(("finnhub", finnhub, {"source": "finnhub"}))
        else:
            attempts.append("finnhub:empty")
    except Exception as exc:  # noqa: BLE001
        attempts.append(f"finnhub:exc:{exc}")
        logger.warning("terminal calendar Finnhub failed", error=str(exc))

    try:
        investing = await _from_investing(limit=limit)
        if investing:
            candidates.append(("investing_rapidapi", investing, {"source": "investing_rapidapi"}))
        else:
            attempts.append("investing:empty")
    except Exception as exc:  # noqa: BLE001
        attempts.append(f"investing:exc:{exc}")
        logger.warning("terminal calendar Investing failed", error=str(exc))

    enrich_pool: list[CalendarEvent] = []
    for _name, events, _meta in candidates:
        enrich_pool.extend(events)

    if candidates:
        ranked = sorted(
            candidates,
            key=lambda row: (_calendar_value_score(row[1]), len(row[1])),
            reverse=True,
        )
        provider, events, meta = ranked[0]
        if _calendar_value_score(events) == 0 and len(ranked) > 1:
            for alt_provider, alt_events, _alt_meta in ranked[1:]:
                if _calendar_value_score(alt_events) > 0:
                    events = _merge_calendar_events(events, alt_events)
                    provider = f"{provider}+{alt_provider}"
                    break
        elif enrich_pool:
            events = _merge_calendar_events(events, enrich_pool)

        if _calendar_value_score(events) > 0 or events:
            return FetchResult(
                success=True,
                data=events[:limit],
                provider=provider,
                metadata={**meta, "fallback_tried": attempts, "value_rows": _calendar_value_score(events)},
            )
        attempts.append(f"{provider}:titles_only")

    try:
        fred = await _from_fred(limit=limit)
        if fred:
            return FetchResult(
                success=True,
                data=fred,
                provider="fred",
                metadata={
                    "source": "fred_releases",
                    "fallback_tried": attempts,
                    "note": "FRED release dates only — upgrade FMP/Finnhub for ACT/FCST/PREV",
                },
            )
        attempts.append("fred:empty")
    except Exception as exc:  # noqa: BLE001
        attempts.append(f"fred:exc:{exc}")
        logger.warning("terminal calendar FRED failed", error=str(exc))

    free = _free_policy_calendar(limit=limit)
    if free:
        return FetchResult(
            success=True,
            data=free,
            provider="free_policy_calendar",
            metadata={
                "source": "fomc+cbr",
                "fallback_tried": attempts,
                "note": "Curated FOMC/CBR only — no ACT/FCST/PREV without paid calendar API",
            },
        )

    return FetchResult(
        success=False,
        error="All calendar sources failed: " + "; ".join(attempts),
        error_code="ALL_FAILED",
        provider="router",
        metadata={"attempts": attempts},
    )
