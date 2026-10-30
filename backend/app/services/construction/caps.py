"""Hard deploy cap is the institutional floor. Never invent $10k over settings."""
from __future__ import annotations

from dataclasses import dataclass

from app.core.config import settings
from app.services.risk.portfolio_sizing import (
    deploy_bounds,
    resolve_deploy_cap_for_sizing,
)


@dataclass(frozen=True, slots=True)
class DeployEnvelope:
    deploy_cap: float
    per_name: float
    max_book: float
    min_ticket: float
    name_frac: float
    exposure_frac: float
    cash_buffer_frac: float


def envelope(
    settings_cap: float | None,
    account_total: float | None = None,
) -> DeployEnvelope:
    cap = resolve_deploy_cap_for_sizing(settings_cap, account_total)
    per_name, max_book, min_ticket = deploy_bounds(cap)
    expo = float(settings.MAX_PORTFOLIO_EXPOSURE_PCT) / 100.0
    cash = max(0.0, 1.0 - expo)
    name_frac = per_name / cap if cap > 0 else 0.0
    return DeployEnvelope(
        deploy_cap=cap,
        per_name=per_name,
        max_book=max_book,
        min_ticket=min_ticket,
        name_frac=name_frac,
        exposure_frac=expo,
        cash_buffer_frac=cash,
    )
