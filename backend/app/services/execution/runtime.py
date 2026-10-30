"""Apply SOR / Cartea schedule / risk brackets on a live OrderRequest."""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from app.services.execution.adapter import OrderRequest
from app.services.execution.bracket_risk import align_with_engine
from app.services.execution.fill_tape import append_fill
from app.services.execution.schedule import build_schedule
from app.services.execution.sor import pick_venue
from app.services.risk.portfolio_sizing import resolve_deploy_cap_for_sizing


def volume_profile_from_bars(volumes: list[float] | None, n: int) -> list[float] | None:
    if not volumes or n <= 0:
        return None
    chunk = max(1, len(volumes) // n)
    weights: list[float] = []
    for i in range(n):
        sl = volumes[i * chunk : (i + 1) * chunk] if i < n - 1 else volumes[i * chunk :]
        weights.append(float(sum(sl)))
    if sum(weights) <= 0:
        return None
    return weights


def prepare_request(
    req: OrderRequest,
    *,
    adv_qty: float = 0.0,
    atr: float | None = None,
    volumes: list[float] | None = None,
    bid: float | None = None,
    ask: float | None = None,
    kind: str = "twap",
    portfolio_size: float | None = None,
) -> tuple[OrderRequest, dict[str, Any]]:
    """Clip qty (Cartea) and snap SL/TP to the risk engine. Does not sleep (not HFT)."""
    cap = resolve_deploy_cap_for_sizing(portfolio_size, None)
    entry = float(req.limit_price or req.stop_price or 0.0)
    atr_v = float(atr) if atr and atr > 0 else (
        abs(entry - float(req.stop_loss)) / 2.0 if entry and req.stop_loss else 0.0
    )
    meta: dict[str, Any] = {}
    sl, tp = req.stop_loss, req.take_profit
    if entry > 0 and atr_v > 0 and (sl or tp):
        chk = align_with_engine(
            ticker=req.ticker,
            side=req.side,
            entry=entry,
            atr=atr_v,
            stop_loss=sl,
            take_profit=tp,
            portfolio_size=cap or 250.0,
        )
        sl, tp = chk.stop_loss, chk.take_profit
        meta["bracket"] = {"ok": chk.ok, "aligned": chk.aligned, "reasons": list(chk.reasons)}
        if not chk.ok:
            meta["reject"] = "bracket_inconsistent"
            return req, meta
    n = 6
    sched = build_schedule(
        float(req.qty),
        adv_qty=adv_qty,
        n_slices=n,
        kind=kind,
        volume_profile=volume_profile_from_bars(volumes, n),
        bid=bid,
        ask=ask,
        direction="short" if str(req.side).lower() in {"sell", "short"} else "long",
        atr_pct=(atr_v / entry) if entry > 0 and atr_v > 0 else None,
    )
    meta["schedule"] = {
        "kind": sched.kind,
        "clipped_qty": sched.clipped_qty,
        "n": len(sched.children),
        "notes": list(sched.notes),
        "children": [{"seq": c.seq, "qty": c.qty, "wait_seconds": c.wait_seconds} for c in sched.children],
    }
    if sched.clipped_qty <= 0:
        meta["reject"] = sched.notes[0] if sched.notes else "schedule_empty"
        return req, meta
    new = replace(req, qty=sched.clipped_qty, stop_loss=sl, take_profit=tp)
    return new, meta


def record_result(req: OrderRequest, result: Any, *, venue: str, arrival: float | None = None) -> None:
    append_fill(
        {
            "venue": venue,
            "symbol": req.ticker,
            "side": req.side,
            "status": getattr(result, "status", None),
            "arrival_price": arrival or req.limit_price or getattr(result, "filled_price", None),
            "fill_price": getattr(result, "filled_price", None),
            "qty": getattr(result, "filled_qty", None) or req.qty,
            "mode": "paper" if venue == "paper" else "live",
        }
    )


def choose_venue(ticker: str, *, keyed: list[str], paper_ok: bool) -> str:
    from app.services.execution.fill_tape import load_fills

    pick = pick_venue(ticker, keyed=keyed, fills=load_fills(), paper_ok=paper_ok)
    return pick.venue
