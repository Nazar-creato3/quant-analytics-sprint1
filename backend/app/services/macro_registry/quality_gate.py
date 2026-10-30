"""Quality gate for normalized macro observations (Prompt 44)."""
from __future__ import annotations

import math
import re
from datetime import datetime, timedelta, timezone
from typing import Sequence

from app.core.logging import get_logger
from app.services.macro_registry.types import NormalizedObservation, QualityFlag

logger = get_logger(__name__)

# Process-wide quality-gate failure counters for /macro/health.
_quality_gate_failure_counts: dict[str, int] = {}

DEFAULT_STALENESS_MULTIPLIER = 3.0
DEFAULT_OUTLIER_STD = 3.0
DEFAULT_OUTLIER_WINDOW = 5

# Approximate cadence when cron/period metadata is unavailable.
DAILY_REFRESH_HOURS = 24.0
WEEKLY_REFRESH_HOURS = 24.0 * 7
MONTHLY_REFRESH_HOURS = 24.0 * 35
QUARTERLY_REFRESH_HOURS = 24.0 * 92
ANNUAL_REFRESH_HOURS = 24.0 * 365
_QUARTER_PERIOD_RE = re.compile(r"^\d{4}-Q[1-4]$")
# Daily market series: allow through a long weekend (Fri obs still valid Mon/Sun).
DAILY_STALENESS_CALENDAR_DAYS = 5


class QualityGate:
    """Validate normalized observations before downstream consumption."""

    def __init__(
        self,
        *,
        staleness_multiplier: float = DEFAULT_STALENESS_MULTIPLIER,
        outlier_std: float = DEFAULT_OUTLIER_STD,
        outlier_window: int = DEFAULT_OUTLIER_WINDOW,
    ) -> None:
        self.staleness_multiplier = staleness_multiplier
        self.outlier_std = outlier_std
        self.outlier_window = outlier_window
        self._failure_counts: dict[str, int] = {}

    def evaluate_batch(
        self,
        observations: Sequence[NormalizedObservation],
        *,
        refresh_interval_hours: float = 24.0,
        has_lineage: bool = True,
        prior_values: Sequence[float] | None = None,
        now: datetime | None = None,
    ) -> dict[tuple[str, datetime], str]:
        ts = now or datetime.now(timezone.utc)
        flags: dict[tuple[str, datetime], str] = {}
        latest_by_instrument = _latest_observations(observations)
        for obs in observations:
            key = (obs.instrument, obs.observation_time)
            is_latest = latest_by_instrument.get(obs.instrument) == obs
            flag = self.evaluate_one(
                obs,
                refresh_interval_hours=refresh_interval_hours,
                has_lineage=has_lineage,
                prior_values=prior_values if is_latest else None,
                now=ts,
                is_latest=is_latest,
            )
            flags[key] = flag
            if flag in (QualityFlag.MISSING.value, QualityFlag.STALE.value):
                self._failure_counts[obs.source_id] = self._failure_counts.get(obs.source_id, 0) + 1
                _quality_gate_failure_counts[obs.source_id] = (
                    _quality_gate_failure_counts.get(obs.source_id, 0) + 1
                )
        self._maybe_alert_systematic_failure()
        return flags

    def evaluate_one(
        self,
        obs: NormalizedObservation,
        *,
        refresh_interval_hours: float = 24.0,
        has_lineage: bool = True,
        prior_values: Sequence[float] | None = None,
        now: datetime | None = None,
        is_latest: bool = True,
    ) -> str:
        ts = now or datetime.now(timezone.utc)

        if not has_lineage or not obs.raw_payload_hash:
            return QualityFlag.MISSING.value

        if obs.value is None or math.isnan(obs.value) or math.isinf(obs.value):
            return QualityFlag.MISSING.value

        release = _utc(obs.release_time)
        observation = _utc(obs.observation_time)
        if release > ts or observation > ts:
            return QualityFlag.MISSING.value

        # Historical rows remain valid stored history; only the latest point
        # drives snapshot freshness.
        if not is_latest:
            return QualityFlag.OK.value

        cadence_hours = infer_refresh_hours(obs.period, refresh_interval_hours=refresh_interval_hours)
        if cadence_hours <= DAILY_REFRESH_HOURS:
            max_age = timedelta(days=DAILY_STALENESS_CALENDAR_DAYS)
        else:
            max_age = timedelta(hours=cadence_hours * self.staleness_multiplier)
        if ts - observation > max_age:
            return QualityFlag.STALE.value

        if prior_values and len(prior_values) >= 2:
            mean = sum(prior_values) / len(prior_values)
            variance = sum((v - mean) ** 2 for v in prior_values) / len(prior_values)
            std = math.sqrt(variance) if variance > 0 else 0.0
            if std > 0 and abs(obs.value - mean) > self.outlier_std * std:
                return QualityFlag.SUSPECT.value

        return QualityFlag.OK.value

    def is_passing(self, quality_flag: str) -> bool:
        return quality_flag == QualityFlag.OK.value

    def _maybe_alert_systematic_failure(self, threshold: int = 3) -> None:
        for source_id, count in self._failure_counts.items():
            if count >= threshold:
                logger.error(
                    "macro_quality_gate_systematic_failure",
                    source_id=source_id,
                    failure_count=count,
                )
                self._emit_alert(source_id, count)

    def _emit_alert(self, source_id: str, count: int) -> None:
        """Integrate with generic webhook/Telegram alert transport."""
        import asyncio

        from app.services.event_risk.alerts import emit_quality_gate_alert

        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(
                    emit_quality_gate_alert(source_id=source_id, failure_count=count)
                )
            else:
                loop.run_until_complete(
                    emit_quality_gate_alert(source_id=source_id, failure_count=count)
                )
        except RuntimeError:
            asyncio.run(emit_quality_gate_alert(source_id=source_id, failure_count=count))
        except Exception:
            logger.warning("macro_source_quality_alert", source_id=source_id, failure_count=count)


