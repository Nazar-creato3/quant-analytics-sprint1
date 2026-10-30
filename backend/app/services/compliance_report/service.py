"""Assemble compliance PDF payload from DealIntent + explainability data."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog
from app.domain.deal_intent import DealIntentORM, DealIntentRead
from app.domain.instrument import InstrumentORM
from app.domain.profile import ProfileORM, ProfileRead
from app.domain.sleeve import SleeveORM
from app.services.compliance_report.types import ComplianceReportDocument
from app.services.explainability.layer import ExplainabilityLayer
from app.services.prediction_hierarchy.narrator import PredictionNarrator
from app.services.prediction_hierarchy.orchestrator import get_hierarchy_orchestrator


class ComplianceReportNotFoundError(LookupError):
    """Raised when DealIntent or related entities are missing."""


class ComplianceReportService:
    """Build compliance documentation for an approved or pending DealIntent."""

    def __init__(
        self,
        *,
        explainability: ExplainabilityLayer | None = None,
        narrator: PredictionNarrator | None = None,
    ) -> None:
        self._explainability = explainability or ExplainabilityLayer()
        self._narrator = narrator or PredictionNarrator()
        self._orchestrator = get_hierarchy_orchestrator()

    async def build_document(
        self,
        session: AsyncSession,
        deal_intent_id: str,
    ) -> ComplianceReportDocument:
        intent_row = await session.get(DealIntentORM, deal_intent_id)
        if intent_row is None:
            raise ComplianceReportNotFoundError(f"DealIntent {deal_intent_id} not found")

        intent = DealIntentRead.from_orm_row(intent_row)
        instrument = await session.get(InstrumentORM, intent.instrument_id)
        if instrument is None:
            raise ComplianceReportNotFoundError(
                f"Instrument {intent.instrument_id} not found for DealIntent"
            )

        sleeve = await session.get(SleeveORM, intent.sleeve_id)
        if sleeve is None:
            raise ComplianceReportNotFoundError(f"Sleeve {intent.sleeve_id} not found")

        profile_row = await session.get(ProfileORM, sleeve.profile_id)
        if profile_row is None:
            raise ComplianceReportNotFoundError(f"Profile for sleeve {intent.sleeve_id} not found")

        profile = ProfileRead.from_orm_row(profile_row)
        snapshot = await self._explainability.explain_for_instrument(
            session,
            intent.instrument_id,
        )

        sections: list[tuple[str, str]] = []
        if snapshot.regime_explanation:
            sections.append(("Режим рынка", snapshot.regime_explanation))
        if snapshot.factor_explanation:
            sections.append(("Факторная модель", snapshot.factor_explanation))
        if snapshot.forecast_explanation:
            sections.append(("Прогноз", snapshot.forecast_explanation))
        if snapshot.risk_explanation:
            sections.append(("Оценка риска", snapshot.risk_explanation))

        narrator_insights = tuple(
            decision.text for decision in snapshot.recent_decisions[:3]
        )
        try:
            forecast = await self._orchestrator.get_forecast(
                session,
                intent.instrument_id,
                symbol=instrument.symbol,
                include_narrative=True,
                use_cache=True,
            )
            narrator_phrases = tuple(i.text_ru for i in self._narrator.narrate(forecast)[:5])
            if narrator_phrases:
                narrator_insights = narrator_phrases
        except Exception:
            pass

        audit_reference = await self._latest_audit_reference(session, intent)

        return ComplianceReportDocument(
            report_id=str(uuid.uuid4()),
            generated_at=datetime.now(timezone.utc),
            deal_intent_id=intent.id,
            instrument_symbol=instrument.symbol,
            instrument_id=intent.instrument_id,
            direction=intent.direction.value,
            strategy=intent.strategy.value,
            status=intent.status.value,
            entry_reason=intent.entry_reason,
            target_price=_format_price(intent.target_price),
            risk_appetite=profile.risk_appetite.value,
            max_drawdown_pct=str(profile.max_drawdown_pct),
            jurisdiction=profile.jurisdiction.value,
            account_type=profile.account_type.value,
            explainability_headline=snapshot.headline,
            explainability_sections=tuple(sections),
            narrator_insights=narrator_insights,
            audit_reference=audit_reference,
        )

    async def _latest_audit_reference(
        self,
        session: AsyncSession,
        intent: DealIntentRead,
    ) -> str | None:
        stmt = (
            select(AuditLog)
            .where(AuditLog.action.contains("deal_intent"))
            .order_by(desc(AuditLog.timestamp))
            .limit(50)
        )
        result = await session.execute(stmt)
        for entry in result.scalars().all():
            details = entry.details or {}
            if details.get("deal_intent_id") == intent.id:
                return f"audit_log:{entry.id} @ {entry.timestamp.isoformat()}"
        entry = result.scalars().first()
        return f"audit_log:{entry.id} @ {entry.timestamp.isoformat()}" if entry else None


def _format_price(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value, "f")
