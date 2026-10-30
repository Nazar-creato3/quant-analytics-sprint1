"""Pure transformer functions for macro normalization (Prompt 43)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable

from app.services.macro_registry.types import InternalObservation, NormalizedObservation


def _confidence_for_revision(revision: int) -> float:
    """Preliminary releases get lower confidence (Prompt 48)."""
    if revision <= 0:
        return 0.65
    if revision == 1:
        return 0.80
    return 0.92


def transform_fred_level(
    obs: InternalObservation,
    *,
    source_id: str,
    raw_payload_hash: str,
) -> NormalizedObservation:
    return NormalizedObservation(
        instrument=obs.instrument,
        source_id=source_id,
        value=obs.value,
        currency=obs.currency,
        unit=obs.unit,
        release_time=_ensure_utc(obs.release_time),
        observation_time=_ensure_utc(obs.observation_time),
        period=obs.period,
        revision=obs.revision,
        confidence=_confidence_for_revision(obs.revision),
        raw_payload_hash=raw_payload_hash,
    )


def transform_fred_cpi_yoy(
    observations: list[InternalObservation],
    *,
    source_id: str,
    raw_payload_hash: str,
) -> list[NormalizedObservation]:
    """Convert CPI index levels to YoY % change."""
    sorted_obs = sorted(observations, key=lambda o: o.observation_time)
    normalized: list[NormalizedObservation] = []
    index_by_period: dict[str, float] = {}
    for obs in sorted_obs:
        index_by_period[obs.period] = obs.value
        year, month = obs.period.split("-")
        prior_key = f"{int(year) - 1}-{month}"
        prior = index_by_period.get(prior_key)
        if prior is None or prior <= 0:
            continue
        yoy = (obs.value / prior - 1.0) * 100.0
        normalized.append(
            NormalizedObservation(
                instrument=obs.instrument,
                source_id=source_id,
                value=round(yoy, 4),
                currency=None,
                unit="%",
                release_time=_ensure_utc(obs.release_time),
                observation_time=_ensure_utc(obs.observation_time),
                period=obs.period,
                revision=obs.revision,
                confidence=_confidence_for_revision(obs.revision),
                raw_payload_hash=raw_payload_hash,
            )
        )
    return normalized


def transform_cbr_key_rate(
    obs: InternalObservation,
    *,
    source_id: str,
    raw_payload_hash: str,
) -> NormalizedObservation:
    return NormalizedObservation(
        instrument=obs.instrument,
        source_id=source_id,
        value=obs.value,
        currency="RUB",
        unit="%",
        release_time=_ensure_utc(obs.release_time),
        observation_time=_ensure_utc(obs.observation_time),
        period=obs.period,
        revision=obs.revision,
        confidence=_confidence_for_revision(obs.revision),
        raw_payload_hash=raw_payload_hash,
    )


def transform_yfinance_close(
    obs: InternalObservation,
    *,
    source_id: str,
    raw_payload_hash: str,
) -> NormalizedObservation:
    return NormalizedObservation(
        instrument=obs.instrument,
        source_id=source_id,
        value=obs.value,
        currency="USD",
        unit="USD/barrel",
        release_time=_ensure_utc(obs.release_time),
        observation_time=_ensure_utc(obs.observation_time),
        period=obs.period,
        revision=obs.revision,
        confidence=0.75,
        raw_payload_hash=raw_payload_hash,
    )


def transform_boc_key_rate(
    obs: InternalObservation,
    *,
    source_id: str,
    raw_payload_hash: str,
) -> NormalizedObservation:
    return NormalizedObservation(
        instrument=obs.instrument,
        source_id=source_id,
        value=obs.value,
        currency="CAD",
        unit="%",
        release_time=_ensure_utc(obs.release_time),
        observation_time=_ensure_utc(obs.observation_time),
        period=obs.period,
        revision=obs.revision,
        confidence=_confidence_for_revision(obs.revision),
        raw_payload_hash=raw_payload_hash,
    )


def transform_world_bank_level(
    obs: InternalObservation,
    *,
    source_id: str,
    raw_payload_hash: str,
) -> NormalizedObservation:
    return transform_fred_level(
        obs,
        source_id=source_id,
        raw_payload_hash=raw_payload_hash,
    )


def transform_eia_level(
    obs: InternalObservation,
    *,
    source_id: str,
    raw_payload_hash: str,
) -> NormalizedObservation:
    return transform_fred_level(
        obs,
        source_id=source_id,
        raw_payload_hash=raw_payload_hash,
    )


def transform_eurostat_level(
    obs: InternalObservation,
    *,
    source_id: str,
    raw_payload_hash: str,
) -> NormalizedObservation:
    return transform_fred_level(
        obs,
        source_id=source_id,
        raw_payload_hash=raw_payload_hash,
    )


def transform_calendar(*args, **kwargs) -> NormalizedObservation:
    raise NotImplementedError("Calendar entries use MacroCalendarAdapter.parse_calendar")


TRANSFORMER_REGISTRY: dict[str, Callable[..., NormalizedObservation | list[NormalizedObservation]]] = {
    "transform_fred_level": transform_fred_level,
    "transform_fred_cpi_yoy": transform_fred_cpi_yoy,
    "transform_cbr_key_rate": transform_cbr_key_rate,
    "transform_boc_key_rate": transform_boc_key_rate,
    "transform_yfinance_close": transform_yfinance_close,
    "transform_world_bank_level": transform_world_bank_level,
    "transform_eia_level": transform_eia_level,
    "transform_eurostat_level": transform_eurostat_level,
    "transform_calendar": transform_calendar,
}


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
