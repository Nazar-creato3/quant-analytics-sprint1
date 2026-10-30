"""Macro Registry CRUD + report API (Prompts 41-50)."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access_deps import require_ops_read
from app.core.deps import get_current_user_email, get_db
from app.core.logging import get_logger
from app.schemas.macro_registry import (
    MacroBlockOut,
    MacroHealthOut,
    MacroReportOut,
    MacroSeriesOut,
    MacroSourceCreate,
    MacroSourceOut,
    MacroSourceUpdate,
)
from app.services.macro_registry.quality_gate import get_quality_gate_failure_counts
from app.services.macro_registry.reliability import get_reliability_scores
from app.services.macro_registry.report_engine import MacroReportEngine
from app.services.macro_registry.scheduler import MacroRefreshScheduler
from app.services.macro_registry.seed import INSTRUMENT_TO_LEGACY_CODE
from app.services.macro_registry.service import MacroRegistryService, load_macro_snapshot
from app.services.macro_registry.storage import MacroStorageLayer

router = APIRouter(prefix="/macro", tags=["macro"])
logger = get_logger(__name__)

_service = MacroRegistryService()
_scheduler = MacroRefreshScheduler()
_report_engine = MacroReportEngine()


@router.get("/sources", response_model=list[MacroSourceOut])
async def list_macro_sources(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> list[MacroSourceOut]:
    rows = await _service.list_sources(db)
    return [MacroSourceOut.model_validate(r) for r in rows]


@router.post("/sources", response_model=MacroSourceOut, status_code=status.HTTP_201_CREATED)
async def create_macro_source(
    body: MacroSourceCreate,
    _: object = Depends(require_ops_read),
    db: AsyncSession = Depends(get_db),
) -> MacroSourceOut:
    row = await _service.create_source(db, body.model_dump())
    return MacroSourceOut.model_validate(row)


@router.get("/sources/{source_id}", response_model=MacroSourceOut)
async def get_macro_source(
    source_id: str,
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> MacroSourceOut:
    row = await _service.get_source(db, source_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return MacroSourceOut.model_validate(row)


@router.patch("/sources/{source_id}", response_model=MacroSourceOut)
async def update_macro_source(
    source_id: str,
    body: MacroSourceUpdate,
    _: object = Depends(require_ops_read),
    db: AsyncSession = Depends(get_db),
) -> MacroSourceOut:
    row = await _service.update_source(db, source_id, body.model_dump(exclude_unset=True))
    if row is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return MacroSourceOut.model_validate(row)


@router.delete("/sources/{source_id}")
async def delete_macro_source(
    source_id: str,
    _: object = Depends(require_ops_read),
    db: AsyncSession = Depends(get_db),
):
    deleted = await _service.delete_source(db, source_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Source not found")
    return {"deleted": True}


@router.post("/sources/seed")
async def seed_macro_sources(
    _: object = Depends(require_ops_read),
    db: AsyncSession = Depends(get_db),
) -> dict:
    count = await _service.seed_registry(db)
    migrated = await _service.migrate_legacy_indicators(db)
    return {"seeded": count, "migrated_legacy": migrated}


@router.post("/refresh/{source_id}")
async def refresh_macro_source(
    source_id: str,
    _: object = Depends(require_ops_read),
    db: AsyncSession = Depends(get_db),
) -> dict:
    row = await _service.get_source(db, source_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Source not found")
    try:
        if row.category == "calendar":
            result = await _service.refresh_calendar(db, source_id)
        else:
            result = await _service.refresh_source(db, source_id)
        _scheduler.record_refresh(source_id)
        return result
    except Exception as exc:
        logger.warning("macro_refresh_api_failed", source_id=source_id, error=str(exc))
        if row.fallback_source:
            try:
                fb = await _service.refresh_source(db, row.fallback_source)
                _scheduler.record_refresh(row.fallback_source)
                return {"fallback": fb, "primary_error": str(exc)}
            except Exception as fb_exc:
                raise HTTPException(status_code=503, detail=str(fb_exc)) from fb_exc
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/series/latest", response_model=list[MacroSeriesOut])
async def get_latest_macro_series(
    instrument: str | None = Query(None),
    instruments: str | None = Query(None, description="Comma-separated instrument ids"),
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> list[MacroSeriesOut]:
    storage = MacroStorageLayer()
    if instruments:
        wanted = [x.strip() for x in instruments.split(",") if x.strip()][:30]
    elif instrument:
        wanted = [instrument]
    else:
        wanted = list(INSTRUMENT_TO_LEGACY_CODE.keys())
    results: list[MacroSeriesOut] = []
    for inst in wanted:
        row = await storage.load_passing_latest(db, inst)
        if row is None:
            continue
        results.append(
            MacroSeriesOut(
                instrument=row.instrument,
                value=float(row.value),
                unit=row.unit,
                quality_flag=row.quality_flag,
                confidence=row.confidence,
                release_time=row.release_time,
                observation_time=row.observation_time,
                period=row.period,
                revision=row.revision,
                source_id=row.source_id,
            )
        )
    return results


@router.get("/report", response_model=MacroReportOut)
async def get_macro_report(
    mode: str = Query("daily", pattern="^(daily|weekly)$"),
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> MacroReportOut:
    report = await _report_engine.generate(db, mode=mode)
    return MacroReportOut(
        as_of=datetime.fromisoformat(report["as_of"].replace("Z", "+00:00")),
        mode=mode,
        report=report,
        markdown=report.get("markdown"),
        html=report.get("html"),
    )


@router.get("/block", response_model=MacroBlockOut)
async def get_macro_block(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> MacroBlockOut:
    """Macro block for forecast section."""
    indicators = await load_macro_snapshot(db)
    missing: list[str] = []
    required = ("vix", "cpi", "rate_cb", "dxy", "oil_brent", "unemployment")
    for key in required:
        if key not in indicators:
            missing.append(f"macro_series_normalized.{key}")

    canada_optional = ("rate_cb_ca", "cpi_ca", "unemployment_ca", "usdcad")
    for key in canada_optional:
        if key not in indicators:
            missing.append(f"macro_series_normalized.{key} (Canada — optional)")

    wb_optional = (
        "wb_world_gdp_growth",
        "wb_us_gdp_growth",
        "wb_cn_gdp_growth",
        "wb_ru_gdp_growth",
        "wb_us_inflation",
        "wb_us_current_account",
    )
    for key in wb_optional:
        if key not in indicators:
            missing.append(f"macro_series_normalized.{key} (World Bank — optional)")

    eu_optional = ("eu_gdp_growth", "eu_gdp_yoy_q", "eu_hicp_yoy", "eu_unemployment")
    for key in eu_optional:
        if key not in indicators:
            missing.append(f"macro_series_normalized.{key} (Eurostat — optional)")

    if "credit_spread" not in indicators:
        missing.append("credit_spread.hy_vs_gov (FRED HY OAS + 10Y Treasury)")

    report = await _report_engine.generate(db, mode="daily")
    return MacroBlockOut(
        indicators=indicators,
        report_mode="daily",
        missing_resources=missing,
        upcoming_releases=report.get("upcoming_releases", []),
        as_of=datetime.now(timezone.utc),
    )


@router.get("/health", response_model=MacroHealthOut)
async def macro_registry_health(
    email: str = Depends(get_current_user_email),
    db: AsyncSession = Depends(get_db),
) -> MacroHealthOut:
    rows = await _service.list_sources(db)
    now = datetime.now(timezone.utc)
    sources = []
    queue_lag: dict[str, float] = {}
    for r in rows:
        lag_seconds = 0.0
        if r.last_successful_refresh is not None:
            last = r.last_successful_refresh
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            lag_seconds = max(0.0, (now - last).total_seconds())
        queue_lag[r.source_id] = lag_seconds
        sources.append(
            {
                "source_id": r.source_id,
                "category": r.category,
                "symbol": r.symbol,
                "last_successful_refresh": (
                    r.last_successful_refresh.isoformat() if r.last_successful_refresh else None
                ),
                "is_active": r.is_active,
                "reliability_score": float(getattr(r, "reliability_score", 1.0) or 1.0),
            }
        )
    reliability = await get_reliability_scores(db)
    scheduler_lag = _scheduler.get_queue_lag_seconds()
    merged_lag = {**queue_lag, **scheduler_lag}
    failures = get_quality_gate_failure_counts()
    degraded = any(score < 0.6 for score in reliability.values()) or bool(failures)
    return MacroHealthOut(
        status="degraded" if degraded else ("ok" if rows else "empty"),
        sources=sources,
        last_refresh=_scheduler.get_refresh_status(),
        quality_gate_failures=failures,
        queue_lag_seconds=merged_lag,
        reliability_scores=reliability,
    )
