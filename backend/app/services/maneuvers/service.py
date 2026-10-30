"""Maneuver candidates from the user's profile and the prompt-36 target.

Paper only. A missing input skips that kind and records «нет данных».
Live execution is not started here.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime, timedelta
from decimal import ROUND_CEILING, ROUND_DOWN, Decimal
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

MODEL_VERSION = "maneuvers.v1"
NOTE = "это возвращает портфель к вашим правилам"
_MISSING = "нет данных"
_LIMIT_BONUS = Decimal(1)
_REAL_LABELS = {"trend_up", "trend_down", "range", "volatility", "crisis"}
_RISK_LABELS = {"crisis", "trend_down", "volatility"}


def load_maneuver_config() -> dict[str, Any]:
    raw = json.loads(Path(__file__).with_name("config.json").read_text(encoding="utf-8"))
    return {
        "max_active": int(raw["max_active"]),
        "ttl_hours": int(raw["ttl_hours"]),
        "price_move_pct": Decimal(str(raw["price_move_pct"])),
        "default_lot": Decimal(str(raw["default_lot"])),
    }


def maneuver_expired(
    maneuver: dict[str, Any],
    *,
    now: datetime,
    prices: dict[str, Decimal],
) -> tuple[bool, str]:
    """True when the clock passed expires_at or an anchor moved past the config threshold."""
    raw = str(maneuver.get("expires_at") or "")
    if not raw:
        return True, _MISSING
    exp = datetime.fromisoformat(raw)
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    if now >= exp:
        return True, "истёк срок"
    limit = Decimal(str((maneuver.get("expiry") or {}).get("price_move_pct") or "0"))
    for anchor in (maneuver.get("expiry") or {}).get("anchors") or []:
        ticker = str(anchor.get("ticker") or "")
        px = prices.get(ticker)
        if px is None or anchor.get("price") in (None, ""):
            continue
        base = Decimal(str(anchor["price"]))
        if base == 0:
            continue
        if abs(px - base) / abs(base) > limit:
            return True, "цена сдвинулась сверх порога"
    return False, ""


def select_maneuvers(
    candidates: list[dict[str, Any]],
    *,
    limit: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Highest profile score first. Same ticker in two maneuvers is a conflict. Cap is N."""
    ranked = sorted(candidates, key=lambda row: (-Decimal(str(row["score"])), str(row["kind"])))
    kept: list[dict[str, Any]] = []
    notes: list[dict[str, Any]] = []
    for cand in ranked:
        clash = next((row for row in kept if _shares_ticker(cand, row)), None)
        if clash is not None:
            notes.append(
                {
                    "kept_kind": clash["kind"],
                    "kept_score": clash["score"],
                    "dropped_kind": cand["kind"],
                    "dropped_score": cand["score"],
                    "reason": (
                        f"конфликт по {_shared_names(cand, clash)}: оставлен {clash['kind']} "
                        f"с оценкой {clash['score']}"
                    ),
                }
            )
            continue
        if len(kept) >= limit:
            notes.append(
                {
                    "dropped_kind": cand["kind"],
                    "dropped_score": cand["score"],
                    "reason": f"сверх лимита N={limit}: оставлены более высокие оценки",
                }
            )
            continue
        kept.append(cand)
    return kept, notes


