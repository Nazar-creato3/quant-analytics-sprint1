"""Validation replay report structures."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.domain.enums import Strategy
from app.services.integration.types import AuditEntry, IntentGateOutcome, PaperTrade


@dataclass
class ValidationReport:
    """Single strategy × venue validation outcome."""

    source: str
    strategy: str
    symbol: str
    period_days: int
    total_bars: int
    intents_proposed: int
    intents_executed: int
    win_rate: float
    max_drawdown_pct: float
    sharpe_ratio: float
    rejected: list[IntentGateOutcome] = field(default_factory=list)
    held: list[IntentGateOutcome] = field(default_factory=list)
    trades: list[PaperTrade] = field(default_factory=list)
    audit_entries: list[AuditEntry] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    used_stub_data: bool = False

    def summary(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "strategy": self.strategy,
            "symbol": self.symbol,
            "period_days": self.period_days,
            "total_bars": self.total_bars,
            "intents_proposed": self.intents_proposed,
            "intents_executed": self.intents_executed,
            "win_rate": self.win_rate,
            "max_drawdown_pct": self.max_drawdown_pct,
            "sharpe_ratio": self.sharpe_ratio,
            "rejected_count": len(self.rejected),
            "held_count": len(self.held),
            "rejected_reasons": [
                {"stage": item.stage, "status": item.status, "reason": item.reason}
                for item in self.rejected[:20]
            ],
            "held_reasons": [
                {"stage": item.stage, "status": item.status, "reason": item.reason}
                for item in self.held[:20]
            ],
            "used_stub_data": self.used_stub_data,
            "gaps": self.gaps,
        }


@dataclass
class CombinedValidationReport:
    """Aggregate report across venues and strategies."""

    period_days: int
    reports: list[ValidationReport] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)

    @property
    def total_executed(self) -> int:
        return sum(report.intents_executed for report in self.reports)

    @property
    def combined_win_rate(self) -> float:
        trades = [trade for report in self.reports for trade in report.trades]
        if not trades:
            return 0.0
        wins = sum(1 for trade in trades if trade.return_pct > 0)
        return round(wins / len(trades), 4)

    def summary(self) -> dict[str, Any]:
        return {
            "period_days": self.period_days,
            "total_executed": self.total_executed,
            "combined_win_rate": self.combined_win_rate,
            "reports": [report.summary() for report in self.reports],
            "gaps": self.gaps,
        }
