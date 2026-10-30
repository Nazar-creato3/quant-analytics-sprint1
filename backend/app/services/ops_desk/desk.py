"""Desk D: risk + compliance + ops in one snapshot."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Any, Mapping, Sequence

from app.services.ops_desk.audit_size import record as audit_record
from app.services.ops_desk.disaster import seal_deploy_floor
from app.services.ops_desk.factors import factor_book
from app.services.ops_desk.kills import evaluate_kills
from app.services.ops_desk.pretrade import check as pretrade_check
from app.services.ops_desk.realtime import book_risk
from app.services.ops_desk.stress import run_all
from app.services.ops_desk.tca_post import book_tca


def evaluate_desk(
    *,
    symbols: Sequence[str],
    weights: Sequence[float],
    notionals: Sequence[float],
    settings_cap: float | None,
    account_total: float | None = None,
    hist: Mapping[str, Sequence[float]] | None = None,
    spy: Sequence[float] | None = None,
    betas: Sequence[float] | None = None,
    sectors: Sequence[str] = (),
    sides: Sequence[str] = (),
    adv: Sequence[float] = (),
    countries: Sequence[str] = (),
    fills_by_symbol: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    ff_rows: Sequence[Mapping[str, Any]] | None = None,
    day_pnl_frac: float = 0.0,
    dd_frac: float = 0.0,
    last_bar: datetime | None = None,
    broker_connected: bool | None = True,
    day_trades_5d: int = 0,
    would_day_trade: bool = False,
    stale_hours: float = 36.0,
    user_id: str = "paper",
    account: str = "paper",
    sleeve: str = "retail_long_only",
    audit_path=None,
    seal_path=None,
) -> dict[str, Any]:
    book_usd = float(sum(abs(float(x)) for x in notionals))
    br = book_risk(weights, symbols, hist=hist)
    fb = factor_book(weights, symbols, sectors=sectors, hist=hist, spy=spy, ff_rows=ff_rows)
    bvec = list(betas) if betas is not None else [1.0] * len(weights)
    stresses = run_all(weights, bvec, symbols=symbols)
    halt, kills = evaluate_kills(
        day_pnl_frac=day_pnl_frac,
        dd_frac=dd_frac,
        last_bar=last_bar,
        broker_connected=broker_connected,
        stale_hours=stale_hours,
    )
    pre = pretrade_check(
        settings_cap=settings_cap,
        account_total=account_total,
        proposed_book_usd=book_usd,
        symbols=symbols,
        sides=sides or ("long",) * len(symbols),
        notionals=notionals,
        adv=adv,
        countries=countries,
        day_trades_5d=day_trades_5d,
        would_day_trade=would_day_trade,
    )
    tca = [asdict(x) for x in book_tca(fills_by_symbol or {})]
    veto = list(pre.reasons)
    if halt:
        veto.extend(k.name for k in kills if k.tripped)
    wmap = {str(symbols[i]): float(weights[i]) for i in range(min(len(symbols), len(weights)))}
    audit = audit_record(
        deploy_cap=pre.deploy_cap,
        weights=wmap,
        veto=veto,
        user_id=user_id,
        account=account,
        sleeve=sleeve,
        dest=audit_path,
    )
    floor = seal_deploy_floor(settings_cap, account_total, dest=seal_path)
    return {
        "deploy_cap": pre.deploy_cap,
        "book_usd": round(book_usd, 2),
        "risk": asdict(br),
        "factors": {
            "hhi": fb.hhi,
            "max_name": fb.max_name,
            "max_sector": fb.max_sector,
            "spy_beta": fb.spy_beta,
            "ff": fb.ff,
            "notes": list(fb.notes),
        },
        "stress": [asdict(s) for s in stresses],
        "kills": {"halt": halt, "items": [asdict(k) for k in kills]},
        "pretrade": {
            "allow": pre.allow and not halt,
            "reasons": list(pre.reasons),
            "locate_ok": pre.locate_ok,
            "pdt_blocked": pre.pdt_blocked,
        },
        "tca": tca,
        "audit": {"ts": audit["ts"], "veto": audit["veto"], "deploy_cap": audit["deploy_cap"]},
        "dr_floor": floor["deploy_cap"],
        "veto": veto,
    }
