"""System diagnostics: macro invariants + golden regression checks (Prompt 89)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from app.services.analysis.macro_region import format_macro_snippet_for_symbol
from app.services.chat.context_isolation import prior_messages_for_symbol, resolve_advisor_symbol
from app.services.market_analysis.scenarios import run_stress_scenarios
from app.services.risk.maneuver_generator import ManeuverGenerator


@dataclass
class DiagnosticFinding:
    check_id: str
    passed: bool
    message: str
    severity: str = "error"
    context: dict[str, Any] = field(default_factory=dict)


@dataclass
class DiagnosticsReport:
    findings: list[DiagnosticFinding]

    @property
    def ok(self) -> bool:
        return all(f.passed for f in self.findings)

    def failures(self) -> list[DiagnosticFinding]:
        return [f for f in self.findings if not f.passed]


_MACRO_BOUNDS: dict[str, tuple[float, float]] = {
    "rate_cb_us": (0.0, 10.0),
    "rate_cb": (0.0, 25.0),
    "vix": (5.0, 100.0),
}


def check_macro_indicator_invariants(indicators: dict[str, float]) -> list[DiagnosticFinding]:
    findings: list[DiagnosticFinding] = []
    for key, (lo, hi) in _MACRO_BOUNDS.items():
        val = indicators.get(key)
        if val is None:
            continue
        if not (lo <= float(val) <= hi):
            findings.append(
                DiagnosticFinding(
                    check_id=f"macro.invariant.{key}",
                    passed=False,
                    message=f"{key}={val} outside [{lo}, {hi}]",
                    context={"value": val, "lo": lo, "hi": hi},
                )
            )
        else:
            findings.append(
                DiagnosticFinding(
                    check_id=f"macro.invariant.{key}",
                    passed=True,
                    message=f"{key} within bounds",
                )
            )
    return findings


def golden_spy_not_cbr_rate() -> DiagnosticFinding:
    snippet = format_macro_snippet_for_symbol(
        "SPY",
        {"rate_cb": 14.25, "rate_cb_us": 3.75, "vix": 17.0},
    )
    bad = "14.25" in snippet or "ЦБ РФ" in snippet
    return DiagnosticFinding(
        check_id="golden.88.spy_fed_not_cbr",
        passed=not bad and "3.75" in snippet,
        message="SPY macro must use Fed rate, not CBR" if bad else "SPY macro region OK",
    )


def golden_gazp_not_fed_rate() -> DiagnosticFinding:
    snippet = format_macro_snippet_for_symbol(
        "GAZP",
        {"rate_cb": 14.25, "rate_cb_us": 3.75, "vix": 17.0},
    )
    bad = "3.75" in snippet and "ФРС" in snippet
    return DiagnosticFinding(
        check_id="golden.88.gazp_cbr_not_fed",
        passed="14.25" in snippet and not bad,
        message="GAZP macro must use CBR rate" if bad else "GAZP macro region OK",
    )


def golden_chat_gazp_googl_isolation() -> DiagnosticFinding:
    prior = ("GAZP инвестпрограмма 515 млрд ₽",)
    filtered = prior_messages_for_symbol(prior, "GOOGL")
    sym = resolve_advisor_symbol("GOOGL прогноз", "GAZP")
    ok = sym == "GOOGL" and filtered == ()
    return DiagnosticFinding(
        check_id="golden.80.googl_no_gazp_leak",
        passed=ok,
        message="GOOGL must not inherit GAZP prior facts" if not ok else "Chat isolation OK",
    )


def golden_scenario_replay_not_fake_zero() -> DiagnosticFinding:
    exposures = {"market_beta": 1.1, "momentum": 0.3, "value": 0.1}
    results = run_stress_scenarios(exposures)
    replay = results.get("2008_replay")
    ok = replay is not None and replay != 0.0
    empty = run_stress_scenarios({})
    ok = ok and empty.get("2008_replay") is None
    return DiagnosticFinding(
        check_id="golden.81.replay_not_stub_zero",
        passed=ok,
        message="Historical replay must be non-zero with exposure, null without",
    )


def golden_maneuver_threshold_fallback(
    market_data_factory: Callable[[], dict] | None = None,
) -> DiagnosticFinding:
    """Requires synthetic OHLCV; skipped when factory not provided in live runs."""
    if market_data_factory is None:
        return DiagnosticFinding(
            check_id="golden.84.maneuver_best_available",
            passed=True,
            message="skipped (no market_data_factory in this run)",
            severity="info",
        )
    gen = ManeuverGenerator(confidence_threshold=0.99, portfolio_size=10_000.0)
    outs = gen.generate(market_data=market_data_factory())
    tradeable = [m for m in outs if not m.is_no_trade]
    ok = len(tradeable) >= 1
    return DiagnosticFinding(
        check_id="golden.84.maneuver_best_available",
        passed=ok,
        message="High threshold must still yield ≥1 tradeable when signals exist",
    )


def golden_chat_spy_brief_no_duplicate_block() -> DiagnosticFinding:
    """Prompt 92: SPY forecast chat must not repeat long metric blocks when user asks for brief reply."""
    from dataclasses import replace

    from app.services.analysis.context import AnalysisContext
    from app.services.analysis.ticker_payload import ShapFactor, assemble_ticker_analysis_payload
    from app.services.chat.advisor_prompt import has_repeated_substring, wants_brief_direct_answer
    from app.services.chat.deep_advisor import AdvisorContext, compose_deep_reply
    from app.services.prediction_hierarchy.types import (
        ActionForecast,
        ActionRecommendation,
        DistributionForecast,
        ForecastOutput,
        IntervalForecast,
        PointForecast,
        PointMagnitudeClass,
        RiskForecastLayer,
        ScenarioForecast,
    )

    question = (
        "Почему такой прогноз по SPY на неделю? Ответь прямо, без полного шаблона."
    )
    output = ForecastOutput(
        instrument_id=1,
        symbol="SPY",
        as_of="2026-07-23T00:00:00Z",
        point_forecast=PointForecast(
            magnitude_class=PointMagnitudeClass.UP,
            expected_return_sign=1,
            momentum_score=0.5,
        ),
        interval_forecast=IntervalForecast(
            horizon_days=7,
            p10=-0.02,
            p90=0.05,
            rolling_volatility=0.015,
            confidence_multiplier=1.645,
        ),
        distribution_forecast=DistributionForecast(
            p5=-0.05,
            p25=0.0,
            p50=0.02,
            p75=0.04,
            p95=0.08,
            method="historical_percentile",
        ),
        scenario_forecast=ScenarioForecast(scenarios=(), scenario_dispersion=0.02),
        risk_forecast=RiskForecastLayer(
            instrument_metrics={"cvar_95": 0.11, "beta": 1.0, "var_95": 0.08},
            portfolio_metrics={},
            plain_language_summary="",
            risk_items=(),
        ),
        action_forecast=ActionForecast(
            recommendation=ActionRecommendation.HOLD,
            reason="range",
            rule_id="t",
        ),
        calibrated_confidence=0.6,
        high_confidence=False,
        instruction_block="",
        narrator_insights=(),
    )
    analysis = AnalysisContext(symbol="SPY")
    payload = assemble_ticker_analysis_payload(output=output, analysis=analysis)
    payload = replace(
        payload,
        ml_score=0.65,
        shap_top_factors=(ShapFactor(feature="momentum", contribution=0.1),),
    )
    ctx = AdvisorContext(output=output, analysis=analysis, payload=payload)
    reply = compose_deep_reply(question=question, ctx=ctx, prior_messages=())
    ok = (
        wants_brief_direct_answer(question)
        and "[1]" not in reply
        and not has_repeated_substring(reply, min_len=50)
        and reply.count("VaR 95%") <= 1
        and reply.count("CVaR 95%") <= 1
    )
    return DiagnosticFinding(
        check_id="golden.92.spy_brief_no_duplicate_metrics",
        passed=ok,
        message="SPY brief chat must not duplicate long metric blocks"
        if not ok
        else "SPY brief chat reply OK",
    )


def golden_maneuvers_count_toast_vs_list_sync() -> DiagnosticFinding:
    """Prompt 90: status/toast tradeable_count uses same rule as persisted maneuvers."""
    from types import SimpleNamespace

    from app.schemas.schemas import StrategyType
    from app.services.pipeline.maneuver_counts import analysis_list_counts_sync, count_tradeable_persisted

    rows = [
        SimpleNamespace(
            strategy_type=StrategyType.MOMENTUM,
            ticker="SPY",
            direction="long",
            position_size_usd=1_000.0,
        ),
        SimpleNamespace(
            strategy_type=StrategyType.NO_TRADE,
            ticker="—",
            direction="neutral",
            position_size_usd=0.0,
        ),
    ]
    n = count_tradeable_persisted(rows)
    ok = n == 1 and analysis_list_counts_sync(status_tradeable=1, report_maneuvers=rows, list_tradeable=1)
    bad = analysis_list_counts_sync(status_tradeable=10, report_maneuvers=rows, list_tradeable=1)
    passed = ok and not bad
    return DiagnosticFinding(
        check_id="maneuvers_count_toast_vs_list_sync",
        passed=passed,
        message="Poll/toast count must match report rows" if passed else "Toast/list sync rule broken",
    )


class DiagnosticsEngine:
    """Run invariant + golden checks; alert on failure via ops webhook."""

    def run(
        self,
        *,
        macro_indicators: dict[str, float] | None = None,
        market_data_factory: Callable[[], dict] | None = None,
    ) -> DiagnosticsReport:
        findings: list[DiagnosticFinding] = []
        if macro_indicators:
            findings.extend(check_macro_indicator_invariants(macro_indicators))
        findings.extend(
            [
                golden_spy_not_cbr_rate(),
                golden_gazp_not_fed_rate(),
                golden_chat_gazp_googl_isolation(),
                golden_scenario_replay_not_fake_zero(),
                golden_maneuver_threshold_fallback(market_data_factory),
                golden_chat_spy_brief_no_duplicate_block(),
                golden_maneuvers_count_toast_vs_list_sync(),
            ]
        )
        return DiagnosticsReport(findings=findings)

    async def run_and_alert(
        self,
        *,
        macro_indicators: dict[str, float] | None = None,
        market_data_factory: Callable[[], dict] | None = None,
    ) -> DiagnosticsReport:
        report = self.run(
            macro_indicators=macro_indicators,
            market_data_factory=market_data_factory,
        )
        for failure in report.failures():
            if failure.severity == "info":
                continue
            from app.services.event_risk.alerts import emit_diagnostics_alert

            await emit_diagnostics_alert(
                check_id=failure.check_id,
                message=failure.message,
                context=failure.context,
            )
        return report
