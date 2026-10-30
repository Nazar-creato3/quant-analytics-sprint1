"""End-to-end book construction. Cap first, then optimizer, vol, TCM, tax, sleeves."""
from __future__ import annotations

from dataclasses import asdict
from datetime import date
from typing import Any, Mapping, Sequence

from app.core.logging import get_logger
from app.services.construction.caps import envelope
from app.services.construction.compliance import screen
from app.services.construction.optimizer import Constraints, NameSpec, optimize
from app.services.construction.rebalance import RebalancePolicy, plan as rebalance_plan
from app.services.construction.risk_model import blend_cov, decompose_book, gaussian_cvar, tracking_error
from app.services.construction.sleeve_nav import new_trade_leg, pending_cash, settled_cash, split_account_nav
from app.services.construction.tax_lots import plan_open
from app.services.construction.tcm import filter_by_edge
from app.services.construction.vol_budget import NameRisk, scale_book_to_vol_target

logger = get_logger(__name__)


def _positive(raw: Any) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value <= 0:
        return None
    return value


def _refused_book(
    *,
    settings_cap: float | None,
    account_total: float | None,
    user_id: str,
    account: str,
    sleeve: str,
    mode: str,
    reason: str,
) -> dict[str, Any]:
    env = envelope(settings_cap, account_total)
    return {
        "deploy_cap": env.deploy_cap,
        "cash_buffer": env.cash_buffer_frac,
        "max_book": env.max_book,
        "book_usd": 0.0,
        "cash_usd": round(env.deploy_cap, 2),
        "holdings": [],
        "mode": mode,
        "optimizer_notes": [],
        "vol_budget": {},
        "tcm": [],
        "rejected": [reason],
        "rebalance": {"due": False, "reason": reason, "trades": []},
        "sleeves": [],
        "user_id": user_id,
        "account": account,
        "sleeve": sleeve,
        "risk_book": {},
        "compliance": [],
        "settlement": {},
        "ops": None,
        "data_status": "нет данных",
    }


def _edge(row: Mapping[str, Any]) -> float:
    for key in ("edge", "expected_excess", "p_beat_21", "p_beat_5", "p_beat_20"):
        v = row.get(key)
        if v is None:
            continue
        try:
            x = float(v)
        except (TypeError, ValueError):
            continue
        if key.startswith("p_beat"):
            return max(0.0, x - 0.5) * 0.04  # map 0.75 → ~1% expected excess
        return x
    return 0.0


def _ops_snapshot(
    *,
    holdings: list[dict[str, Any]],
    specs: Sequence[NameSpec],
    aligned: Sequence[Mapping[str, Any]],
    settings_cap: float | None,
    account_total: float | None,
    hist,
    spy,
    fills_by_symbol,
    ff_rows,
    day_pnl_frac: float,
    dd_frac: float,
    last_bar,
    broker_connected,
    day_trades_5d: int,
    would_day_trade: bool,
    stale_hours: float,
    user_id: str,
    account: str,
    sleeve: str,
) -> dict[str, Any] | None:
    try:
        from app.services.ops_desk.desk import evaluate_desk
    except Exception as exc:
        logger.warning("ops desk import failed; construction ops stay empty", error=str(exc)[:200])
        return None
    by = {s.symbol: (s, aligned[i] if i < len(aligned) else {}) for i, s in enumerate(specs)}
    symbols = [h["symbol"] for h in holdings]
    weights = [h["weight"] for h in holdings]
    notionals = [h["notional_usd"] for h in holdings]
    betas = [float(by[s][1].get("beta") or by[s][0].beta) if s in by else 1.0 for s in symbols]
    sectors = [h.get("sector") or "UNK" for h in holdings]
    adv = [float(by[s][0].adv_usd) if s in by else 0.0 for s in symbols]
    countries = [str(by[s][1].get("country") or by[s][0].country) if s in by else "US" for s in symbols]
    try:
        ops = evaluate_desk(
            symbols=symbols,
            weights=weights,
            notionals=notionals,
            settings_cap=settings_cap,
            account_total=account_total,
            hist=hist,
            spy=spy,
            betas=betas,
            sectors=sectors,
            adv=adv,
            countries=countries,
            fills_by_symbol=fills_by_symbol,
            ff_rows=ff_rows,
            day_pnl_frac=day_pnl_frac,
            dd_frac=dd_frac,
            last_bar=last_bar,
            broker_connected=broker_connected,
            day_trades_5d=day_trades_5d,
            would_day_trade=would_day_trade,
            stale_hours=stale_hours,
            user_id=user_id,
            account=account,
            sleeve=sleeve,
        )
    except Exception as exc:
        logger.warning("ops desk evaluate failed; construction ops stay empty", error=str(exc)[:200])
        return None
    return ops