def generate_maneuvers(
    *,
    user_id: str,
    mode: str = "paper",
    method: str = "equal_weight",
) -> dict[str, Any]:
    """Build, score, and cap paper maneuvers. Called from act_desk.propose."""
    cfg = load_maneuver_config()
    if mode != "paper":
        return {"items": [], "skipped": [{"kind": "live", "reason": "исполнение live выключено"}], "selection": [], "target": None}
    from app.services.investment_profile.service import get_profile

    profile = get_profile(user_id)
    if not profile:
        return {"items": [], "skipped": [{"kind": "profile", "reason": _MISSING}], "selection": [], "target": None}
    ctx = _context(user_id, mode, method, profile)
    found: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for kind, builder in (
        ("rebalance", _rebalance),
        ("reduce_weight", _concentration),
        ("risk_limit", _risk_limit),
        ("hedge", _hedge),
        ("tax_loss", _tax_loss),
        ("replace", _replace),
        ("regime", _regime),
        ("deposit", _deposit),
    ):
        cand, missing = _safe(kind, lambda builder=builder: builder(ctx, cfg))
        if cand is not None:
            from app.services.qa.feature_flags import is_enabled

            if is_enabled("qa_maneuver_control"):
                from app.services.maneuver_control.service import gate_candidate

                cand, blocked = gate_candidate(cand)
                if cand is None:
                    skipped.append({"kind": kind, "reason": blocked or _MISSING})
                    continue
            found.append(cand)
        elif missing:
            skipped.append({"kind": kind, "reason": missing})
    kept, notes = select_maneuvers(found, limit=int(cfg["max_active"]))
    kept_ids = {id(row) for row in kept}
    for row in kept:
        row["selection_note"] = "оставлен: оценка выше конфликтующих и внутри лимита N"
    for note in notes:
        dropped = next((row for row in found if row["kind"] == note.get("dropped_kind") and id(row) not in kept_ids), None)
        if dropped is not None:
            dropped["selection_note"] = note["reason"]
    return {"items": kept, "skipped": skipped, "selection": notes, "target": ctx.get("target")}


def _safe(kind: str, builder: Any) -> tuple[dict[str, Any] | None, str | None]:
    try:
        return builder()
    except Exception:
        logger.exception("maneuver kind=%s", kind)
        return None, _MISSING


def _context(user_id: str, mode: str, method: str, profile: dict[str, Any]) -> dict[str, Any]:
    from app.services.concentration.service import _trade_price, analyze_portfolio
    from app.services.portfolio_book.service import positions_for
    from app.services.risk_engine.service import compute_risk_for_user
    from app.services.target_portfolio.service import build_target

    positions = positions_for(user_id=user_id, mode=mode)  # type: ignore[arg-type]
    holdings: list[dict[str, Any]] = []
    book_px: dict[str, Decimal] = {}
    for pos in positions:
        if pos.ticker == "CASH" or pos.qty == 0:
            continue
        px = _trade_price(user_id, mode, pos.ticker)
        if px is None:
            continue
        book_px[pos.ticker.upper()] = px
        holdings.append(
            {
                "ticker": pos.ticker.upper(),
                "qty": abs(pos.qty),
                "price": px,
                "ccy": pos.ccy or "RUB",
                "value": abs(pos.qty) * px,
            }
        )
    try:
        target = build_target(user_id, mode=mode, method=method)
    except Exception:
        logger.exception("maneuver target")
        target = {"status": _MISSING, "reason": _MISSING, "weights": None, "orders": []}
    try:
        risk = compute_risk_for_user(user_id, mode)
    except Exception:
        logger.exception("maneuver risk")
        risk = {"var_95": None, "es_975": None}
    try:
        conc = analyze_portfolio(user_id=user_id, mode=mode)
    except Exception:
        logger.exception("maneuver concentration")
        conc = {"empty": True, "weights": {}, "hhi": None}
    return {
        "user_id": user_id,
        "mode": mode,
        "method": method,
        "profile": profile,
        "holdings": holdings,
        "book_px": book_px,
        "target": target,
        "risk": risk,
        "conc": conc,
        "nav": sum((row["value"] for row in holdings), Decimal(0)),
    }


