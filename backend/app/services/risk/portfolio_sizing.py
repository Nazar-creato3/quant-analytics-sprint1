"""Resolve deploy cap and split it across maneuvers by conviction."""
from __future__ import annotations

from typing import Any, Sequence

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# Only when BOTH settings cap and account total are unset.
DEFAULT_SIZING_PORTFOLIO_USD: float = 10_000.0
MIN_PROPOSAL_PCT_OF_CAP: float = 3.0
MIN_PROPOSAL_USD: float = 20.0


def min_proposal_notional_usd(portfolio_usd: float) -> float:
    """Smallest ticket that still fits inside one name's % cap."""
    cap = max(0.0, float(portfolio_usd or 0.0))
    if cap <= 0:
        return MIN_PROPOSAL_USD
    per_name = cap * float(settings.MAX_POSITION_PCT) / 100.0
    if settings.MAX_NOTIONAL_PER_POSITION_USD and settings.MAX_NOTIONAL_PER_POSITION_USD > 0:
        per_name = min(per_name, float(settings.MAX_NOTIONAL_PER_POSITION_USD))
    pct_min = cap * MIN_PROPOSAL_PCT_OF_CAP / 100.0
    floor = min(MIN_PROPOSAL_USD, per_name) if per_name > 0 else MIN_PROPOSAL_USD
    ticket = max(floor, pct_min)
    if per_name > 0:
        ticket = min(ticket, per_name)
    return round(max(ticket, 0.01), 2)


def resolve_portfolio_size_usd(raw: float | None) -> float:
    """Positive notional for risk math. Prefer an explicit cap; never invent $10k over it."""
    if raw is None:
        base = float(settings.DEFAULT_PORTFOLIO_SIZE)
    else:
        base = float(raw)
    if base > 0:
        return base
    fallback = float(getattr(settings, "SIZING_PORTFOLIO_FALLBACK_USD", DEFAULT_SIZING_PORTFOLIO_USD))
    return fallback if fallback > 0 else DEFAULT_SIZING_PORTFOLIO_USD


def resolve_deploy_cap_for_sizing(
    settings_cap: float | None,
    account_total: float | None,
) -> float:
    """Single source of truth: operator cap, never above cash; never $10k over a $250 setting.

    - both positive → min(cap, account)
    - cap > 0, account 0 → use cap (paper proposals)
    - cap 0, account > 0 → use account (do not size vs phantom $10k)
    - both 0 → fallback for brand-new users
    """
    from app.services.portfolio.cap_limit import clamp_cap_to_balance

    cap = max(0.0, float(settings_cap or 0.0))
    total = max(0.0, float(account_total or 0.0))
    if cap > 0 and total > 0:
        return clamp_cap_to_balance(cap, total)
    if cap > 0:
        return round(cap, 2)
    if total > 0:
        return round(total, 2)
    return resolve_portfolio_size_usd(0.0)


def _is_tradeable_slot(maneuver: Any) -> bool:
    if getattr(maneuver, "is_no_trade", False):
        return False
    st = getattr(maneuver, "strategy_type", None)
    if st is None:
        return True
    token = getattr(st, "value", st)
    return str(token).lower() != "no_trade"


def deploy_bounds(deploy_cap: float) -> tuple[float, float, float]:
    """per-name USD, book USD, min ticket USD."""
    cap = max(0.0, float(deploy_cap or 0.0))
    per_name = cap * float(settings.MAX_POSITION_PCT) / 100.0
    if settings.MAX_NOTIONAL_PER_POSITION_USD and settings.MAX_NOTIONAL_PER_POSITION_USD > 0:
        per_name = min(per_name, float(settings.MAX_NOTIONAL_PER_POSITION_USD))
    per_name = min(cap, per_name)
    max_book = cap * float(settings.MAX_PORTFOLIO_EXPOSURE_PCT) / 100.0
    return per_name, max_book, min_proposal_notional_usd(cap)


def _conviction_scores(maneuvers: Sequence[Any]) -> list[float]:
    scores: list[float] = []
    for m in maneuvers:
        conf = float(getattr(m, "confidence", 0.0) or 0.0)
        scores.append(max(0.0, min(1.0, conf)))
    return scores


