"""Human-readable risk explanations for Terminal Quant outputs."""
from __future__ import annotations

from app.services.terminal_platform.quant.models import (
    QuantRiskDecision,
    RiskMetrics,
    StressResult,
    VaRResult,
)


def _pct(value: float, *, decimals: int = 2) -> str:
    return f"{value * 100:.{decimals}f}%"


class RiskExplainer:
    """Turn quant numbers into plain-language commentary (no LLM)."""

    def explain_metrics(self, metrics: RiskMetrics) -> str:
        parts = [
            f"Sharpe {metrics.sharpe:.2f}",
            f"Sortino {metrics.sortino:.2f}",
            f"annualized volatility {_pct(metrics.volatility_annual)}",
            f"max drawdown {_pct(metrics.max_drawdown)}",
        ]
        if metrics.cagr is not None:
            parts.append(f"CAGR {_pct(metrics.cagr)}")
        if metrics.beta is not None:
            parts.append(f"beta {metrics.beta:.2f}")
        if metrics.correlation is not None:
            parts.append(f"benchmark correlation {metrics.correlation:.2f}")

        tone = self._tone(metrics)
        return f"{tone} Key figures: {'; '.join(parts)}."

    def explain_var(self, result: VaRResult) -> str:
        method = result.method.value.replace("_", " ")
        text = (
            f"At {result.confidence:.0%} confidence ({method}), "
            f"estimated loss is {_pct(result.var)} of notional"
        )
        if result.cvar is not None:
            text += f"; expected shortfall beyond VaR is {_pct(result.cvar)}"
        if result.n_simulations:
            text += f" ({result.n_simulations} Monte Carlo paths)"
        return text + "."

    def explain_stress(self, result: StressResult) -> str:
        direction = "loss" if result.portfolio_pnl_pct < 0 else "gain"
        top = sorted(
            result.contribution_by_symbol.items(),
            key=lambda item: abs(item[1]),
            reverse=True,
        )[:3]
        drivers = ", ".join(f"{sym} {_pct(contrib)}" for sym, contrib in top) or "n/a"
        return (
            f"Scenario '{result.scenario_name}' implies portfolio {direction} of "
            f"{_pct(abs(result.portfolio_pnl_pct))} "
            f"(≈ {result.portfolio_pnl_usd:,.2f} USD). Largest drivers: {drivers}."
        )

    def explain_decision(self, decision: QuantRiskDecision) -> str:
        status = "approved" if decision.approved else "blocked"
        bits = [f"Quant risk check {status} at stage '{decision.stage}': {decision.reason}"]
        if decision.var is not None:
            bits.append(f"VaR={_pct(decision.var)}")
        if decision.drawdown is not None:
            bits.append(f"drawdown={_pct(decision.drawdown)}")
        if decision.metrics is not None:
            bits.append(self.explain_metrics(decision.metrics))
        return " ".join(bits)

    def explain(
        self,
        *,
        metrics: RiskMetrics | None = None,
        var_result: VaRResult | None = None,
        decision: QuantRiskDecision | None = None,
        stress: StressResult | None = None,
    ) -> str:
        chunks: list[str] = []
        if metrics is not None:
            chunks.append(self.explain_metrics(metrics))
        if var_result is not None:
            chunks.append(self.explain_var(var_result))
        if stress is not None:
            chunks.append(self.explain_stress(stress))
        if decision is not None:
            chunks.append(self.explain_decision(decision))
        if not chunks:
            return "No quant risk inputs provided."
        return " ".join(chunks)

    @staticmethod
    def _tone(metrics: RiskMetrics) -> str:
        if metrics.max_drawdown >= 0.25 or metrics.volatility_annual >= 0.40:
            return "Risk profile is elevated."
        if metrics.sharpe >= 1.0 and metrics.max_drawdown < 0.15:
            return "Risk-adjusted profile looks favorable."
        return "Risk profile is moderate."
