"""Pre-trade: hard cap, book exposure, short-locate proxy, US PDT flag."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from app.services.construction.caps import envelope
from app.services.construction.compliance import screen


@dataclass(frozen=True, slots=True)
class Pretrade:
    allow: bool
    reasons: tuple[str, ...]
    locate_ok: bool
    pdt_blocked: bool
    deploy_cap: float
    book_usd: float


def short_locate_proxy(
    *,
    side: str,
    notional_usd: float,
    adv_usd: float,
    participation: float = 0.01,
) -> bool:
    """No HTB vendor: locate ≈ 1% ADV. Longs always locate-ok."""
    if str(side).lower() not in {"short", "sell_short"}:
        return True
    if adv_usd <= 0:
        return False
    return float(notional_usd) <= float(adv_usd) * float(participation) + 1e-9


def pdt_blocked(
    *,
    account_equity: float,
    day_trades_5d: int,
    is_us: bool,
    would_day_trade: bool,
    pdt_equity_floor: float = 25_000.0,
    max_day_trades: int = 3,
) -> bool:
    """FINRA-style: < $25k equity + already 3 day-trades in 5 sessions → block another."""
    if not is_us or not would_day_trade:
        return False
    if float(account_equity) >= float(pdt_equity_floor) - 1e-6:
        return False
    return int(day_trades_5d) >= int(max_day_trades)


def check(
    *,
    settings_cap: float | None,
    account_total: float | None,
    proposed_book_usd: float,
    symbols: Sequence[str] = (),
    sides: Sequence[str] = (),
    notionals: Sequence[float] = (),
    adv: Sequence[float] = (),
    countries: Sequence[str] = (),
    day_trades_5d: int = 0,
    would_day_trade: bool = False,
    restricted: Sequence[str] = (),
) -> Pretrade:
    env = envelope(settings_cap, account_total)
    reasons: list[str] = []
    if proposed_book_usd > env.max_book + 1e-6:
        reasons.append("exposure_cap")
    if proposed_book_usd > env.deploy_cap + 1e-6:
        reasons.append("deploy_cap")
    for i, usd in enumerate(notionals):
        if float(usd) > env.per_name + 1e-6:
            reasons.append(f"name_cap:{(symbols[i] if i < len(symbols) else i)}")
    ok_screen, breaches = screen(symbols, restricted=restricted, adv=adv, countries=countries)
    for b in breaches:
        reasons.append(f"{b.rule}:{b.symbol}")
    locates = []
    for i, usd in enumerate(notionals):
        side = sides[i] if i < len(sides) else "long"
        a = adv[i] if i < len(adv) else 0.0
        locates.append(short_locate_proxy(side=side, notional_usd=float(usd), adv_usd=float(a)))
        if not locates[-1]:
            reasons.append(f"locate:{(symbols[i] if i < len(symbols) else i)}")
    is_us = any(str(c or "US").upper() == "US" for c in (countries or ("US",)))
    pdt = pdt_blocked(
        account_equity=float(account_total or env.deploy_cap),
        day_trades_5d=day_trades_5d,
        is_us=is_us,
        would_day_trade=would_day_trade,
    )
    if pdt:
        reasons.append("pdt")
    if symbols and not all(ok_screen):
        reasons.append("compliance")
    return Pretrade(
        allow=not reasons,
        reasons=tuple(dict.fromkeys(reasons)),
        locate_ok=all(locates) if locates else True,
        pdt_blocked=pdt,
        deploy_cap=env.deploy_cap,
        book_usd=round(float(proposed_book_usd), 2),
    )
