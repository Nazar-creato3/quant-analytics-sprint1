"""One execution plan: SOR + Cartea schedule + risk-aligned brackets."""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from app.services.execution.bracket_risk import align_with_engine
from app.services.execution.schedule import build_schedule
from app.services.execution.scorecard import build_scorecards
from app.services.execution.sor import pick_venue


def plan_execution(
    *,
    ticker: str,
    side: str,
    qty: float,
    entry: float,
    atr: float,
    keyed_venues: Sequence[str],
    fills: Sequence[Mapping[str, Any]] = (),
    adv_qty: float = 0.0,
    stop_loss: float | None = None,
    take_profit: float | None = None,
    portfolio_size: float = 250.0,
    bid: float | None = None,
    ask: float | None = None,
    volume_profile: Sequence[float] | None = None,
    kind: str = "twap",
    paper_ok: bool = True,
) -> dict[str, Any]:
    cards = build_scorecards(list(fills))
    pick = pick_venue(ticker, keyed=keyed_venues, fills=fills, paper_ok=paper_ok, cards=cards)
    br = align_with_engine(
        ticker=ticker,
        side=side,
        entry=entry,
        atr=atr,
        stop_loss=stop_loss,
        take_profit=take_profit,
        portfolio_size=portfolio_size,
    )
    sched = build_schedule(
        qty,
        adv_qty=adv_qty,
        kind=kind,
        volume_profile=volume_profile,
        bid=bid,
        ask=ask,
        direction="short" if str(side).lower() in {"sell", "short"} else "long",
        atr_pct=(atr / entry) if entry > 0 and atr > 0 else None,
    )
    return {
        "ticker": ticker.upper(),
        "venue": pick.venue,
        "route_reason": pick.reason,
        "fallbacks": list(pick.fallbacks),
        "scorecards": {k: v.score for k, v in cards.items() if v.n},
        "bracket": {
            "ok": br.ok,
            "stop_loss": br.stop_loss,
            "take_profit": br.take_profit,
            "aligned": br.aligned,
            "reasons": list(br.reasons),
        },
        "schedule": {
            "kind": sched.kind,
            "clipped_qty": sched.clipped_qty,
            "n": len(sched.children),
            "notes": list(sched.notes),
            "children": [
                {"seq": c.seq, "qty": c.qty, "wait_seconds": c.wait_seconds, "mult": c.size_mult}
                for c in sched.children
            ],
        },
        "allow": br.ok and sched.clipped_qty > 0,
    }
