"""Structured compliance report payload before PDF rendering."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True, slots=True)
class ComplianceReportDocument:
    """Human-readable compliance documentation for a DealIntent recommendation."""

    report_id: str
    generated_at: datetime
    deal_intent_id: str
    instrument_symbol: str
    instrument_id: int
    direction: str
    strategy: str
    status: str
    entry_reason: str
    target_price: str | None
    risk_appetite: str
    max_drawdown_pct: str
    jurisdiction: str
    account_type: str
    explainability_headline: str
    explainability_sections: tuple[tuple[str, str], ...]
    narrator_insights: tuple[str, ...] = ()
    audit_reference: str | None = None
    legal_notice: str = (
        "Документ сформирован автоматически платформой Quant Analytics. "
        "Рекомендация носит вероятностный характер и не является гарантией результата. "
        "Инвестор самостоятельно принимает решение об исполнении в своём брокерском счёте."
    )
    forbidden_response_keys: frozenset[str] = field(
        default_factory=lambda: frozenset(
            {
                "email",
                "user_id",
                "profile_id",
                "client_name",
                "phone",
            }
        )
    )

    def to_dict(self) -> dict[str, object]:
        return {
            "report_id": self.report_id,
            "generated_at": self.generated_at.isoformat(),
            "deal_intent_id": self.deal_intent_id,
            "instrument_symbol": self.instrument_symbol,
            "instrument_id": self.instrument_id,
            "direction": self.direction,
            "strategy": self.strategy,
            "status": self.status,
            "entry_reason": self.entry_reason,
            "target_price": self.target_price,
            "risk_appetite": self.risk_appetite,
            "max_drawdown_pct": self.max_drawdown_pct,
            "jurisdiction": self.jurisdiction,
            "account_type": self.account_type,
            "explainability_headline": self.explainability_headline,
            "explainability_sections": [
                {"title": title, "body": body}
                for title, body in self.explainability_sections
            ],
            "narrator_insights": list(self.narrator_insights),
            "audit_reference": self.audit_reference,
            "legal_notice": self.legal_notice,
        }
