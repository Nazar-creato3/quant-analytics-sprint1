"""Sleeve-level NAV: paper / live / user never commingle. T+1 + CA without a vendor."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Mapping, Sequence


SLEEVES: tuple[str, ...] = ("cross_sectional", "retail_long_only", "cash")


@dataclass(frozen=True, slots=True)
class SleeveNAV:
    user_id: str
    account: str  # paper | live
    sleeve: str
    nav: float
    deploy_cap: float

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.user_id, self.account, self.sleeve)


def split_account_nav(
    *,
    user_id: str,
    account: str,
    nav: float,
    deploy_cap: float,
    sleeve_frac: Mapping[str, float] | None = None,
) -> tuple[SleeveNAV, ...]:
    """One account NAV → isolated sleeves. Residual always cash. Cap is per-account, not shared."""
    cap = min(max(0.0, float(deploy_cap)), max(0.0, float(nav))) if nav > 0 and deploy_cap > 0 else max(0.0, float(deploy_cap or nav or 0.0))
    if nav <= 0 and cap <= 0:
        return ()
    base = max(float(nav), 0.0)
    fracs = dict(sleeve_frac or {"cross_sectional": 0.0, "retail_long_only": 0.80, "cash": 0.20})
    # Force cash sleeve ≥ explicit buffer leftover
    risky = max(0.0, float(fracs.get("cross_sectional") or 0.0)) + max(
        0.0, float(fracs.get("retail_long_only") or 0.0)
    )
    if risky > 0.80:
        scale = 0.80 / risky
        fracs["cross_sectional"] = float(fracs.get("cross_sectional") or 0.0) * scale
        fracs["retail_long_only"] = float(fracs.get("retail_long_only") or 0.0) * scale
    fracs["cash"] = max(0.0, 1.0 - float(fracs.get("cross_sectional") or 0.0) - float(fracs.get("retail_long_only") or 0.0))
    out: list[SleeveNAV] = []
    for name in SLEEVES:
        f = max(0.0, float(fracs.get(name) or 0.0))
        sleeve_nav = round(base * f, 2) if base > 0 else 0.0
        sleeve_cap = round(cap * f, 2) if name != "cash" else 0.0
        out.append(
            SleeveNAV(
                user_id=str(user_id),
                account=account,
                sleeve=name,
                nav=sleeve_nav,
                deploy_cap=sleeve_cap,
            )
        )
    return tuple(out)


def isolate_users(
    rows: Sequence[SleeveNAV],
) -> dict[tuple[str, str], tuple[SleeveNAV, ...]]:
    """Group by (user, account). Callers must not sum across keys."""
    grouped: dict[tuple[str, str], list[SleeveNAV]] = {}
    for row in rows:
        grouped.setdefault((row.user_id, row.account), []).append(row)
    return {k: tuple(v) for k, v in grouped.items()}


def assert_isolated(a: SleeveNAV, b: SleeveNAV) -> bool:
    """True when two NAVs must not be netted (different user or account)."""
    return a.user_id != b.user_id or a.account != b.account


@dataclass(frozen=True, slots=True)
class CashLeg:
    amount: float
    trade_date: date
    settle_date: date
    kind: str  # buy_debit | sell_credit | dividend
    user_id: str
    account: str
    sleeve: str


def next_business_day(d: date) -> date:
    nxt = d + timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    return nxt


def t_plus(d: date, n: int = 1) -> date:
    out = d
    for _ in range(max(0, n)):
        out = next_business_day(out)
    return out


def new_trade_leg(
    *,
    amount: float,
    as_of: date,
    kind: str,
    user_id: str,
    account: str,
    sleeve: str,
    t_plus_days: int = 1,
) -> CashLeg:
    return CashLeg(
        amount=float(amount),
        trade_date=as_of,
        settle_date=t_plus(as_of, t_plus_days),
        kind=kind,
        user_id=user_id,
        account=account,
        sleeve=sleeve,
    )


def settled_cash(legs: Sequence[CashLeg], *, as_of: date, user_id: str, account: str, sleeve: str) -> float:
    tot = 0.0
    for leg in legs:
        if (leg.user_id, leg.account, leg.sleeve) != (user_id, account, sleeve):
            continue
        if as_of >= leg.settle_date:
            tot += float(leg.amount)
    return round(tot, 2)


def pending_cash(legs: Sequence[CashLeg], *, as_of: date, user_id: str, account: str, sleeve: str) -> float:
    tot = 0.0
    for leg in legs:
        if (leg.user_id, leg.account, leg.sleeve) != (user_id, account, sleeve):
            continue
        if as_of < leg.settle_date:
            tot += float(leg.amount)
    return round(tot, 2)


def apply_ca_to_nav(
    nav: float,
    *,
    cash_dividend_usd: float = 0.0,
    split_ratio: float = 1.0,
) -> float:
    """Cash div increases NAV; split is qty/price only — NAV dollars unchanged."""
    _ = split_ratio  # lots handle share count; NAV cash is invariant
    return round(float(nav) + max(0.0, float(cash_dividend_usd)), 2)
