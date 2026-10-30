"""Macro release calendar adapter (Prompt 49)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx

from app.services.macro.fomc_calendar import _FOMC_MEETING_STARTS
from app.services.macro_registry.adapters.base import IMacroAdapter, build_raw_response
from app.services.macro_registry.types import CalendarEntry, InternalObservation, RawResponse

# CBR board meeting dates (public schedule, 2025-2026).
_CBR_MEETING_DATES: tuple[str, ...] = (
    "2025-02-14",
    "2025-03-21",
    "2025-04-25",
    "2025-06-06",
    "2025-07-25",
    "2025-09-12",
    "2025-10-24",
    "2025-12-19",
    "2026-02-13",
    "2026-03-20",
    "2026-04-24",
    "2026-06-05",
    "2026-07-24",
    "2026-09-11",
    "2026-10-23",
    "2026-12-18",
)


class MacroCalendarAdapter(IMacroAdapter):
    """Fetch upcoming macro release schedules (not current values)."""

    async def fetch(self, client: httpx.AsyncClient) -> RawResponse:
        endpoint = self.config.endpoint
        if endpoint == "adapter:fomc_calendar":
            entries = self._build_fomc_entries()
        elif endpoint == "adapter:cbr_calendar":
            entries = self._build_cbr_entries()
        elif endpoint == "adapter:investing_calendar":
            entries = await self._build_investing_entries()
        else:
            raise ValueError(f"Unsupported calendar endpoint: {endpoint}")
        payload = json.dumps({"entries": [self._entry_to_dict(e) for e in entries]})
        return build_raw_response(self.config, payload)

    def normalize(self, raw: RawResponse) -> list[InternalObservation]:
        """Calendar adapter returns empty observations — use parse_calendar instead."""
        return []

    def parse_calendar(self, raw: RawResponse) -> list[CalendarEntry]:
        payload = json.loads(raw.payload)
        entries: list[CalendarEntry] = []
        for item in payload.get("entries", []):
            release_time = datetime.fromisoformat(item["expected_release_time"].replace("Z", "+00:00"))
            entries.append(
                CalendarEntry(
                    instrument=item["instrument"],
                    expected_release_time=release_time,
                    period_covered=item.get("period_covered"),
                    source_id=self.config.source_id,
                    consensus_estimate=item.get("consensus_estimate"),
                )
            )
        return entries

    def _build_fomc_entries(self) -> list[CalendarEntry]:
        now = datetime.now(timezone.utc)
        entries: list[CalendarEntry] = []
        for start in _FOMC_MEETING_STARTS:
            decision_at = datetime(start.year, start.month, start.day, 19, 0, tzinfo=timezone.utc)
            if decision_at <= now:
                continue
            entries.append(
                CalendarEntry(
                    instrument="FED_FUNDS_RATE",
                    expected_release_time=decision_at,
                    period_covered=start.strftime("%Y-%m"),
                    source_id=self.config.source_id,
                    consensus_estimate=None,
                )
            )
        return entries[:6]

    def _build_cbr_entries(self) -> list[CalendarEntry]:
        now = datetime.now(timezone.utc)
        entries: list[CalendarEntry] = []
        for date_str in _CBR_MEETING_DATES:
            parts = date_str.split("-")
            release_at = datetime(int(parts[0]), int(parts[1]), int(parts[2]), 10, 30, tzinfo=timezone.utc)
            if release_at <= now:
                continue
            entries.append(
                CalendarEntry(
                    instrument="CBR_KEY_RATE",
                    expected_release_time=release_at,
                    period_covered=date_str[:7],
                    source_id=self.config.source_id,
                    consensus_estimate=None,
                )
            )
        return entries[:6]

    async def _build_investing_entries(self) -> list[CalendarEntry]:
        from app.services.data import investing_rapidapi

        if not investing_rapidapi.is_configured():
            return []

        events = await investing_rapidapi.fetch_economic_events()
        now = datetime.now(timezone.utc)
        entries: list[CalendarEntry] = []
        for event in events:
            if event.get("impact") not in ("high", "medium"):
                continue
            release_time = _parse_event_datetime(event.get("event_date"))
            if release_time <= now:
                continue
            entries.append(
                CalendarEntry(
                    instrument=_instrument_for_event(str(event.get("event_name", ""))),
                    expected_release_time=release_time,
                    period_covered=release_time.strftime("%Y-%m"),
                    source_id=self.config.source_id,
                    consensus_estimate=_parse_float(event.get("estimate")),
                )
            )
        entries.sort(key=lambda e: e.expected_release_time)
        return entries[:20]

    @staticmethod
    def _entry_to_dict(entry: CalendarEntry) -> dict:
        return {
            "instrument": entry.instrument,
            "expected_release_time": entry.expected_release_time.isoformat(),
            "period_covered": entry.period_covered,
            "consensus_estimate": entry.consensus_estimate,
        }


def _instrument_for_event(event_name: str) -> str:
    name = event_name.lower()
    if any(k in name for k in ("cpi", "inflation", "pce")):
        return "US_CPI_YOY"
    if any(k in name for k in ("payroll", "nonfarm", "employment", "unemployment")):
        return "US_UNEMPLOYMENT"
    if any(k in name for k in ("fed", "fomc", "rate decision", "interest rate")):
        return "FED_FUNDS_RATE"
    if "gdp" in name:
        return "WB_US_GDP_GROWTH"
    return "INVESTING_ECON_CALENDAR"


def _parse_event_datetime(value: object) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _parse_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace("%", "").replace(",", ""))
    except (TypeError, ValueError):
        return None
