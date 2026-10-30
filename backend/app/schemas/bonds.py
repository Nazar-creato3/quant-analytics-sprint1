from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class BondIssueOut(BaseModel):
    figi: str
    secid: str | None = None
    name: str | None = None
    qty: str | None = None
    ytm: float | None = None
    ytp: float | None = None
    current_yield: float | None = None
    duration: float | None = None
    modified: float | None = None
    convexity: float | None = None
    g_spread: float | None = None
    g_spread_label: str | None = None
    dirty_price: float | None = None
    clean_price: float | None = None
    aci: float | None = None
    value_rub: float | None = None
    next_event: str | None = None
    floater: bool = False
    warnings: list[str] = Field(default_factory=list)
    excluded: bool = False
    status: str = "ok"
    methodology: str = "/methodology/bonds"
    as_of: str | None = None
    source: str | None = None


class BondPortfolioOut(BaseModel):
    portfolio_id: str
    user_id: str
    as_of: str | None = None
    source: str | None = None
    methodology: str
    summary: dict[str, Any]
    issues: list[dict[str, Any]]
    ladder: dict[str, Any]
    data_status: str
    texts_key: str = "bonds"


class BondStressOut(BaseModel):
    portfolio_id: str
    shift_bp: int
    delta_rub: float | None
    delta_pct_portfolio: float | None
    floater_note: str | None = None
    issues: list[dict[str, Any]]
    elapsed_ms: float
    methodology: str
    as_of: str | None = None
    source: str | None = None