def get_quality_gate_failure_counts() -> dict[str, int]:
    return dict(_quality_gate_failure_counts)


def infer_refresh_hours(period: str, *, refresh_interval_hours: float | None = None) -> float:
    """Infer expected series cadence from period format and source cron."""
    if _QUARTER_PERIOD_RE.match(period.strip()):
        return QUARTERLY_REFRESH_HOURS
    if period.strip().isdigit() and len(period.strip()) == 4:
        return ANNUAL_REFRESH_HOURS
    if len(period) == 7 and period[4] == "-":
        return MONTHLY_REFRESH_HOURS
    if len(period) == 10 and period[4] == "-" and period[7] == "-":
        return DAILY_REFRESH_HOURS
    if refresh_interval_hours is not None:
        if refresh_interval_hours <= DAILY_REFRESH_HOURS:
            return DAILY_REFRESH_HOURS
        if refresh_interval_hours >= MONTHLY_REFRESH_HOURS:
            return refresh_interval_hours
        return refresh_interval_hours
    return WEEKLY_REFRESH_HOURS


def cron_to_refresh_hours(cron: str) -> float:
    """Map macro_source_registry cron to expected refresh cadence in hours."""
    parts = cron.split()
    if len(parts) >= 5:
        day_of_month = parts[2]
        if day_of_month not in ("*", "1-5"):
            return MONTHLY_REFRESH_HOURS
    if "* * 1-5" in cron:
        return DAILY_REFRESH_HOURS
    if "* * *" in cron:
        return DAILY_REFRESH_HOURS
    return WEEKLY_REFRESH_HOURS


def _latest_observations(
    observations: Sequence[NormalizedObservation],
) -> dict[str, NormalizedObservation]:
    latest: dict[str, NormalizedObservation] = {}
    for obs in observations:
        current = latest.get(obs.instrument)
        if current is None or obs.observation_time > current.observation_time:
            latest[obs.instrument] = obs
    return latest


def _utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