def construct_sleeve(
    rows: Sequence[Mapping[str, Any]],
    *,
    settings_cap: float | None,
    account_total: float | None = None,
    user_id: str = "paper",
    account: str = "paper",
    sleeve: str = "retail_long_only",
    mode: str = "conviction",
    hist: Mapping[str, Sequence[float]] | None = None,
    fills_by_symbol: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    as_of: date | None = None,
    last_rebalance: date | None = None,
    current_weights: Mapping[str, float] | None = None,
    recent_loss_sales: Sequence[tuple[str, date, str, str]] = (),
    target_ann_vol: float = 0.12,
    restricted: Sequence[str] = (),
    blocked_countries: Sequence[str] = (),
    bench_weights: Sequence[float] | None = None,
    min_adv_usd: float = 0.0,
    spy: Sequence[float] | None = None,
    ff_rows: Sequence[Mapping[str, Any]] | None = None,
    day_pnl_frac: float = 0.0,
    dd_frac: float = 0.0,
    last_bar=None,
    broker_connected: bool | None = True,
    day_trades_5d: int = 0,
    would_day_trade: bool = False,
    stale_hours: float = 36.0,
) -> dict[str, Any]:
    try:
        from app.services.platform_desk.mandate import cached_headlines, load_ips, ticker_blocked

        ips = load_ips(user_id)
        if ips.deploy_cap and float(ips.deploy_cap) > 0:
            if settings_cap and float(settings_cap) > 0:
                settings_cap = min(float(settings_cap), float(ips.deploy_cap))
            else:
                settings_cap = float(ips.deploy_cap)
        banned = list(restricted) if restricted else list(ips.banned_tickers)
        for r in rows:
            sym = str(r.get("symbol") or "").upper()
            text = " ".join(
                [
                    str(r.get("note") or ""),
                    str(r.get("catalyst") or ""),
                    cached_headlines(sym),
                ]
            )
            if ticker_blocked(sym, ips, headlines=text):
                banned.append(sym)
        restricted = tuple(dict.fromkeys(str(x).upper() for x in banned if str(x).strip()))
    except Exception as exc:
        logger.warning("mandate unavailable; refuse construction", user_id=user_id, error=str(exc)[:200])
        return _refused_book(
            settings_cap=settings_cap,
            account_total=account_total,
            user_id=user_id,
            account=account,
            sleeve=sleeve,
            mode=mode,
            reason="нет данных",
        )
    env = envelope(settings_cap, account_total)
    specs: list[NameSpec] = []
    aligned: list[Mapping[str, Any]] = []
    skip_rejected: list[str] = []
    for r in rows:
        sym = str(r.get("symbol") or "").upper()
        if not sym:
            continue
        vol = _positive(r.get("vol") if r.get("vol") is not None else r.get("vol_ann"))
        px = _positive(r.get("price"))
        if vol is None or px is None:
            skip_rejected.append(f"{sym}:нет данных")
            continue
        aligned.append(r)
        specs.append(
            NameSpec(
                symbol=sym,
                mu=float(r.get("mu") or _edge(r)),
                vol=vol,
                sector=str(r.get("sector") or "UNK"),
                adv_usd=float(r.get("adv_usd") or 0.0),
                current_w=float((current_weights or {}).get(sym) or r.get("current_w") or 0.0),
                conviction=max(0.0, _edge(r) or float(r.get("confidence") or 0.0)),
                beta=float(r.get("beta") or 1.0),
                country=str(r.get("country") or "US"),
                restricted=bool(r.get("restricted")) or sym in {x.upper() for x in restricted},
                size=float(r.get("size") or 0.0),
            )
        )
    if not specs:
        empty = _refused_book(
            settings_cap=settings_cap,
            account_total=account_total,
            user_id=user_id,
            account=account,
            sleeve=sleeve,
            mode=mode,
            reason="нет данных",
        )
        empty["rejected"] = skip_rejected or ["нет данных"]
        return empty
    allow, breaches = screen(
        [s.symbol for s in specs],
        restricted=restricted,
        adv=[s.adv_usd for s in specs],
        min_adv_usd=min_adv_usd,
        countries=[s.country for s in specs],
        blocked_countries=blocked_countries,
        long_only=sleeve != "cross_sectional",
    )
    cons = Constraints(
        name_cap=env.name_frac,
        exposure_cap=env.exposure_frac,
        cash_buffer=env.cash_buffer_frac,
        long_only=sleeve != "cross_sectional",
        restricted=tuple(str(x).upper() for x in restricted),
    )
    opt = optimize(
        specs,
        mode=mode,  # type: ignore[arg-type]
        hist=hist,
        cons=cons,
        deploy_cap=env.deploy_cap,
        bench_weights=bench_weights,
    )
    weights = list(opt.weights)
    symbols = [s.symbol for s in specs]

    # Vol target at book level
    risks = [
        NameRisk(
            symbol=s.symbol,
            weight=weights[i] if i < len(weights) else 0.0,
            price=float(aligned[i]["price"]),
            atr=float(aligned[i].get("atr") or max(s.vol, 0.01) * 100.0 / (252**0.5)),
            vol_ann=s.vol,
        )
        for i, s in enumerate(specs)
    ]
    risk_book = blend_cov(
        [s.symbol for s in specs],
        [s.vol for s in specs],
        hist=hist,
        sectors=[s.sector for s in specs],
        size=[s.size for s in specs],
    )
    weights, vb = scale_book_to_vol_target(
        weights,
        risks,
        equity_usd=env.deploy_cap,
        target_ann=target_ann_vol,
        max_scale=1.0,
        cov=risk_book.cov if risk_book.cov.size else None,
    )
    tot_vol = sum(abs(w) for w in weights)
    if tot_vol > env.exposure_frac + 1e-12:
        weights = [w * env.exposure_frac / tot_vol for w in weights]

    # TCM reject
    notionals = [abs(w) * env.deploy_cap for w in weights]
    edges = [_edge(r) for r in aligned]
    advs = [s.adv_usd for s in specs]
    ok, quotes = filter_by_edge(
        symbols, edges=edges, notionals=notionals, adv=advs, fills_by_symbol=fills_by_symbol
    )
    rejected: list[str] = list(skip_rejected)
    day = as_of or date.today()
    for i, sym in enumerate(symbols):
        allow_tax, tax_reason = plan_open(
            symbol=sym,
            as_of=day,
            account=account,
            sleeve_id=sleeve,
            recent_loss_sales=recent_loss_sales,
            taxable=True,  # paper-first awareness; same rule as taxable live
        )
        if i < len(allow) and not allow[i]:
            weights[i] = 0.0
            rejected.append(f"{sym}:compliance")
            continue
        if not ok[i] or not allow_tax:
            weights[i] = 0.0
            rejected.append(f"{sym}:{'cost' if not ok[i] else tax_reason}")

    # Re-apply exposure after zeros
    tot = sum(abs(w) for w in weights)
    if tot > env.exposure_frac:
        weights = [w * env.exposure_frac / tot for w in weights]

    # Notionals + hard cap
    holdings = []
    book_usd = 0.0
    for i, s in enumerate(specs):
        usd = round(abs(weights[i]) * env.deploy_cap, 2)
        usd = min(usd, env.per_name, env.deploy_cap)
        if usd + 1e-6 < env.min_ticket:
            usd = 0.0
            weights[i] = 0.0
        if book_usd + usd > env.max_book + 1e-6:
            usd = 0.0
            weights[i] = 0.0
        if usd > 0:
            book_usd += usd
            holdings.append(
                {
                    "symbol": s.symbol,
                    "weight": round(weights[i], 6),
                    "notional_usd": usd,
                    "sector": s.sector,
                }
            )

    rb = rebalance_plan(
        symbols,
        [s.current_w for s in specs],
        weights,
        as_of=day,
        last=last_rebalance,
        policy=RebalancePolicy(cash_buffer=env.cash_buffer_frac),
    )
    sleeves = split_account_nav(
        user_id=user_id,
        account=account,
        nav=float(account_total or env.deploy_cap),
        deploy_cap=env.deploy_cap,
        sleeve_frac={
            "retail_long_only": env.exposure_frac if sleeve == "retail_long_only" else 0.0,
            "cross_sectional": env.exposure_frac if sleeve == "cross_sectional" else 0.0,
            "cash": env.cash_buffer_frac,
        },
    )
    payload = {
        "deploy_cap": env.deploy_cap,
        "cash_buffer": env.cash_buffer_frac,
        "max_book": env.max_book,
        "book_usd": round(book_usd, 2),
        "cash_usd": round(max(0.0, env.deploy_cap - book_usd), 2),
        "holdings": holdings,
        "mode": opt.mode,
        "optimizer_notes": list(opt.notes),
        "vol_budget": {
            "target": vb.target_ann,
            "forecast": vb.forecast_ann,
            "scale": vb.scale,
            "turtle_units": vb.units,
        },
        "tcm": [asdict(q) for q in quotes],
        "rejected": rejected,
        "rebalance": {
            "due": rb.due,
            "reason": rb.reason,
            "trades": [list(t) for t in rb.trades],
        },
        "sleeves": [
            {"user_id": s.user_id, "account": s.account, "sleeve": s.sleeve, "nav": s.nav, "deploy_cap": s.deploy_cap}
            for s in sleeves
        ],
        "user_id": user_id,
        "account": account,
        "sleeve": sleeve,
        "risk_book": {
            **decompose_book(weights, risk_book),
            "te": tracking_error(weights, bench_weights or [0.0] * len(weights), risk_book.cov) if specs else 0.0,
            "cvar": gaussian_cvar(vb.forecast_ann),
            "port_beta": opt.port_beta,
            "notes": list(risk_book.notes),
        },
        "compliance": [{"symbol": b.symbol, "rule": b.rule, "detail": b.detail} for b in breaches],
        "settlement": {
            "t_plus": 1,
            "pending_cash": pending_cash(
                [new_trade_leg(amount=-h["notional_usd"], as_of=day, kind="buy_debit", user_id=user_id, account=account, sleeve=sleeve) for h in holdings],
                as_of=day,
                user_id=user_id,
                account=account,
                sleeve=sleeve,
            ),
            "settled_cash": settled_cash([], as_of=day, user_id=user_id, account=account, sleeve=sleeve),
        },
        "ops": None,
    }
    ops = _ops_snapshot(
        holdings=holdings,
        specs=specs,
        aligned=aligned,
        settings_cap=settings_cap,
        account_total=account_total,
        hist=hist,
        spy=spy,
        fills_by_symbol=fills_by_symbol,
        ff_rows=ff_rows,
        day_pnl_frac=day_pnl_frac,
        dd_frac=dd_frac,
        last_bar=last_bar,
        broker_connected=broker_connected,
        day_trades_5d=day_trades_5d,
        would_day_trade=would_day_trade,
        stale_hours=stale_hours,
        user_id=user_id,
        account=account,
        sleeve=sleeve,
    )
    payload["ops"] = ops
    if ops and (ops.get("kills") or {}).get("halt"):
        payload["holdings"] = []
        payload["book_usd"] = 0.0
        payload["cash_usd"] = round(env.deploy_cap, 2)
        payload["rejected"] = list(rejected) + ["kill_switch"]
    return payload
