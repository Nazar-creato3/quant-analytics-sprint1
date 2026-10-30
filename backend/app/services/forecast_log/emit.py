"""Non-blocking emit with local outbox fallback (Prompt 11A delivery)."""
from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.services.forecast_log.record import (
    emit_from_chat_payload,
    emit_from_forecast_out,
    emit_from_market_payload,
    record_emission,
)
from app.services.qa.feature_flags import is_enabled

logger = get_logger(__name__)


def enqueue_persist(row_id: int) -> None:
    """Celery persist is best-effort; memory+hash already committed."""
    if not is_enabled("qa_forecast_log"):
        return
    try:
        from app.tasks.forecast_log import persist_forecast_log_task

        persist_forecast_log_task.delay(row_id)
    except Exception as exc:
        logger.warning("forecast_log persist enqueue failed", error=str(exc)[:200], row_id=row_id)


def emit_forecast(out: Any, *, section: str = "forecast") -> None:
    row = emit_from_forecast_out(out, section=section)
    if row is not None:
        enqueue_persist(row.id)


def emit_chat(payload: dict[str, Any]) -> None:
    row = emit_from_chat_payload(payload)
    if row is not None:
        enqueue_persist(row.id)


def emit_market(payload: dict[str, Any]) -> None:
    row = emit_from_market_payload(payload)
    if row is not None:
        enqueue_persist(row.id)


def emit_bot_or_composer(
    *,
    ticker: str,
    direction: int,
    probability: str,
    section: str,
    model_id: str,
) -> None:
    row = record_emission(
        ticker=ticker,
        instrument_id=ticker,
        horizon_days=1,
        direction=direction,
        probability=probability,
        section=section,
        model_id=model_id,
        model_version="v1",
        issued_price_source="issued_spot_not_eod",
    )
    if row is not None:
        enqueue_persist(row.id)