def capped_conviction_weights(scores: list[float], *, name_cap_frac: float) -> list[float]:
    """Best idea → name cap; others scale by conviction/peak. Leftover stays cash.

    Do not normalize to 1.0 then clip: that flattens similar scores onto the 10% name cap.
    """
    n = len(scores)
    if n == 0:
        return []
    cap_f = min(1.0, max(0.0, float(name_cap_frac)))
    w = [max(0.0, float(s)) for s in scores]
    peak = max(w) if w else 0.0
    if peak <= 0:
        return [0.0] * n
    return [cap_f * (x / peak) for x in w]


def apply_maneuver_notional(maneuver: Any, new_usd: float, *, deploy_cap: float | None = None) -> None:
    """Rewrite size and proportional PnL / plan text."""
    new_usd = round(max(0.0, float(new_usd)), 2)
    old = float(getattr(maneuver, "position_size_usd", 0.0) or 0.0)
    if old > 1e-9:
        factor = new_usd / old
        for attr in ("expected_pnl_low", "expected_pnl_high"):
            val = getattr(maneuver, attr, None)
            if val is not None:
                setattr(maneuver, attr, round(float(val) * factor, 2))
    cap = float(deploy_cap) if deploy_cap is not None and float(deploy_cap) > 0 else 0.0
    if cap > 0:
        maneuver.risk_percent = round(100.0 * new_usd / cap, 4)
    elif old > 1e-9:
        rp = float(getattr(maneuver, "risk_percent", 0.0) or 0.0)
        maneuver.risk_percent = round(rp * (new_usd / old), 4)
    maneuver.position_size_usd = new_usd
    plan = getattr(maneuver, "execution_plan", None)
    if plan and new_usd > 0:
        maneuver.execution_plan = (
            f"{str(plan).split('Размер:')[0].rstrip()} Размер: ${new_usd:,.0f}."
        )


def _mark_no_trade(maneuver: Any, reason: str, *, deploy_cap: float | None = None) -> None:
    if not hasattr(maneuver, "__table__"):
        maneuver.is_no_trade = True
    current = getattr(maneuver, "strategy_type", None)
    if current is not None and not isinstance(current, str):
        from app.db.models import StrategyType

        maneuver.strategy_type = StrategyType.NO_TRADE
    else:
        maneuver.strategy_type = "no_trade"
    if hasattr(maneuver, "rationale"):
        maneuver.rationale = reason
    apply_maneuver_notional(maneuver, 0.0, deploy_cap=deploy_cap)


def _apply_construction_book(active: Sequence[Any], cap: float, *, user_id: str = "paper") -> bool:
    """Construction no longer overwrites tickets. Halt lives on the live order path."""
    del active, cap, user_id
    return False


