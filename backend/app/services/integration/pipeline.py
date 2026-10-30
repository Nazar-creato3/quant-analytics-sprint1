"""
ValidationPipeline — end-to-end DealIntent validation (no live trading).

Flow: Profile → Sleeve → StrategyMesh → ComplianceAccessLayer → SleeveEngine
      → RiskGate/AntiLossGuard → ApprovalPolicyEngine → PaperExecutor → AuditLog
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Sequence

from app.domain.deal_intent import DealIntentCreate, DealIntentRead, transition_deal_intent_status
from app.domain.deal_intent_enums import DealIntentDirection, DealIntentStatus
from app.domain.deal_intent_fsm import DealIntentEvent
from app.domain.enums import AssetCategory, Strategy
from app.domain.profile import ProfileRead
from app.domain.sleeve import SleeveRead
from app.services.approval.engine import evaluate_policy
from app.services.approval.models import MarketContext, PolicyState
from app.services.control_fabric.audit_journal import ControlFabricAuditAction
from app.services.control_fabric.replay_engine import ReplayEngine
from app.services.control_fabric.risk_gate import RiskGate, compute_atr
from app.services.control_fabric.types import ReplayIntentRecord, RiskSnapshot
from app.services.execution.adapter import OrderRequest, PaperExecutor
from app.services.execution.guard import DealIntentExecutionContext
from app.services.control_fabric.strategy_halt import check_strategy_halt_sync
from app.services.integration.historical_data import KNOWN_GAPS, rolling_indicators
from app.services.integration.marginal_risk_gate import DEFAULT_INTENT_DELTA_WEIGHT
from app.services.integration.stack import PredictionRiskStack
from app.services.integration.metrics import (
    build_equity_curve,
    compute_max_drawdown_pct,
    compute_sharpe_ratio,
    compute_win_rate,
)
from app.services.integration.report import CombinedValidationReport, ValidationReport
from app.services.integration.types import (
    AuditEntry,
    HistoricalBar,
    IntentGateOutcome,
    PaperTrade,
    VenueConfig,
)
from app.services.sleeve.engine import SleeveEngine
from app.services.sleeve.types import IntentRiskRequest
from app.services.strategy.mesh import StrategyMesh
from app.services.strategy.regime import CryptoRegimeAdapter, EquityRegimeAdapter
from app.services.strategy.types import InstrumentSnapshot, RawMarketSnapshot, SleeveStrategyContext


class ValidationPipeline:
    """In-memory validation orchestrator — paper execution only."""

    def __init__(
        self,
        profile: ProfileRead,
        sleeve: SleeveRead,
        *,
        mesh: StrategyMesh | None = None,
        sleeve_engine: SleeveEngine | None = None,
        risk_gate: RiskGate | None = None,
        replay_engine: ReplayEngine | None = None,
        prediction_stack: PredictionRiskStack | None = None,
        total_capital_usd: Decimal | float = 100_000,
    ) -> None:
        self.profile = profile
        self.sleeve = sleeve
        self.sleeve_engine = sleeve_engine or SleeveEngine(total_capital_usd=total_capital_usd)
        self.risk_gate = risk_gate or RiskGate()
        self.replay_engine = replay_engine or ReplayEngine(risk_gate=self.risk_gate)
        self.prediction_stack = prediction_stack or PredictionRiskStack()
        if mesh is not None:
            self.mesh = mesh
        else:
            default_mesh = StrategyMesh.default()
            self.mesh = StrategyMesh(
                default_mesh.registered.values(),
                sleeve_engine=self.sleeve_engine,
            )
        self.audit_entries: list[AuditEntry] = []

    def _audit(
        self,
        action: str,
        *,
        resource_id: str | None,
        success: bool,
        details: dict,
        error: str | None = None,
    ) -> None:
        self.audit_entries.append(
            AuditEntry(
                action=action,
                resource_id=resource_id,
                success=success,
                details=details,
                error=error,
            )
        )

    @staticmethod
    def _create_to_read(create: DealIntentCreate, *, status: DealIntentStatus) -> DealIntentRead:
        now = datetime.now(timezone.utc)
        payload = create.model_dump()
        payload["status"] = status
        return DealIntentRead(
            id=str(uuid.uuid4()),
            created_at=now,
            updated_at=now,
            **payload,
        )

    def _build_market_context(
        self,
        bars: Sequence[HistoricalBar],
        index: int,
        venue: VenueConfig,
    ):
        window = bars[max(0, index - 20) : index + 1]
        closes = [bar.close for bar in window]
        highs = [bar.high for bar in window]
        lows = [bar.low for bar in window]
        indicators = rolling_indicators(closes, highs, lows)

        instrument = InstrumentSnapshot(
            instrument_id=venue.instrument_id,
            symbol=venue.symbol,
            category=venue.category,
            last_price=Decimal(str(round(bars[index].close, 4))),
            volatility=indicators["volatility"],
            spread_bps=indicators["spread_bps"],
            momentum=indicators["momentum"],
            mean_reversion_z=indicators["mean_reversion_z"],
            breakout_strength=indicators["breakout_strength"],
        )
        sleeve_ctx = SleeveStrategyContext(
            sleeve_id=venue.sleeve_id,
            category=venue.category,
            instruments=(instrument,),
            risk_budget_remaining=self.sleeve.risk_budget,
        )
        raw = RawMarketSnapshot(
            instruments=(instrument,),
            session_active=True,
            bid_ask_imbalance=0.1,
            vix_level=20.0 if venue.category != AssetCategory.CRYPTO else None,
        )
        if venue.category == AssetCategory.CRYPTO:
            return CryptoRegimeAdapter().build_context(raw, sleeve_ctx)
        return EquityRegimeAdapter().build_context(raw, sleeve_ctx)

    def _market_context_for_gates(
        self,
        bars: Sequence[HistoricalBar],
        index: int,
        venue: VenueConfig,
    ) -> MarketContext:
        window = bars[max(0, index - 20) : index + 1]
        closes = [bar.close for bar in window]
        highs = [bar.high for bar in window]
        lows = [bar.low for bar in window]
        indicators = rolling_indicators(closes, highs, lows)
        atr = compute_atr(highs, lows, closes)

        return MarketContext(
            instrument_volatility=indicators["volatility"],
            instrument_spread_bps=indicators["spread_bps"],
            instrument_category=venue.category,
            max_correlation_with_portfolio=0.2,
            market_regime="range",
            profile_drawdown_pct=0.0,
            profile_daily_loss_abs=Decimal("0"),
            sleeve_status=self.sleeve.status,
            sleeve_risk_budget_remaining=self.sleeve.risk_budget,
        )

    async def _paper_execute(
        self,
        intent: DealIntentRead,
        fill_price: float,
    ) -> dict:
        executor = PaperExecutor()
        ctx = DealIntentExecutionContext(
            deal_intent_id=intent.id,
            status=DealIntentStatus.EXECUTING,
        )
        side = "buy" if intent.direction == DealIntentDirection.LONG else "sell"
        qty = 1.0
        result = await executor.submit_order(
            OrderRequest(
                ticker=venue_symbol(intent),
                side=side,
                qty=qty,
                order_type="limit",
                limit_price=fill_price,
                execution_context=ctx,
            )
        )
        details = {
            "broker_order_id": result.broker_order_id,
            "status": result.status,
            "filled_price": result.filled_price,
            "filled_qty": result.filled_qty,
            "mode": "paper",
        }
        self._audit(
            ControlFabricAuditAction.EXECUTION,
            resource_id=intent.id,
            success=result.status == "filled",
            details=details,
            error=result.error,
        )
        return details


def venue_symbol(intent: DealIntentRead) -> str:
    symbol = (intent.exit_logic or {}).get("symbol")
    return str(symbol) if symbol else "BTC-USD"


async def run_validation_on_bars(
    pipeline: ValidationPipeline,
    bars: Sequence[HistoricalBar],
    *,
    venue: VenueConfig,
    strategy: Strategy,
    period_days: int,
    used_stub_data: bool = False,
    gaps: Sequence[str] | None = None,
    stack: PredictionRiskStack | None = None,
    bars_by_instrument: dict[int, list[HistoricalBar]] | None = None,
) -> ValidationReport:
    """Walk historical bars and validate the full intent pipeline."""
    stack_builder = stack or pipeline.prediction_stack
    all_bars = dict(bars_by_instrument or {})
    all_bars.setdefault(venue.instrument_id, list(bars))

    rejected: list[IntentGateOutcome] = []
    held: list[IntentGateOutcome] = []
    trades: list[PaperTrade] = []
    intents_proposed = 0
    intents_executed = 0
    min_index = 20

    for index in range(min_index, len(bars) - 1):
        halt = check_strategy_halt_sync(
            session_preferences=pipeline.profile.session_preferences,
            sleeve_id=venue.sleeve_id,
        )
        if halt.halted:
            rejected.append(
                IntentGateOutcome(
                    intent_id=f"halt-{index}",
                    strategy=strategy,
                    instrument_id=venue.instrument_id,
                    symbol=venue.symbol,
                    stage="kill_switch",
                    status="halted",
                    reason=halt.reason or "strategies_stopped",
                    explainability={"halt_source": halt.source},
                    bar_timestamp=bars[index].timestamp.isoformat(),
                )
            )
            break

        market_ctx = pipeline._build_market_context(bars, index, venue)
        proposal = pipeline.mesh.propose_intent(
            strategy,
            pipeline.profile,
            market_ctx,
            instrument_id=venue.instrument_id,
            instrument_category=venue.category,
        )

        if proposal.blocked or proposal.intent is None:
            reason = proposal.compliance.reason if proposal.blocked else "strategy produced no intent"
            rejected.append(
                IntentGateOutcome(
                    intent_id=f"blocked-{index}",
                    strategy=strategy,
                    instrument_id=venue.instrument_id,
                    symbol=venue.symbol,
                    stage="compliance" if proposal.blocked else "strategy_mesh",
                    status="blocked",
                    reason=reason,
                    explainability={"compliance": proposal.compliance.reason},
                    bar_timestamp=bars[index].timestamp.isoformat(),
                )
            )
            continue

        create = proposal.intent
        exit_logic = dict(create.exit_logic or {})
        exit_logic.setdefault("symbol", venue.symbol)
        create = create.model_copy(update={"exit_logic": exit_logic, "sleeve_id": venue.sleeve_id})

        intent = pipeline._create_to_read(create, status=DealIntentStatus.PENDING_APPROVAL)
        intents_proposed += 1

        pipeline._audit(
            ControlFabricAuditAction.INTENT_CREATED,
            resource_id=intent.id,
            success=True,
            details={
                "profile_id": pipeline.profile.id,
                "sleeve_id": intent.sleeve_id,
                "strategy": strategy.value,
                "source": venue.source,
            },
        )

        risk_request = IntentRiskRequest(
            sleeve_id=venue.sleeve_id,
            risk_amount_usd=Decimal("1000"),
            instrument_id=venue.instrument_id,
            instrument_category=venue.category,
        )
        sleeve_gate = pipeline.sleeve_engine.validate_new_intent_with_compliance(
            risk_request,
            pipeline.sleeve,
            pipeline.profile,
        )
        if not sleeve_gate.allowed:
            rejected.append(
                IntentGateOutcome(
                    intent_id=intent.id,
                    strategy=strategy,
                    instrument_id=venue.instrument_id,
                    symbol=venue.symbol,
                    stage="sleeve_engine",
                    status="blocked",
                    reason=sleeve_gate.reason,
                    explainability={"sleeve_gate": sleeve_gate.reason},
                    bar_timestamp=bars[index].timestamp.isoformat(),
                )
            )
            continue

        gate_context = pipeline._market_context_for_gates(bars, index, venue)
        risk_inputs = None
        if stack_builder is not None and index >= 24:
            try:
                stack_context = stack_builder.build_at_index(
                    all_bars,
                    target=venue,
                    index=index,
                    profile=pipeline.profile,
                    sleeve=pipeline.sleeve,
                    proposed_delta_weight=DEFAULT_INTENT_DELTA_WEIGHT,
                )
                gate_context = stack_context.market_context
                risk_inputs = stack_context.risk_inputs
            except (IndexError, ValueError):
                pass

        snapshot = RiskSnapshot()
        highs = [bar.high for bar in bars[max(0, index - 20) : index + 1]]
        lows = [bar.low for bar in bars[max(0, index - 20) : index + 1]]
        closes = [bar.close for bar in bars[max(0, index - 20) : index + 1]]
        atr = compute_atr(highs, lows, closes)
        price = bars[index].close

        risk_result = pipeline.risk_gate.check_intent(
            intent,
            pipeline.profile,
            pipeline.sleeve,
            gate_context,
            snapshot=snapshot,
            atr=atr,
            price=price,
            risk_inputs=risk_inputs,
        )
        pipeline._audit(
            ControlFabricAuditAction.RISK_GATE,
            resource_id=intent.id,
            success=risk_result.allowed,
            details={
                "outcome": risk_result.outcome.value,
                "reason": risk_result.reason,
                "metadata": risk_result.metadata,
            },
            error=None if risk_result.allowed else risk_result.reason,
        )

        if not risk_result.allowed:
            rejected.append(
                IntentGateOutcome(
                    intent_id=intent.id,
                    strategy=strategy,
                    instrument_id=venue.instrument_id,
                    symbol=venue.symbol,
                    stage="risk_gate",
                    status=risk_result.outcome.value,
                    reason=risk_result.reason,
                    explainability={
                        "anti_loss_guard": risk_result.metadata,
                        "outcome": risk_result.outcome.value,
                    },
                    bar_timestamp=bars[index].timestamp.isoformat(),
                )
            )
            continue

        decision = evaluate_policy(intent, pipeline.profile, gate_context)
        pipeline._audit(
            ControlFabricAuditAction.APPROVAL_POLICY,
            resource_id=intent.id,
            success=decision.is_approvable,
            details=decision.to_audit_details(),
            error=decision.reason if not decision.is_approvable else None,
        )

        if decision.state == PolicyState.HOLD_FOR_REVIEW:
            held.append(
                IntentGateOutcome(
                    intent_id=intent.id,
                    strategy=strategy,
                    instrument_id=venue.instrument_id,
                    symbol=venue.symbol,
                    stage="approval_policy",
                    status=decision.state.value,
                    reason=decision.reason,
                    explainability=decision.to_audit_details(),
                    bar_timestamp=bars[index].timestamp.isoformat(),
                )
            )
            continue

        if not decision.is_approvable:
            rejected.append(
                IntentGateOutcome(
                    intent_id=intent.id,
                    strategy=strategy,
                    instrument_id=venue.instrument_id,
                    symbol=venue.symbol,
                    stage="approval_policy",
                    status=decision.state.value,
                    reason=decision.reason,
                    explainability=decision.to_audit_details(),
                    bar_timestamp=bars[index].timestamp.isoformat(),
                )
            )
            continue

        try:
            transition_deal_intent_status(intent.status, DealIntentEvent.APPROVE)
            executing = intent.model_copy(update={"status": DealIntentStatus.EXECUTING})
        except ValueError:
            continue

        fill_price = bars[index].close
        exec_details = await pipeline._paper_execute(executing, fill_price)
        if exec_details.get("status") != "filled":
            continue

        intents_executed += 1
        exit_price = bars[index + 1].close
        if intent.direction == DealIntentDirection.LONG:
            ret_pct = (exit_price - fill_price) / max(fill_price, 1e-9) * 100.0
        else:
            ret_pct = (fill_price - exit_price) / max(fill_price, 1e-9) * 100.0

        trades.append(
            PaperTrade(
                intent_id=intent.id,
                strategy=strategy,
                symbol=venue.symbol,
                entry_price=fill_price,
                exit_price=exit_price,
                return_pct=round(ret_pct, 4),
                entry_ts=bars[index].timestamp.isoformat(),
                exit_ts=bars[index + 1].timestamp.isoformat(),
            )
        )

    equity_curve, returns = build_equity_curve(trades)
    report = ValidationReport(
        source=venue.source,
        strategy=strategy.value,
        symbol=venue.symbol,
        period_days=period_days,
        total_bars=len(bars),
        intents_proposed=intents_proposed,
        intents_executed=intents_executed,
        win_rate=compute_win_rate(trades),
        max_drawdown_pct=compute_max_drawdown_pct(equity_curve),
        sharpe_ratio=compute_sharpe_ratio(returns),
        rejected=rejected,
        held=held,
        trades=trades,
        audit_entries=list(pipeline.audit_entries),
        gaps=list(gaps or KNOWN_GAPS),
        used_stub_data=used_stub_data,
    )
    return report


def run_replay_consistency_check(
    pipeline: ValidationPipeline,
    bars: Sequence[HistoricalBar],
    *,
    venue: VenueConfig,
    strategy: Strategy,
) -> int:
    """Build ReplayIntentRecords from validation bars and verify replay engine parity."""
    records: list[ReplayIntentRecord] = []
    profiles = {pipeline.profile.id: pipeline.profile}
    sleeves = {pipeline.sleeve.id: pipeline.sleeve}

    for index in range(20, min(len(bars) - 1, 40)):
        market_ctx = pipeline._build_market_context(bars, index, venue)
        proposal = pipeline.mesh.propose_intent(
            strategy,
            pipeline.profile,
            market_ctx,
            instrument_id=venue.instrument_id,
            instrument_category=venue.category,
        )
        if proposal.intent is None:
            continue
        intent = pipeline._create_to_read(proposal.intent, status=DealIntentStatus.PENDING_APPROVAL)
        gate_context = pipeline._market_context_for_gates(bars, index, venue)
        records.append(
            ReplayIntentRecord(
                intent_id=intent.id,
                instrument_id=venue.instrument_id,
                sleeve_id=venue.sleeve_id,
                profile_id=pipeline.profile.id,
                timestamp=bars[index].timestamp.isoformat(),
                intent_snapshot=intent.model_dump(mode="json"),
                market_snapshot={
                    "instrument_volatility": gate_context.instrument_volatility,
                    "instrument_spread_bps": gate_context.instrument_spread_bps,
                    "max_correlation_with_portfolio": gate_context.max_correlation_with_portfolio,
                    "market_regime": gate_context.market_regime,
                    "profile_drawdown_pct": gate_context.profile_drawdown_pct,
                    "profile_daily_loss_abs": str(gate_context.profile_daily_loss_abs),
                },
            )
        )

    if not records:
        return 0
    report = pipeline.replay_engine.replay(records, profiles=profiles, sleeves=sleeves)
    return report.matched


async def run_combined_validation(
    pipeline: ValidationPipeline,
    venue_bars: dict[str, tuple[list[HistoricalBar], bool]],
    *,
    venues: dict[str, VenueConfig],
    strategies: Sequence[Strategy],
    period_days: int = 90,
    stack: PredictionRiskStack | None = None,
    bars_by_instrument: dict[int, list[HistoricalBar]] | None = None,
) -> CombinedValidationReport:
    stack_builder = stack or pipeline.prediction_stack
    all_bars = dict(bars_by_instrument or {})
    for source, (bars, _stub) in venue_bars.items():
        venue = venues[source]
        all_bars.setdefault(venue.instrument_id, bars)

    reports: list[ValidationReport] = []
    for source, (bars, stub) in venue_bars.items():
        venue = venues[source]
        for strategy in strategies:
            pipeline.audit_entries.clear()
            report = await run_validation_on_bars(
                pipeline,
                bars,
                venue=venue,
                strategy=strategy,
                period_days=period_days,
                used_stub_data=stub,
                stack=stack_builder,
                bars_by_instrument=all_bars,
            )
            reports.append(report)
    return CombinedValidationReport(period_days=period_days, reports=reports, gaps=list(KNOWN_GAPS))
