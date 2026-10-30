"""ExplainabilityLayer — human-readable decision explanations (Prompt 28)."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditLog
from app.domain.regime import RegimeHistoryORM
from app.services.control_fabric.audit_journal import ControlFabricAuditAction
from app.services.control_fabric.risk_types import PortfolioRiskAssessment, RiskMetricAssessment
from app.services.explainability.formatters import fmt_num, fmt_pct, fmt_pct_change, fmt_regime_label
from app.services.explainability.types import DecisionExplanation, InstrumentExplainabilitySnapshot
from app.services.factor.repository import FactorExposureRepository
from app.services.factor.types import FactorName
from app.services.forecast.engine import ForecastEngine, get_forecast_engine
from app.services.forecast.types import InstrumentForecast
from app.services.regime.types import RegimeScopeType


_APPROVAL_ACTION_PREFIX = "approval_policy."
_RISK_ACTIONS = frozenset(
    {
        ControlFabricAuditAction.RISK_GATE,
        "risk_gate",
    }
)
_APPROVAL_ACTIONS = frozenset(
    {
        ControlFabricAuditAction.APPROVAL_POLICY,
    }
)


class ExplainabilityLayer:
    """Generate grounded explanations from audit, regime, factor, forecast, and risk data."""

    def __init__(
        self,
        *,
        factor_repository: FactorExposureRepository | None = None,
        forecast_engine: ForecastEngine | None = None,
    ) -> None:
        self._factor_repository = factor_repository or FactorExposureRepository()
        self._forecast_engine = forecast_engine or get_forecast_engine()

    def explain_regime_transition(
        self,
        *,
        previous_regime: str | None,
        current_regime: str,
        confidence: float,
        features: Mapping[str, float] | None = None,
        prior_features: Mapping[str, float] | None = None,
        factor_r_squared_current: float | None = None,
        factor_r_squared_previous: float | None = None,
    ) -> tuple[str, dict[str, Any]]:
        """Explain a regime change with concrete numeric drivers."""
        metrics: dict[str, Any] = {
            "previous_regime": previous_regime,
            "current_regime": current_regime,
            "confidence": confidence,
        }
        current_label = fmt_regime_label(current_regime)

        if previous_regime is None or previous_regime == current_regime:
            text = (
                f"Режим {current_label} сохраняется с уверенностью {fmt_num(confidence, decimals=2)}."
            )
            if features:
                vol_ratio = features.get("vol_ratio")
                if vol_ratio is not None:
                    metrics["vol_ratio"] = vol_ratio
                    text += f" rolling_volatility_ratio={fmt_num(vol_ratio, decimals=2)}."
            return text, metrics

        previous_label = fmt_regime_label(previous_regime)
        parts = [
            f"Режим сменился с {previous_label} на {current_label} "
            f"(confidence={fmt_num(confidence, decimals=2)})."
        ]

        if features and prior_features:
            vol_ratio = float(features.get("vol_ratio", 0.0))
            prior_vol_ratio = float(prior_features.get("vol_ratio", vol_ratio))
            metrics["vol_ratio"] = vol_ratio
            metrics["prior_vol_ratio"] = prior_vol_ratio
            if prior_vol_ratio > 0 and vol_ratio != prior_vol_ratio:
                parts.append(
                    f" rolling_volatility выросла на {fmt_pct_change(prior_vol_ratio, vol_ratio)} "
                    f"({fmt_num(prior_vol_ratio, decimals=2)} → {fmt_num(vol_ratio, decimals=2)})."
                )

        if (
            factor_r_squared_current is not None
            and factor_r_squared_previous is not None
            and factor_r_squared_current != factor_r_squared_previous
        ):
            metrics["r_squared_current"] = factor_r_squared_current
            metrics["r_squared_previous"] = factor_r_squared_previous
            parts.append(
                f" r_squared факторной модели снизился с {fmt_num(factor_r_squared_previous, decimals=2)} "
                f"до {fmt_num(factor_r_squared_current, decimals=2)}."
            )

        return " ".join(parts), metrics

    def explain_factor_model(
        self,
        *,
        r_squared: float,
        prior_r_squared: float | None = None,
        betas: Mapping[str, float] | None = None,
    ) -> tuple[str, dict[str, Any]]:
        metrics: dict[str, Any] = {"r_squared": r_squared}
        if prior_r_squared is not None:
            metrics["prior_r_squared"] = prior_r_squared

        if r_squared < 0.35:
            quality = "низкое"
        elif r_squared < 0.55:
            quality = "умеренное"
        else:
            quality = "высокое"

        text = f"Факторная модель объясняет {fmt_pct(r_squared)} доходности ({quality} r_squared={fmt_num(r_squared, decimals=2)})."
        if prior_r_squared is not None and prior_r_squared != r_squared:
            direction = "снизился" if r_squared < prior_r_squared else "вырос"
            text += (
                f" r_squared {direction} с {fmt_num(prior_r_squared, decimals=2)} "
                f"до {fmt_num(r_squared, decimals=2)}."
            )

        if betas:
            dominant = max(betas.items(), key=lambda item: abs(item[1]))
            metrics["dominant_factor"] = dominant[0]
            metrics["dominant_beta"] = dominant[1]
            text += (
                f" Доминирующий фактор: {dominant[0].replace('_', ' ')} "
                f"(beta={fmt_num(dominant[1], decimals=2)})."
            )

        return text, metrics

    def explain_forecast(self, forecast: InstrumentForecast) -> tuple[str, dict[str, Any]]:
        metrics = {
            "dominant_regime": forecast.dominant_regime,
            "confidence": forecast.confidence,
            "composite_risk_score": forecast.composite_risk_score,
            "risk_flags": list(forecast.risk_flags),
            "signals": forecast.signals.as_dict(),
        }
        regime_label = fmt_regime_label(forecast.dominant_regime)
        parts = [
            f"ForecastEngine: доминирующий режим {regime_label} "
            f"(confidence={fmt_num(forecast.confidence, decimals=2)}, "
            f"composite_risk={fmt_num(forecast.composite_risk_score, decimals=2)})."
        ]
        if forecast.risk_flags:
            flags = ", ".join(flag.replace("_", " ") for flag in forecast.risk_flags)
            parts.append(f" risk_flags: {flags}.")
        top_factors = sorted(
            forecast.contributing_factors,
            key=lambda item: item.weight,
            reverse=True,
        )[:3]
        if top_factors:
            factor_bits = [
                f"{item.factor}={fmt_num(item.weight, decimals=2)}"
                for item in top_factors
            ]
            parts.append(f" Топ факторы: {', '.join(factor_bits)}.")
        return " ".join(parts), metrics

    def explain_risk_assessment(
        self,
        assessment: PortfolioRiskAssessment,
    ) -> tuple[str, dict[str, Any]]:
        metrics = assessment.to_dict()
        breached = assessment.breached
        if not breached:
            worst = max(
                (metric for metric in assessment.metrics),
                key=lambda item: item.value / max(item.threshold, 1e-9),
                default=None,
            )
            if worst is None and assessment.instrument_assessments:
                instrument_metrics = [
                    metric
                    for row in assessment.instrument_assessments
                    for metric in row.metrics
                ]
                worst = max(
                    instrument_metrics,
                    key=lambda item: item.value / max(item.threshold, 1e-9),
                    default=None,
                )
            if worst is None:
                return "RiskEngine: все метрики в пределах лимитов.", metrics
            text = (
                f"RiskEngine: лимиты не нарушены; ближайшая метрика {worst.name}="
                f"{fmt_num(worst.value, decimals=4)} при пороге {fmt_num(worst.threshold, decimals=4)} "
                f"({worst.scope})."
            )
            return text, metrics

        breach = breached[0]
        text = (
            f"RiskEngine заблокировал решение: {breach.name}="
            f"{fmt_num(breach.value, decimals=4)} превышает порог {fmt_num(breach.threshold, decimals=4)} "
            f"({breach.scope})."
        )
        if len(breached) > 1:
            text += f" Дополнительно превышены: {', '.join(item.name for item in breached[1:3])}."
        return text, metrics

    def explain_risk_metric(self, metric: RiskMetricAssessment) -> tuple[str, dict[str, Any]]:
        metrics = {
            "name": metric.name,
            "value": metric.value,
            "threshold": metric.threshold,
            "scope": metric.scope,
            "exceeded": metric.exceeded,
        }
        if metric.exceeded:
            text = (
                f"RiskEngine: {metric.name}={fmt_num(metric.value, decimals=4)} > "
                f"порог {fmt_num(metric.threshold, decimals=4)} ({metric.scope})."
            )
        else:
            text = (
                f"RiskEngine: {metric.name}={fmt_num(metric.value, decimals=4)} "
                f"в пределах порога {fmt_num(metric.threshold, decimals=4)} ({metric.scope})."
            )
        return text, metrics

    def explain_approval_decision(self, details: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
        state = str(details.get("policy_state", details.get("state", "unknown")))
        reason = str(details.get("reason", ""))
        risk_score = float(details.get("risk_score", 0.0))
        metrics = {
            "policy_state": state,
            "reason": reason,
            "risk_score": risk_score,
        }
        text = (
            f"ApprovalPolicyEngine: {state}; risk_score={fmt_num(risk_score, decimals=2)}. "
            f"Причина: {reason}"
        )
        return text, metrics

    def explain_audit_entry(
        self,
        entry: AuditLog,
        *,
        regime_context: Mapping[str, Any] | None = None,
    ) -> DecisionExplanation:
        details = entry.details or {}
        action = entry.action

        if action in _RISK_ACTIONS:
            text, metrics = self._explain_risk_gate_details(details)
            summary = details.get("outcome", "risk_gate")
            return DecisionExplanation(
                decision_type="risk_gate",
                summary=str(summary),
                text=text,
                timestamp=entry.timestamp,
                source_metrics=metrics,
            )

        if action in _APPROVAL_ACTIONS or action.startswith(_APPROVAL_ACTION_PREFIX):
            text, metrics = self.explain_approval_decision(details)
            if regime_context:
                metrics.update(regime_context)
            return DecisionExplanation(
                decision_type="approval_policy",
                summary=str(details.get("policy_state", action)),
                text=text,
                timestamp=entry.timestamp,
                source_metrics=metrics,
            )

        return DecisionExplanation(
            decision_type=action,
            summary=action,
            text=f"Действие {action}: {details.get('reason', entry.error or 'без детализации')}.",
            timestamp=entry.timestamp,
            source_metrics=dict(details),
        )

    def _explain_risk_gate_details(self, details: Mapping[str, Any]) -> tuple[str, dict[str, Any]]:
        metadata = details.get("metadata") or {}
        metrics = dict(metadata)
        metrics["outcome"] = details.get("outcome")
        metrics["allowed"] = details.get("allowed")

        risk_metric = metadata.get("risk_metric")
        if risk_metric is not None:
            value = float(metadata.get("risk_value", 0.0))
            threshold = float(metadata.get("risk_threshold", 0.0))
            scope = metadata.get("risk_scope", "portfolio")
            text = (
                f"RiskGate: {risk_metric}={fmt_num(value, decimals=4)} > "
                f"порог {fmt_num(threshold, decimals=4)} ({scope})."
            )
            return text, metrics

        reason = str(details.get("reason", metadata.get("reason", "risk gate decision")))
        allowed = details.get("allowed", metadata.get("allowed"))
        prefix = "RiskGate пропустил" if allowed else "RiskGate заблокировал"
        return f"{prefix}: {reason}.", metrics

    async def load_regime_history(
        self,
        session: AsyncSession,
        instrument_id: int,
        *,
        limit: int = 2,
    ) -> list[RegimeHistoryORM]:
        stmt = (
            select(RegimeHistoryORM)
            .where(
                RegimeHistoryORM.scope_type == RegimeScopeType.INSTRUMENT.value,
                RegimeHistoryORM.scope_id == str(instrument_id),
            )
            .order_by(desc(RegimeHistoryORM.time))
            .limit(limit)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def load_factor_snapshot(
        self,
        session: AsyncSession,
        instrument_id: int,
    ) -> tuple[float | None, float | None, dict[str, float]]:
        current_rows = await self._factor_repository.latest_exposures(session, instrument_id, limit=1)
        prior_rows = await self._factor_repository.latest_exposures(session, instrument_id, limit=2)
        if not current_rows:
            return None, None, {}

        current_r2 = float(current_rows[0].r_squared_of_model)
        prior_r2 = None
        if len(prior_rows) >= 2 and prior_rows[1].time != prior_rows[0].time:
            prior_r2 = float(prior_rows[1].r_squared_of_model)

        betas: dict[str, float] = {}
        latest_time = current_rows[0].time
        for row in current_rows:
            if row.time == latest_time:
                betas[row.factor_name.value] = row.beta
        return current_r2, prior_r2, betas

    async def explain_for_instrument(
        self,
        session: AsyncSession,
        instrument_id: int,
    ) -> InstrumentExplainabilitySnapshot:
        regime_rows = await self.load_regime_history(session, instrument_id, limit=2)
        current_regime = regime_rows[0] if regime_rows else None
        prior_regime = regime_rows[1] if len(regime_rows) > 1 else None

        r_squared, prior_r_squared, betas = await self.load_factor_snapshot(session, instrument_id)

        regime_explanation: str | None = None
        regime_metrics: dict[str, Any] = {}
        if current_regime is not None:
            prior_features = prior_regime.features if prior_regime else None
            regime_explanation, regime_metrics = self.explain_regime_transition(
                previous_regime=current_regime.previous_regime or (
                    prior_regime.dominant_regime if prior_regime else None
                ),
                current_regime=current_regime.dominant_regime,
                confidence=float(current_regime.confidence),
                features=current_regime.features,
                prior_features=prior_features,
                factor_r_squared_current=r_squared,
                factor_r_squared_previous=prior_r_squared,
            )

        factor_explanation: str | None = None
        factor_metrics: dict[str, Any] = {}
        if r_squared is not None:
            factor_explanation, factor_metrics = self.explain_factor_model(
                r_squared=r_squared,
                prior_r_squared=prior_r_squared,
                betas=betas,
            )

        forecast_explanation: str | None = None
        forecast_metrics: dict[str, Any] = {}
        forecast = await self._forecast_engine.forecast_instrument(session, instrument_id)
        if forecast is not None:
            forecast_explanation, forecast_metrics = self.explain_forecast(forecast)

        audit_entries = await self._load_audit_for_instrument(session, instrument_id)
        recent_decisions = [
            self.explain_audit_entry(entry, regime_context=regime_metrics)
            for entry in audit_entries[:5]
        ]

        risk_explanation: str | None = None
        risk_metrics: dict[str, Any] = {}
        for entry in audit_entries:
            metadata = (entry.details or {}).get("metadata") or {}
            assessment_payload = metadata.get("risk_assessment")
            if assessment_payload:
                assessment = _assessment_from_dict(assessment_payload, instrument_id)
                risk_explanation, risk_metrics = self.explain_risk_assessment(assessment)
                break

        headline = regime_explanation or factor_explanation or forecast_explanation or (
            "Недостаточно данных для объяснения текущего состояния."
        )

        return InstrumentExplainabilitySnapshot(
            instrument_id=instrument_id,
            headline=headline,
            regime_explanation=regime_explanation,
            factor_explanation=factor_explanation,
            forecast_explanation=forecast_explanation,
            risk_explanation=risk_explanation,
            recent_decisions=tuple(recent_decisions),
            source_metrics={
                "regime": regime_metrics,
                "factor": factor_metrics,
                "forecast": forecast_metrics,
                "risk": risk_metrics,
            },
        )

    async def explain_audit_log(
        self,
        session: AsyncSession,
        audit_log_id: str,
    ) -> DecisionExplanation | None:
        entry = await session.get(AuditLog, audit_log_id)
        if entry is None:
            return None
        instrument_id = _instrument_id_from_audit(entry)
        regime_context: dict[str, Any] | None = None
        if instrument_id is not None:
            snapshot = await self.explain_for_instrument(session, instrument_id)
            regime_context = snapshot.source_metrics.get("regime")
        return self.explain_audit_entry(entry, regime_context=regime_context)

    async def _load_audit_for_instrument(
        self,
        session: AsyncSession,
        instrument_id: int,
    ) -> list[AuditLog]:
        instrument_key = str(instrument_id)
        try:
            json_key = AuditLog.details["instrument_id"]
            json_filter = json_key.astext == instrument_key  # type: ignore[attr-defined]
            stmt = (
                select(AuditLog)
                .where(json_filter)
                .order_by(desc(AuditLog.timestamp))
                .limit(10)
            )
            result = await session.execute(stmt)
            rows = list(result.scalars().all())
            if rows:
                return rows
        except (AttributeError, TypeError, NotImplementedError):
            pass
        except Exception:
            pass

        stmt = (
            select(AuditLog)
            .where(AuditLog.resource_id == instrument_key)
            .order_by(desc(AuditLog.timestamp))
            .limit(10)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())


def _instrument_id_from_audit(entry: AuditLog) -> int | None:
    details = entry.details or {}
    raw = details.get("instrument_id")
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _assessment_from_dict(payload: Mapping[str, Any], instrument_id: int) -> PortfolioRiskAssessment:
    portfolio_metrics = tuple(
        RiskMetricAssessment(
            name=str(item["name"]),
            value=float(item["value"]),
            threshold=float(item["threshold"]),
            exceeded=bool(item["exceeded"]),
            scope=item["scope"],  # type: ignore[arg-type]
            metadata=dict(item.get("metadata") or {}),
        )
        for item in payload.get("portfolio_metrics", [])
    )
    from app.services.control_fabric.risk_types import InstrumentRiskAssessment

    instrument_metrics = payload.get("instrument_metrics") or {}
    assessments = []
    for key, metrics in instrument_metrics.items():
        assessments.append(
            InstrumentRiskAssessment(
                instrument_id=int(key),
                metrics=tuple(
                    RiskMetricAssessment(
                        name=str(item["name"]),
                        value=float(item["value"]),
                        threshold=float(item["threshold"]),
                        exceeded=bool(item["exceeded"]),
                        scope=item["scope"],  # type: ignore[arg-type]
                    )
                    for item in metrics
                ),
            )
        )
    if not assessments:
        assessments = [
            InstrumentRiskAssessment(instrument_id=instrument_id, metrics=()),
        ]
    return PortfolioRiskAssessment(metrics=portfolio_metrics, instrument_assessments=tuple(assessments))


_layer = ExplainabilityLayer()


def get_explainability_layer() -> ExplainabilityLayer:
    return _layer
