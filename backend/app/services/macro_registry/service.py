"""Macro Registry orchestration service."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.domain.macro_registry import (
    MacroCalendarEntryORM,
    MacroSourceRegistryORM,
)
from app.domain.market_data import MacroIndicatorORM
from app.services.macro_registry.adapters.base import compute_payload_hash
from app.services.macro_registry.adapters.calendar import MacroCalendarAdapter
from app.services.macro_registry.adapters.central_bank import CentralBankAdapter
from app.services.macro_registry.adapters.eia_bulk import EiaBulkAdapter
from app.services.macro_registry.adapters.energy import EnergyAdapter
from app.services.macro_registry.adapters.statistics import MacroStatisticsAdapter
from app.services.macro_registry.adapters.eurostat_bulk import EurostatBulkAdapter
from app.services.macro_registry.adapters.world_bank import WorldBankAdapter
from app.services.macro_registry.normalization import NormalizationLayer
from app.services.macro_registry.quality_gate import QualityGate, cron_to_refresh_hours
from app.services.macro_registry.seed import INSTRUMENT_TO_LEGACY_CODE, MACRO_SOURCE_SEED, seed_timestamp
from app.services.macro_registry.storage import MacroStorageLayer
from app.services.macro_registry.types import MacroSourceConfig, NormalizedObservation

logger = get_logger(__name__)

MACRO_SNAPSHOT_CACHE_KEY = "macro:snapshot:global"
MACRO_SNAPSHOT_CACHE_TTL_SECONDS = 120

CATEGORY_ADAPTERS = {
    "rate": CentralBankAdapter,
    "credit": CentralBankAdapter,
    "inflation": MacroStatisticsAdapter,
    "employment": MacroStatisticsAdapter,
    "fx": MacroStatisticsAdapter,
    "volatility_index": MacroStatisticsAdapter,
    "energy": EnergyAdapter,
    "commodity": EnergyAdapter,
    "calendar": MacroCalendarAdapter,
    "global": WorldBankAdapter,
    "regional": EurostatBulkAdapter,
}


def _config_from_orm(row: MacroSourceRegistryORM) -> MacroSourceConfig:
    return MacroSourceConfig(
        source_id=row.source_id,
        category=row.category,
        symbol=row.symbol,
        endpoint=row.endpoint,
        refresh_interval=row.refresh_interval,
        priority=row.priority,
        is_free=row.is_free,
        fallback_source=row.fallback_source,
        transformer=row.transformer,
        is_active=row.is_active,
    )


def _order_macro_seed_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {row["source_id"]: row for row in rows}
    ordered: list[dict[str, Any]] = []
    seen: set[str] = set()

    def visit(source_id: str) -> None:
        if source_id in seen:
            return
        row = by_id.get(source_id)
        if row is None:
            return
        fallback = row.get("fallback_source")
        if fallback:
            visit(str(fallback))
        seen.add(source_id)
        ordered.append(row)

    for row in rows:
        visit(row["source_id"])
    return ordered


class MacroRegistryService:
    """CRUD + ingestion pipeline for macro registry."""

    def __init__(self) -> None:
        self.normalization = NormalizationLayer()
        self.quality_gate = QualityGate()
        self.storage = MacroStorageLayer(self.quality_gate)

    async def seed_registry(self, session: AsyncSession) -> int:
        now = seed_timestamp()
        count = 0
        for row in _order_macro_seed_rows(MACRO_SOURCE_SEED):
            stmt = (
                insert(MacroSourceRegistryORM)
                .values(
                    **row,
                    is_active=True,
                    created_at=now,
                    updated_at=now,
                )
                .on_conflict_do_update(
                    index_elements=["source_id"],
                    set_={
                        "category": row["category"],
                        "symbol": row["symbol"],
                        "endpoint": row["endpoint"],
                        "refresh_interval": row["refresh_interval"],
                        "priority": row["priority"],
                        "is_free": row["is_free"],
                        "fallback_source": row["fallback_source"],
                        "transformer": row["transformer"],
                        "updated_at": now,
                    },
                )
            )
            await session.execute(stmt)
            count += 1
        await session.commit()
        return count

    async def list_sources(self, session: AsyncSession) -> list[MacroSourceRegistryORM]:
        return list((await session.execute(select(MacroSourceRegistryORM))).scalars().all())

    async def get_source(self, session: AsyncSession, source_id: str) -> MacroSourceRegistryORM | None:
        return (
            await session.execute(
                select(MacroSourceRegistryORM).where(MacroSourceRegistryORM.source_id == source_id)
            )
        ).scalar_one_or_none()

    async def create_source(self, session: AsyncSession, data: dict[str, Any]) -> MacroSourceRegistryORM:
        now = seed_timestamp()
        row = MacroSourceRegistryORM(**data, created_at=now, updated_at=now)
        session.add(row)
        await session.commit()
        await session.refresh(row)
        return row

    async def update_source(
        self,
        session: AsyncSession,
        source_id: str,
        data: dict[str, Any],
    ) -> MacroSourceRegistryORM | None:
        row = await self.get_source(session, source_id)
        if row is None:
            return None
        for key, value in data.items():
            if hasattr(row, key) and value is not None:
                setattr(row, key, value)
        row.updated_at = seed_timestamp()
        await session.commit()
        await session.refresh(row)
        return row

    async def delete_source(self, session: AsyncSession, source_id: str) -> bool:
        row = await self.get_source(session, source_id)
        if row is None:
            return False
        await session.delete(row)
        await session.commit()
        return True

    def resolve_adapter(self, config: MacroSourceConfig):
        if config.endpoint.startswith("adapter:eia") or config.endpoint.startswith("adapter:eia_bulk"):
            return EiaBulkAdapter(config)
        if config.endpoint.startswith("adapter:eurostat"):
            return EurostatBulkAdapter(config)
        adapter_cls = CATEGORY_ADAPTERS.get(config.category)
        if adapter_cls is None:
            raise ValueError(f"No adapter for category {config.category}")
        return adapter_cls(config)

    async def refresh_source(self, session: AsyncSession, source_id: str) -> dict[str, Any]:
        row = await self.get_source(session, source_id)
        if row is None:
            raise ValueError(f"Unknown source_id: {source_id}")
        config = _config_from_orm(row)
        adapter = self.resolve_adapter(config)

        async with httpx.AsyncClient() as client:
            raw = await adapter.fetch_with_retry(client)

        raw_id = await self.storage.store_raw_response(session, raw)
        if raw_id is None:
            await session.commit()
            return {"source_id": source_id, "deduplicated": True}

        observations = adapter.normalize(raw)
        normalized = self.normalization.transform_batch(
            transformer_name=config.transformer,
            source_id=config.source_id,
            observations=observations,
            raw_payload_hash=raw.payload_hash or compute_payload_hash(raw.payload),
        )

        prior_values = [
            float(v)
            for v in (
                await self._recent_values(session, config.symbol)
            )
        ]
        flags = self.quality_gate.evaluate_batch(
            normalized,
            refresh_interval_hours=cron_to_refresh_hours(config.refresh_interval),
            has_lineage=raw_id is not None,
            prior_values=prior_values,
        )
        from dataclasses import replace

        from app.services.macro_registry.reliability import apply_reliability_update

        batch_passed = all(self.quality_gate.is_passing(flag) for flag in flags.values())
        reliability = await apply_reliability_update(
            session,
            config.source_id,
            passed=batch_passed,
        )
        normalized = [
            replace(obs, confidence=round(obs.confidence * max(0.35, reliability), 4))
            for obs in normalized
        ]

        stored = await self.normalization.persist_observations(
            session,
            raw_response_id=raw_id,
            observations=normalized,
            quality_flags=flags,
        )

        for obs in normalized:
            flag = flags.get((obs.instrument, obs.observation_time), "ok")
            if self.quality_gate.is_passing(flag):
                await self.storage.upsert_series_history(
                    session,
                    instrument=obs.instrument,
                    period=obs.period,
                    value=obs.value,
                    quality_flag=flag,
                )

        row.last_successful_refresh = datetime.now(timezone.utc)
        await session.commit()
        return {"source_id": source_id, "raw_id": raw_id, "stored": stored}

    async def refresh_calendar(self, session: AsyncSession, source_id: str) -> dict[str, Any]:
        row = await self.get_source(session, source_id)
        if row is None:
            raise ValueError(f"Unknown source_id: {source_id}")
        config = _config_from_orm(row)
        adapter = MacroCalendarAdapter(config)
        async with httpx.AsyncClient() as client:
            raw = await adapter.fetch_with_retry(client)
        raw_id = await self.storage.store_raw_response(session, raw)
        entries = adapter.parse_calendar(raw)
        stored = 0
        now = datetime.now(timezone.utc)
        for entry in entries:
            stmt = (
                insert(MacroCalendarEntryORM)
                .values(
                    instrument=entry.instrument,
                    expected_release_time=entry.expected_release_time,
                    period_covered=entry.period_covered,
                    source_id=entry.source_id,
                    consensus_estimate=entry.consensus_estimate,
                    fetched_at=now,
                )
                .on_conflict_do_nothing(
                    constraint="macro_calendar_entries_instrument_release_source_key"
                )
            )
            result = await session.execute(stmt)
            stored += result.rowcount or 0
        row.last_successful_refresh = now
        await session.commit()
        return {"source_id": source_id, "raw_id": raw_id, "calendar_entries": stored}

    async def migrate_legacy_indicators(self, session: AsyncSession) -> int:
        """Migrate macro_indicators → macro_series_normalized with confidence=0.8."""
        await self.seed_registry(session)
        rows = list((await session.execute(select(MacroIndicatorORM))).scalars().all())
        if not rows:
            return 0

        migrated = 0
        for legacy in rows:
            instrument = _legacy_code_to_instrument(legacy.indicator_code)
            if instrument is None:
                continue
            source_id = _instrument_to_source(instrument)
            if source_id is None:
                continue

            payload = (
                f'{{"migrated_from":"macro_indicators","id":{legacy.id},'
                f'"value":"{legacy.value}"}}'
            )
            from app.services.macro_registry.types import RawResponse

            raw = RawResponse(
                source_id=source_id,
                payload=payload,
                content_type="application/json",
                http_status=200,
                fetched_at=legacy.published_at,
                payload_hash=compute_payload_hash(payload),
            )
            raw_id = await self.storage.store_raw_response(session, raw)
            if raw_id is None:
                continue

            from app.services.macro_registry.types import NormalizedObservation

            obs = NormalizedObservation(
                instrument=instrument,
                source_id=source_id,
                value=float(legacy.value),
                currency=None,
                unit="%",
                release_time=legacy.published_at,
                observation_time=legacy.published_at,
                period=legacy.published_at.strftime("%Y-%m"),
                revision=0,
                confidence=0.8,
                raw_payload_hash=raw.payload_hash,
            )
            await self.normalization.persist_observations(
                session,
                raw_response_id=raw_id,
                observations=[obs],
                quality_flags={(obs.instrument, obs.observation_time): "ok"},
            )
            migrated += 1
        await session.commit()
        return migrated

    async def _recent_values(self, session: AsyncSession, instrument: str) -> list[float]:
        from app.domain.macro_registry import MacroSeriesNormalizedORM

        stmt = (
            select(MacroSeriesNormalizedORM)
            .where(
                MacroSeriesNormalizedORM.instrument == instrument,
                MacroSeriesNormalizedORM.quality_flag == "ok",
            )
            .order_by(MacroSeriesNormalizedORM.observation_time.desc())
            .limit(5)
        )
        rows = list((await session.execute(stmt)).scalars().all())
        return [float(r.value) for r in rows]


async def load_macro_snapshot(session: AsyncSession) -> dict[str, float]:
    """Load latest passing normalized values mapped to legacy indicator codes."""
    bundle = await load_macro_snapshot_bundle(session)
    return bundle["indicators"]


async def load_macro_snapshot_bundle(session: AsyncSession) -> dict[str, Any]:
    """Load macro indicators with freshness metadata — cached globally (not per symbol)."""
    from app.utils.cache import cache_get, cache_set

    cached = await cache_get(MACRO_SNAPSHOT_CACHE_KEY)
    if isinstance(cached, dict) and cached.get("indicators"):
        return cached

    storage = MacroStorageLayer()
    gate = QualityGate()
    source_rows = list((await session.execute(select(MacroSourceRegistryORM))).scalars().all())
    refresh_by_source = {
        row.source_id: cron_to_refresh_hours(row.refresh_interval) for row in source_rows
    }
    now = datetime.now(timezone.utc)
    result: dict[str, float] = {}
    source_timestamps: dict[str, str] = {}
    stale_codes: list[str] = []

    for instrument, legacy_code in INSTRUMENT_TO_LEGACY_CODE.items():
        row = await storage.load_latest(session, instrument)
        if row is None:
            continue
        obs = NormalizedObservation(
            instrument=row.instrument,
            source_id=row.source_id,
            value=float(row.value),
            currency=row.currency,
            unit=row.unit,
            release_time=row.release_time,
            observation_time=row.observation_time,
            period=row.period,
            revision=row.revision,
            confidence=row.confidence,
            raw_payload_hash=row.raw_payload_hash,
        )
        refresh_hours = refresh_by_source.get(row.source_id, cron_to_refresh_hours("0 8 * * *"))
        flag = gate.evaluate_one(
            obs,
            refresh_interval_hours=refresh_hours,
            has_lineage=bool(row.raw_payload_hash),
            now=now,
            is_latest=True,
        )
        if gate.is_passing(flag):
            result[legacy_code] = float(row.value)
            ts = row.observation_time or row.release_time
            if ts is not None:
                source_timestamps[legacy_code] = ts.isoformat()
            if flag in {"stale", "delayed"}:
                stale_codes.append(legacy_code)

    if "hy_oas" in result and "gov_10y" in result:
        result["credit_spread"] = round(result["hy_oas"] / 100.0 - result["gov_10y"] / 100.0, 6)

    if not result:
        stmt = select(MacroIndicatorORM).order_by(MacroIndicatorORM.published_at.desc()).limit(50)
        rows = list((await session.execute(stmt)).scalars().all())
        for row in rows:
            if row.indicator_code not in result:
                result[row.indicator_code] = float(row.value)
                if row.published_at is not None:
                    source_timestamps[row.indicator_code] = row.published_at.isoformat()

    bundle = {
        "indicators": result,
        "loaded_at": now.isoformat(),
        "source_timestamps": source_timestamps,
        "cache_key": MACRO_SNAPSHOT_CACHE_KEY,
        "is_stale": bool(stale_codes),
        "stale_reason": (
            f"stale indicators: {', '.join(sorted(stale_codes))}" if stale_codes else ""
        ),
    }
    await cache_set(MACRO_SNAPSHOT_CACHE_KEY, bundle, ttl=MACRO_SNAPSHOT_CACHE_TTL_SECONDS)
    return bundle


def _legacy_code_to_instrument(code: str) -> str | None:
    for instrument, legacy in INSTRUMENT_TO_LEGACY_CODE.items():
        if legacy == code:
            return instrument
    return None


def _instrument_to_source(instrument: str) -> str | None:
    mapping = {
        "CBR_KEY_RATE": "cbr_key_rate",
        "FED_FUNDS_RATE": "fred_fedfunds",
        "US_CPI_YOY": "fred_cpi",
        "US_UNEMPLOYMENT": "fred_unrate",
        "DXY": "fred_dxy",
        "VIX": "fred_vix",
        "BRENT_OIL": "fred_brent",
        "HY_OAS": "fred_hy_spread",
        "GOV_10Y": "fred_gov_10y",
        "BOC_OVERNIGHT_RATE": "boc_overnight_rate",
        "CA_CPI_YOY": "fred_ca_cpi",
        "CA_UNEMPLOYMENT": "fred_ca_unemployment",
        "USDCAD": "fred_ca_usdcad",
        "CA_GOV_10Y": "fred_ca_gov_10y",
        "WTI_CANADA": "fred_ca_wti",
        "WTI_OIL": "eia_wti_spot",
        "NG_HENRY_HUB": "eia_ng_henry_hub",
        "WB_US_GDP_GROWTH": "wb_us_gdp_growth",
        "WB_CN_GDP_GROWTH": "wb_cn_gdp_growth",
        "WB_RU_GDP_GROWTH": "wb_ru_gdp_growth",
        "WB_WLD_GDP_GROWTH": "wb_world_gdp_growth",
        "WB_US_INFLATION": "wb_us_inflation",
        "WB_US_CURRENT_ACCOUNT": "wb_us_current_account",
        "EU_GDP_GROWTH": "eu_gdp_growth",
        "EU_GDP_YOY_Q": "eu_gdp_yoy_q",
        "EU_HICP_YOY": "eu_hicp_yoy",
        "EU_UNEMPLOYMENT": "eu_unemployment",
    }
    return mapping.get(instrument)


def _cron_to_hours(cron: str) -> float:
    return cron_to_refresh_hours(cron)