def _rebalance(ctx: dict[str, Any], cfg: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    target = ctx["target"] or {}
    weights = target.get("weights")
    if target.get("status") != "ok" or not weights:
        return None, _MISSING
    nav: Decimal = ctx["nav"]
    if nav <= 0:
        return None, _MISSING
    current = {row["ticker"]: row["value"] / nav for row in ctx["holdings"]}
    orders: list[dict[str, Any]] = []
    gap = Decimal(0)
    names = set(weights) | set(current)
    for ticker in sorted(names):
        target_w = Decimal(str(weights.get(ticker) or "0"))
        cur_w = current.get(ticker, Decimal(0))
        gap += abs(target_w - cur_w)
        delta_value = nav * target_w - nav * cur_w
        quote = _quote(ticker, ctx["book_px"])
        if quote is None:
            continue
        raw = delta_value / quote["price"]
        qty = _lot_toward_zero(raw, cfg["default_lot"])
        if qty == 0:
            continue
        orders.append(_order(ticker, qty, quote))
    if not orders:
        if gap > 0 and any(_quote(t, ctx["book_px"]) is None for t in names):
            return None, _MISSING
        return None, None
    half = (gap / Decimal(2)).quantize(Decimal("0.0001"))
    return _pack(
        ctx,
        cfg,
        kind="rebalance",
        orders=orders,
        rationale=f"сдвиг долей к целевой структуре {format(half, 'f')}. {NOTE}",
        logic_key="maneuver_rebalance",
        logic_values={"gap": format(half, "f")},
        benefit=half,
        limit_breach=False,
    ), None


def _concentration(ctx: dict[str, Any], cfg: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    conc = ctx["conc"] or {}
    weights = conc.get("weights") or {}
    if conc.get("empty") or not weights or ctx["nav"] <= 0:
        return None, _MISSING
    limit = _frac((ctx["profile"].get("limits") or {}).get("max_position_pct") or ctx["profile"].get("max_position_pct"))
    if limit is None:
        return None, _MISSING
    orders: list[dict[str, Any]] = []
    worst_w = Decimal(0)
    worst_ticker = ""
    for ticker, raw in weights.items():
        weight = Decimal(str(raw))
        if weight <= limit:
            continue
        row = next((item for item in ctx["holdings"] if item["ticker"] == ticker.upper()), None)
        if row is None:
            continue
        price = row["price"]
        if limit >= 1:
            continue
        raw_qty = (row["value"] - limit * ctx["nav"]) / (price * (Decimal(1) - limit))
        qty = _lot_ceil(raw_qty, cfg["default_lot"], row["qty"])
        if qty <= 0:
            continue
        quote = _quote(ticker, ctx["book_px"])
        if quote is None:
            return None, _MISSING
        orders.append(_order(ticker, -qty, quote))
        if weight > worst_w:
            worst_w = weight
            worst_ticker = ticker.upper()
    if not orders:
        return None, None
    benefit = worst_w - limit
    return _pack(
        ctx,
        cfg,
        kind="reduce_weight",
        orders=orders,
        rationale=f"доля {worst_ticker} {format(worst_w, 'f')} выше правила {format(limit, 'f')}. {NOTE}",
        logic_key="act_rule",
        logic_values={"ticker": worst_ticker, "weight": f"{worst_w:.2f}", "limit": f"{limit:.2f}"},
        benefit=benefit,
        limit_breach=True,
        ticker=worst_ticker,
        qty=str(next(abs(Decimal(o["qty"])) for o in orders if o["ticker"] == worst_ticker)),
    ), None


def _risk_limit(ctx: dict[str, Any], cfg: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    risk = ctx["risk"] or {}
    var_now = risk.get("var_95")
    es_now = risk.get("es_975")
    if var_now is None and es_now is None:
        return None, _MISSING
    limits = ctx["profile"].get("limits") or {}
    var_lim = _frac(limits.get("var_95"))
    es_lim = _frac(limits.get("es_975"))
    if var_lim is None and es_lim is None:
        return None, _MISSING
    over_var = var_now is not None and var_lim is not None and Decimal(str(var_now)) > var_lim
    over_es = es_now is not None and es_lim is not None and Decimal(str(es_now)) > es_lim
    if not over_var and not over_es:
        return None, None
    if len(ctx["holdings"]) < 2:
        return None, _MISSING
    best: dict[str, Any] | None = None
    best_after = Decimal(1)
    for row in ctx["holdings"]:
        quote = _quote(row["ticker"], ctx["book_px"])
        if quote is None:
            continue
        qty = _lot_toward_zero(row["qty"], cfg["default_lot"])
        if qty <= 0:
            continue
        orders = [_order(row["ticker"], -qty, quote)]
        impact = _impact(ctx, orders)
        after = impact["delta"]["var_95"]["after"]
        if after is None:
            continue
        after_dec = Decimal(str(after))
        es_after = impact["delta"]["es_975"]["after"]
        inside = (var_lim is None or after_dec <= var_lim) and (
            es_lim is None or es_after is None or Decimal(str(es_after)) <= es_lim
        )
        if inside and (best is None or after_dec < best_after):
            shown = format(Decimal(str(var_now)).quantize(Decimal("0.0001")), "f")
            lim_txt = format(var_lim, "f") if var_lim is not None else format(es_lim or Decimal(0), "f")
            best = _pack(
                ctx,
                cfg,
                kind="risk_limit",
                orders=orders,
                rationale=f"VaR 95% {shown} выше лимита профиля {lim_txt}. {NOTE}",
                logic_key="maneuver_risk",
                logic_values={"var_now": shown, "limit": lim_txt},
                benefit=(Decimal(str(var_now)) - after_dec) if var_now is not None else Decimal(0),
                limit_breach=True,
                impact=impact,
            )
            best_after = after_dec
    if best is None:
        return None, _MISSING
    return best, None


def _hedge(ctx: dict[str, Any], cfg: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    allowed = [str(item).upper() for item in (ctx["profile"].get("allowed_hedge_tickers") or []) if str(item).strip()]
    if not allowed or not ctx["holdings"]:
        return None, _MISSING
    asset = max(ctx["holdings"], key=lambda row: row["value"])
    from app.services.quant_math.core import covariance, historical_volatility
    from app.services.risk_engine.series import get_series

    base = get_series(asset["ticker"])
    if len(base) < 8:
        return None, _MISSING
    chosen: tuple[str, Decimal] | None = None
    saw_series = False
    for ticker in allowed:
        if ticker == asset["ticker"]:
            continue
        series = get_series(ticker)
        if len(series) < 8:
            continue
        saw_series = True
        n = min(len(base), len(series))
        var_a = historical_volatility(base[-n:]) ** 2
        if var_a <= 0:
            continue
        beta = Decimal(str(covariance(series[-n:], base[-n:]) / var_a))
        if beta < 0:
            chosen = (ticker, beta)
            break
    if chosen is None:
        return None, None if saw_series else _MISSING
    ticker, beta = chosen
    quote = _quote(ticker, ctx["book_px"])
    if quote is None or quote["price"] <= 0:
        return None, _MISSING
    raw = (-beta) * asset["value"] / quote["price"]
    qty = _lot_toward_zero(raw, cfg["default_lot"])
    if qty <= 0:
        return None, None
    beta_txt = format(beta.quantize(Decimal("0.0001")), "f")
    return _pack(
        ctx,
        cfg,
        kind="hedge",
        orders=[_order(ticker, qty, quote)],
        rationale=f"бета {beta_txt} у {ticker}, инструмент разрешён профилем. {NOTE}",
        logic_key="maneuver_hedge",
        logic_values={"beta": beta_txt, "ticker": ticker},
        benefit=abs(beta),
        limit_breach=False,
    ), None


def _tax_loss(ctx: dict[str, Any], cfg: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    from app.services.act_desk.service import _open_tax_lots
    from app.services.portfolio_book.store import get_book
    from app.services.target_portfolio.tax import CITATION_214

    txns = get_book().transactions(user_id=ctx["user_id"], mode=ctx["mode"])  # type: ignore[arg-type]
    lots = _open_tax_lots(txns)
    if not lots:
        return None, _MISSING
    orders: list[dict[str, Any]] = []
    loss = Decimal(0)
    for lot in lots:
        quote = _quote(str(lot["ticker"]), ctx["book_px"])
        if quote is None or lot["qty"] <= 0:
            continue
        unit_cost = Decimal(str(lot["cost"])) / Decimal(str(lot["qty"]))
        if quote["price"] >= unit_cost:
            continue
        qty = _lot_toward_zero(Decimal(str(lot["qty"])), cfg["default_lot"])
        if qty <= 0:
            continue
        orders.append(_order(str(lot["ticker"]), -qty, quote))
        loss += (unit_cost - quote["price"]) * qty
    if not orders:
        if all(_quote(str(lot["ticker"]), ctx["book_px"]) is None for lot in lots):
            return None, _MISSING
        return None, None
    impact = _impact(ctx, orders)
    result = ((impact.get("tax") or {}).get("year") or {}).get("net_before_relief")
    if result in (None, ""):
        return None, _MISSING
    result_txt = format(Decimal(str(result)), "f")
    benefit = (loss / ctx["nav"]) if ctx["nav"] > 0 else Decimal(0)
    packed = _pack(
        ctx,
        cfg,
        kind="tax_loss",
        orders=orders,
        rationale=f"отрицательный результат {result_txt} внутри года. {CITATION_214} {NOTE}",
        logic_key="maneuver_tax",
        logic_values={"result": result_txt},
        benefit=benefit,
        limit_breach=False,
        impact=impact,
    )
    return packed, None


def _replace(ctx: dict[str, Any], cfg: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    from app.services.concentration.service import SECTORS
    from app.services.quant_math.core import historical_volatility
    from app.services.risk_engine.series import get_series

    if not ctx["holdings"]:
        return None, _MISSING
    saw_peer = False
    compared = False
    best: tuple[Any, ...] | None = None
    for row in ctx["holdings"]:
        sector = SECTORS.get(row["ticker"])
        if not sector:
            continue
        peers = [name for name, sec in SECTORS.items() if sec == sector and name != row["ticker"]]
        if not peers:
            continue
        saw_peer = True
        series = get_series(row["ticker"])
        if len(series) < 2:
            continue
        vol = historical_volatility(series)
        for peer in peers:
            peer_series = get_series(peer)
            quote = _quote(peer, ctx["book_px"])
            if len(peer_series) < 2 or quote is None:
                continue
            compared = True
            peer_vol = historical_volatility(peer_series)
            if peer_vol < vol and (best is None or peer_vol < best[0]):
                best = (peer_vol, vol, row, peer, quote)
    if best is None:
        if not saw_peer or not compared:
            return None, _MISSING
        return None, None
    peer_vol, vol, row, peer, quote = best
    own = _quote(row["ticker"], ctx["book_px"])
    if own is None:
        return None, _MISSING
    sell_qty = _lot_toward_zero(row["qty"], cfg["default_lot"])
    buy_raw = (sell_qty * own["price"]) / quote["price"]
    buy_qty = _lot_toward_zero(buy_raw, cfg["default_lot"])
    if sell_qty <= 0 or buy_qty <= 0:
        return None, None
    vol_name = format(Decimal(str(vol)).quantize(Decimal("0.0001")), "f")
    vol_peer = format(Decimal(str(peer_vol)).quantize(Decimal("0.0001")), "f")
    return _pack(
        ctx,
        cfg,
        kind="replace",
        orders=[_order(row["ticker"], -sell_qty, own), _order(peer, buy_qty, quote)],
        rationale=f"волатильность {row['ticker']} {vol_name}, близкая бумага {peer} {vol_peer}. {NOTE}",
        logic_key="maneuver_replace",
        logic_values={"vol_name": vol_name, "vol_peer": vol_peer, "name": row["ticker"], "peer": peer},
        benefit=Decimal(vol_name) - Decimal(vol_peer),
        limit_breach=False,
    ), None


def _regime(ctx: dict[str, Any], cfg: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    from app.services.behavior.service import analyze_user
    from app.services.market_regime.service import CONFIG_VERSION, classify_ticker

    snap = classify_ticker("IMOEX", scope="market")
    label = str(snap.get("label") or "")
    if label not in _REAL_LABELS:
        return None, _MISSING
    try:
        behavior = analyze_user(user_id=ctx["user_id"], mode=ctx["mode"])
    except Exception:
        logger.exception("maneuver behavior")
        behavior = {"signals": [], "insufficient": True}
    present = any(bool(item.get("present")) for item in (behavior.get("signals") or []))
    if label not in _RISK_LABELS and not present:
        return None, None
    if not ctx["holdings"]:
        return None, _MISSING
    row = max(ctx["holdings"], key=lambda item: item["value"])
    quote = _quote(row["ticker"], ctx["book_px"])
    if quote is None:
        return None, _MISSING
    qty = cfg["default_lot"] if row["qty"] >= cfg["default_lot"] else Decimal(0)
    if qty <= 0:
        return None, _MISSING
    vol = snap.get("volatility")
    vol_txt = format(Decimal(str(vol if vol is not None else "0")).quantize(Decimal("0.0001")), "f")
    packed = _pack(
        ctx,
        cfg,
        kind="regime",
        orders=[_order(row["ticker"], -qty, quote)],
        rationale=f"метка режима {label}, волатильность {vol_txt}. {NOTE}",
        logic_key="market_regime",
        logic_values={"label": label, "vol": vol_txt},
        benefit=Decimal("0.01"),
        limit_breach=False,
    )
    versions = dict(packed["model_versions"])
    versions["regime"] = CONFIG_VERSION
    versions["behavior"] = str(behavior.get("config_version") or "")
    packed["model_versions"] = versions
    return packed, None


def _deposit(ctx: dict[str, Any], cfg: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    cash = _free_cash(ctx["user_id"], ctx["mode"])
    if cash is None:
        return None, _MISSING
    if cash <= 0:
        return None, None
    weights = (ctx["target"] or {}).get("weights")
    if (ctx["target"] or {}).get("status") != "ok" or not weights:
        return None, _MISSING
    nav = ctx["nav"] + cash
    left = cash
    orders: list[dict[str, Any]] = []
    for ticker in sorted(weights):
        if left <= 0:
            break
        target_value = nav * Decimal(str(weights[ticker]))
        current = next((row["value"] for row in ctx["holdings"] if row["ticker"] == ticker), Decimal(0))
        gap = target_value - current
        if gap <= 0:
            continue
        quote = _quote(ticker, ctx["book_px"])
        if quote is None or quote["price"] <= 0:
            continue
        spend = min(left, gap)
        qty = _lot_toward_zero(spend / quote["price"], cfg["default_lot"])
        if qty <= 0:
            continue
        orders.append(_order(ticker, qty, quote))
        left -= qty * quote["price"]
    if not orders:
        return None, _MISSING
    if any(order["side"] == "sell" for order in orders):
        return None, _MISSING
    cash_txt = format(cash.quantize(Decimal("0.01")), "f")
    return _pack(
        ctx,
        cfg,
        kind="deposit",
        orders=orders,
        rationale=f"пополнение {cash_txt} без уменьшения позиций. {NOTE}",
        logic_key="maneuver_deposit",
        logic_values={"cash": cash_txt},
        benefit=cash / nav if nav > 0 else Decimal(0),
        limit_breach=False,
    ), None


def _pack(
    ctx: dict[str, Any],
    cfg: dict[str, Any],
    *,
    kind: str,
    orders: list[dict[str, Any]],
    rationale: str,
    logic_key: str,
    logic_values: dict[str, Any],
    benefit: Decimal,
    limit_breach: bool,
    impact: dict[str, Any] | None = None,
    ticker: str | None = None,
    qty: str | None = None,
) -> dict[str, Any]:
    from app.services.explanations.service import filter_wording

    if filter_wording(rationale):
        raise ValueError("forbidden wording")
    impact = impact or _impact(ctx, orders)
    costs = impact.get("costs") or {}
    score_value = benefit + (_LIMIT_BONUS if limit_breach else Decimal(0))
    total = costs.get("total")
    if total not in (None, "") and ctx["nav"] > 0:
        score_value -= Decimal(str(total)) / ctx["nav"]
    now = datetime.now(UTC)
    anchors = [
        {
            "ticker": order["ticker"],
            "price": order["price"],
            "source": order["price_source"],
            "license_tag": order["license_tag"],
        }
        for order in orders
    ]
    primary = orders[0]
    profile = ctx["profile"]
    item = {
        "kind": kind,
        "ticker": ticker or primary["ticker"],
        "qty": qty or str(abs(Decimal(primary["qty"]))),
        "orders": orders,
        "rationale": rationale,
        "logic_key": logic_key,
        "logic_values": logic_values,
        "impact": {
            "delta": impact.get("delta"),
            "costs": costs,
            "tax": impact.get("tax"),
        },
        "score": format(score_value, "f"),
        "profile_snapshot": {
            "model_version": profile.get("model_version"),
            "risk_tolerance": profile.get("risk_tolerance"),
            "limits": profile.get("limits"),
            "answers_hash": profile.get("answers_hash"),
            "as_of": profile.get("as_of"),
            "allowed_hedge_tickers": list(profile.get("allowed_hedge_tickers") or []),
        },
        "model_versions": _versions(ctx),
        "inputs_hash": _inputs_hash(ctx),
        "expires_at": (now + timedelta(hours=int(cfg["ttl_hours"]))).isoformat(),
        "expiry": {
            "ttl_hours": int(cfg["ttl_hours"]),
            "price_move_pct": format(cfg["price_move_pct"], "f"),
            "anchors": anchors,
        },
    }
    expired, reason = maneuver_expired(
        item,
        now=now,
        prices={a["ticker"]: Decimal(a["price"]) for a in anchors},
    )
    item["expired"] = expired
    item["expiry_reason"] = reason
    return item


def _impact(ctx: dict[str, Any], orders: list[dict[str, Any]]) -> dict[str, Any]:
    from app.services.act_desk.service import preview_orders

    return preview_orders(user_id=ctx["user_id"], mode=ctx["mode"], orders=orders)


def _versions(ctx: dict[str, Any]) -> dict[str, str]:
    from app.services.risk_engine.fhs import CONFIG_VERSION as RISK_VERSION
    from app.services.stress_library.service import CONFIG_VERSION as STRESS_VERSION
    from app.services.target_portfolio.types import MODEL_VERSION as TARGET_VERSION

    target = ctx.get("target") or {}
    return {
        "maneuvers": MODEL_VERSION,
        "act_desk": "act_desk.v1",
        "target_portfolio": str(target.get("model_version") or TARGET_VERSION),
        "risk": RISK_VERSION,
        "stress": STRESS_VERSION,
        "profile": str((ctx.get("profile") or {}).get("model_version") or ""),
    }


def _inputs_hash(ctx: dict[str, Any]) -> str:
    payload = {
        "holdings": [
            {"ticker": row["ticker"], "qty": format(row["qty"], "f"), "price": format(row["price"], "f")}
            for row in ctx["holdings"]
        ],
        "profile": (ctx.get("profile") or {}).get("answers_hash"),
        "target": (ctx.get("target") or {}).get("model_version"),
        "weights": (ctx.get("target") or {}).get("weights"),
    }
    blob = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _quote(ticker: str, book_px: dict[str, Decimal]) -> dict[str, Any] | None:
    from app.services.target_portfolio.service import load_market_price

    price, tag, allowed = load_market_price(ticker)
    if price is not None and allowed:
        return {"price": price, "source": "market_data", "license_tag": tag}
    book = book_px.get(ticker.upper())
    if book is None:
        return None
    return {"price": book, "source": "portfolio_book", "license_tag": "user_book"}


def _order(ticker: str, qty: Decimal, quote: dict[str, Any]) -> dict[str, str]:
    side = "buy" if qty > 0 else "sell"
    return {
        "ticker": ticker.upper(),
        "side": side,
        "qty": format(abs(qty), "f"),
        "price": format(quote["price"], "f"),
        "price_source": str(quote["source"]),
        "license_tag": str(quote["license_tag"]),
        "ccy": "RUB",
    }


def _lot_toward_zero(qty: Decimal, lot: Decimal) -> Decimal:
    step = lot if lot > 0 else Decimal(1)
    steps = (abs(qty) / step).to_integral_value(rounding=ROUND_DOWN)
    sign = Decimal(1) if qty >= 0 else Decimal(-1)
    return sign * steps * step


def _lot_ceil(qty: Decimal, lot: Decimal, cap: Decimal) -> Decimal:
    step = lot if lot > 0 else Decimal(1)
    steps = (abs(qty) / step).to_integral_value(rounding=ROUND_CEILING)
    out = steps * step
    cap_steps = (abs(cap) / step).to_integral_value(rounding=ROUND_DOWN)
    capped = cap_steps * step
    if out > capped:
        return capped
    return out


def _frac(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    number = Decimal(str(value))
    if number > 1:
        number = number / Decimal(100)
    return number


def _free_cash(user_id: str, mode: str) -> Decimal | None:
    from app.services.portfolio_book.store import get_book

    rows = get_book().transactions(user_id=user_id, mode=mode)  # type: ignore[arg-type]
    deposits = [row for row in rows if row.kind == "deposit"]
    if not deposits:
        return None
    cash = sum((row.amount for row in deposits), Decimal(0))
    cash -= sum((row.amount for row in rows if row.kind == "withdrawal"), Decimal(0))
    for row in rows:
        if row.kind != "trade":
            continue
        if row.qty > 0:
            cash -= abs(row.amount)
        elif row.qty < 0:
            cash += abs(row.amount)
    return cash


def _shares_ticker(left: dict[str, Any], right: dict[str, Any]) -> bool:
    return bool(_names(left) & _names(right))


def _shared_names(left: dict[str, Any], right: dict[str, Any]) -> str:
    return ",".join(sorted(_names(left) & _names(right)))


def _names(row: dict[str, Any]) -> set[str]:
    return {str(order["ticker"]).upper() for order in row.get("orders") or []}