def allocate_deploy_budget(
    maneuvers: list[Any],
    deploy_cap: float,
    *,
    exposure_pct: float | None = None,
    max_position_pct: float | None = None,
    user_id: str = "paper",
) -> list[Any]:
    """Split exposure budget by confidence. Better idea → larger notional, never above name cap."""
    cap = max(0.0, float(deploy_cap or 0.0))
    try:
        from app.services.platform_desk.mandate import load_ips

        ips_cap = load_ips(user_id).deploy_cap
        if ips_cap and float(ips_cap) > 0 and cap > 0:
            cap = min(cap, float(ips_cap))
    except Exception as exc:
        logger.warning("IPS load failed; refuse sizing", user_id=user_id, error=str(exc)[:200])
        for m in maneuvers:
            if _is_tradeable_slot(m):
                _mark_no_trade(m, "нет данных: IPS unavailable", deploy_cap=cap)
        return maneuvers
    exp = float(exposure_pct if exposure_pct is not None else settings.MAX_PORTFOLIO_EXPOSURE_PCT)
    pos_pct = float(max_position_pct if max_position_pct is not None else settings.MAX_POSITION_PCT)
    budget = cap * exp / 100.0
    per_name = cap * pos_pct / 100.0
    if settings.MAX_NOTIONAL_PER_POSITION_USD and settings.MAX_NOTIONAL_PER_POSITION_USD > 0:
        per_name = min(per_name, float(settings.MAX_NOTIONAL_PER_POSITION_USD))
    min_ticket = min_proposal_notional_usd(cap)

    active = [m for m in maneuvers if _is_tradeable_slot(m)]
    if not active or cap <= 0 or budget <= 0:
        return maneuvers

    name_frac = min(1.0, per_name / cap) if cap > 0 else 1.0
    weights = capped_conviction_weights(_conviction_scores(active), name_cap_frac=name_frac)
    halted = _apply_construction_book(active, cap, user_id=user_id)
    if not halted:
        for m, w in zip(active, weights):
            usd = round(min(cap * w, per_name, cap), 2)
            if usd + 1e-6 < min_ticket:
                _mark_no_trade(
                    m,
                    f"Слот ${usd:,.0f} меньше минимума ${min_ticket:,.0f} "
                    f"при капе ${cap:,.0f} — не предлагать.",
                    deploy_cap=cap,
                )
                continue
            apply_maneuver_notional(m, usd, deploy_cap=cap)

    enforce_hard_deploy_caps(maneuvers, cap, exposure_pct=exp, max_position_pct=pos_pct)
    try:
        from app.services.platform_desk.mandate import apply_mandate

        apply_mandate(maneuvers, user_id=user_id, deploy_cap=cap)
    except Exception as exc:
        logger.warning("apply_mandate failed; refuse tickets", user_id=user_id, error=str(exc)[:200])
        for m in maneuvers:
            if _is_tradeable_slot(m):
                _mark_no_trade(m, "нет данных: mandate unavailable", deploy_cap=cap)
    try:
        from app.services.ops_desk.audit_size import record as audit_record

        tradeable = [m for m in maneuvers if _is_tradeable_slot(m)]
        veto = [str(getattr(m, "rationale", "") or "")[:80] for m in maneuvers if not _is_tradeable_slot(m)]
        audit_record(
            deploy_cap=cap,
            weights=[
                (str(getattr(m, "ticker", "")), float(getattr(m, "position_size_usd", 0.0) or 0.0) / cap if cap else 0.0)
                for m in tradeable
            ],
            veto=veto,
            extra={"source": "allocate"},
        )
    except Exception as exc:
        logger.warning("allocate audit_record failed", error=str(exc)[:200])
    return maneuvers


def enforce_hard_deploy_caps(
    maneuvers: list[Any],
    deploy_cap: float,
    *,
    exposure_pct: float | None = None,
    max_position_pct: float | None = None,
) -> list[Any]:
    """Invariant: each name ≤ % cap, sum(tradeable) ≤ exposure, none > full cap."""
    cap = max(0.0, float(deploy_cap or 0.0))
    if cap <= 0:
        return maneuvers
    exp = float(exposure_pct if exposure_pct is not None else settings.MAX_PORTFOLIO_EXPOSURE_PCT)
    pos_pct = float(max_position_pct if max_position_pct is not None else settings.MAX_POSITION_PCT)
    per_name = min(cap, cap * pos_pct / 100.0)
    if settings.MAX_NOTIONAL_PER_POSITION_USD and settings.MAX_NOTIONAL_PER_POSITION_USD > 0:
        per_name = min(per_name, float(settings.MAX_NOTIONAL_PER_POSITION_USD))
    max_book = cap * exp / 100.0
    min_ticket = min_proposal_notional_usd(cap)

    tradeable = [m for m in maneuvers if _is_tradeable_slot(m)]
    for m in tradeable:
        usd = float(getattr(m, "position_size_usd", 0.0) or 0.0)
        if usd > per_name + 1e-6 or usd > cap + 1e-6:
            apply_maneuver_notional(m, min(usd, per_name, cap), deploy_cap=cap)

    tradeable = [m for m in maneuvers if _is_tradeable_slot(m)]
    total = sum(float(getattr(m, "position_size_usd", 0.0) or 0.0) for m in tradeable)
    if total > max_book + 1e-6 and total > 0:
        scale = max_book / total
        for m in tradeable:
            apply_maneuver_notional(
                m,
                float(m.position_size_usd) * scale,
                deploy_cap=cap,
            )

    for m in list(tradeable):
        usd = float(getattr(m, "position_size_usd", 0.0) or 0.0)
        if usd + 1e-6 < min_ticket:
            _mark_no_trade(
                m,
                f"Слот ${usd:,.0f} меньше минимума ${min_ticket:,.0f} "
                f"при капе ${cap:,.0f} — не предлагать.",
                deploy_cap=cap,
            )

    return maneuvers
