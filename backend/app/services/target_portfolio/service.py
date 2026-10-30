"""Target book for one user. Prompt 37 calls build_for_user. target_source stays user."""
from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_EVEN

import numpy as np

from app.services.explanations.service import filter_wording
from app.services.target_portfolio.costs import commission_rate, decide_rebalance, load_cost_table, trade_costs
from app.services.target_portfolio.covariance import align_returns, ledoit_wolf
from app.services.target_portfolio.optimize import (
    ConstructionError,
    _group_rows,
    black_litterman_mu,
    prepare_upper,
    sample_mu,
    solve_cvar,
    solve_equal,
    solve_erc,
    solve_hrp,
    solve_mean_variance,
)
from app.services.target_portfolio.scenarios import fhs_scenarios
from app.services.target_portfolio.tax import iis_note, tax_base_for_year
from app.services.target_portfolio.types import (
    METHODS,
    MODEL_VERSION,
    ConstraintSet,
    ForecastView,
    Instrument,
    TaxLot,
)
from app.services.target_portfolio.views import view_from_forecast

logger = logging.getLogger(__name__)

NOTE = "это возвращает портфель к вашим правилам"
MONEY = Decimal("0.01")
WEIGHT = Decimal("0.00000001")


def construct(
    instruments: list[Instrument],
    *,
    method: str,
    capital: Decimal,
    constraints: ConstraintSet,
    current_weights: dict[str, float] | None = None,
    views: list[ForecastView] | None = None,
    broker: str = "",
    tariff: str = "",
    cost_table: dict | None = None,
    risk_aversion: float = 4.0,
    cvar_alpha: float = 0.95,
    bl_delta: float = 2.5,
    tax_lots: list[TaxLot] | None = None,
    sell_plan: list[tuple[str, Decimal]] | None = None,
    sale_prices: dict[str, Decimal] | None = None,
    as_of: date | None = None,
    account_type: str = "regular",
    iis_opened_on: date | None = None,
    iis_contribution: Decimal | None = None,
) -> dict:
    """One method per call. Comparison of methods is prompt 38."""
    if method not in METHODS:
        return _fail("error", f"неизвестный метод {method}")
    kept, excluded = _select(instruments, constraints)
    if not kept:
        return _fail("нет данных", "нет данных", excluded=excluded)
    kept = sorted(kept, key=lambda item: item.ticker)
    tickers = [item.ticker for item in kept]
    n = len(kept)
    try:
        upper, groups = _limits(kept, constraints, capital)
        w0 = _current(tickers, current_weights)
        weights, solver, cov_note, mu = _dispatch(
            method,
            kept,
            upper=upper,
            groups=groups,
            w0=w0,
            capital=capital,
            constraints=constraints,
            views=views,
            risk_aversion=risk_aversion,
            cvar_alpha=cvar_alpha,
            bl_delta=bl_delta,
        )
    except ConstructionError as exc:
        logger.info("target_portfolio status=%s", exc.status)
        return _fail(exc.status, exc.reason, excluded=excluded, method=method)
    published = _publish(tickers, weights)
    gain, cost_block, traded = _gain_and_costs(
        tickers,
        weights,
        w0,
        mu,
        capital,
        kept,
        broker=broker,
        tariff=tariff,
        cost_table=cost_table,
    )
    total = Decimal(cost_block["total"]) if cost_block.get("total") else None
    if cost_block.get("status") != "ok":
        total = None
    proposed, rebalance_reason = decide_rebalance(gain, total)
    orders = _orders(kept, weights, w0, capital) if proposed else []
    day = as_of or date(2026, 10, 6)
    tax = _tax_block(
        tax_lots or [],
        sell_plan or [],
        sale_prices or {},
        day,
        account_type=account_type,
        iis_opened_on=iis_opened_on,
        iis_contribution=iis_contribution,
    )
    note = NOTE
    if filter_wording(note):
        note = NOTE
    variance = _variance(kept, weights)
    return {
        "status": "ok",
        "reason": "",
        "method": method,
        "target_source": "user",
        "model_version": MODEL_VERSION,
        "solver": solver,
        "cov_note": cov_note,
        "weights": published,
        "sum_weights": _sum_text(published),
        "proposed_rebalance": proposed,
        "rebalance_reason": rebalance_reason,
        "orders": orders,
        "costs": cost_block,
        "traded_notional": format(traded, "f"),
        "expected_gain": None if gain is None else format(gain.quantize(MONEY, rounding=ROUND_HALF_EVEN), "f"),
        "variance": variance,
        "tax": tax,
        "tax_in_comparison": False,
        "excluded": excluded,
        "note": note,
        "consequences": {
            "variance": variance,
            "expected_gain": None if gain is None else format(gain.quantize(MONEY, rounding=ROUND_HALF_EVEN), "f"),
            "costs_total": cost_block.get("total"),
        },
    }


def build_target(
    user_id: str,
    *,
    mode: str = "paper",
    method: str = "equal_weight",
    broker: str = "",
    tariff: str = "",
) -> dict:
    """Production entry for prompt 37. Same calculation as build_for_user."""
    return build_for_user(user_id, mode=mode, method=method, broker=broker, tariff=tariff)


def build_for_user(
    user_id: str,
    *,
    mode: str = "paper",
    method: str = "equal_weight",
    broker: str = "",
    tariff: str = "",
) -> dict:
    """Production entry. Prompt 37 calls this. Model views are not a target source."""
    from app.services.qa.feature_flags import is_enabled

    if not is_enabled("qa_target_portfolio"):
        return _fail("off", "qa_target_portfolio выключен")
    if method not in METHODS:
        return _fail("error", f"неизвестный метод {method}")
    try:
        from app.services.investment_profile.service import get_profile
        from app.services.portfolio_book.service import positions_for
        from app.services.risk_engine.series import get_series

        profile = get_profile(user_id)
    except Exception:
        logger.exception("target_portfolio profile")
        return _fail("error", "расчёт целевой структуры не выполнен")
    if not profile:
        return _fail("нет данных", "задайте лимиты риска в настройках")
    try:
        positions = positions_for(user_id=user_id, mode=mode)  # type: ignore[arg-type]
    except Exception:
        logger.exception("target_portfolio positions")
        return _fail("error", "расчёт целевой структуры не выполнен")
    if not positions:
        empty = _fail("нет данных", "нет данных", method=method)
        from app.services.target_portfolio.tax import NDFL_RATE_LABEL

        empty["tax"] = {"rate": NDFL_RATE_LABEL, "tax_cash": None, "tax_cash_reason": "нет налоговой базы"}
        return empty
    instruments: list[Instrument] = []
    current: dict[str, float] = {}
    notionals: dict[str, Decimal] = {}
    for pos in positions:
        if pos.qty == 0:
            continue
        price, tag, allowed = load_market_price(pos.ticker)
        series = tuple(get_series(pos.ticker))
        instruments.append(
            Instrument(
                ticker=pos.ticker,
                price=price,
                license_tag=tag,
                display_allowed=allowed,
                returns=series,
            )
        )
        if price is not None and allowed:
            notionals[pos.ticker] = (pos.qty * price).copy_abs()
    capital = sum(notionals.values(), Decimal("0"))
    if capital > 0:
        for ticker, money in notionals.items():
            current[ticker] = float(money / capital)
    views = None
    if method == "black_litterman":
        views = _views_for(instruments)
    return construct(
        instruments,
        method=method,
        capital=capital if capital > 0 else Decimal("0"),
        constraints=_constraints_from_profile(profile),
        current_weights=current,
        views=views,
        broker=broker,
        tariff=tariff,
        account_type=str(profile.get("account_type") or "regular"),
    )


def load_market_price(ticker: str) -> tuple[Decimal | None, str, bool]:
    """Price plus whether the license may be shown. Failures become «нет цены»."""
    try:
        from app.services.market_data.equity_eod_store import read_latest_quote
        from app.services.market_data.license import quote_envelope

        quote = read_latest_quote(ticker)
        raw = quote.get("price")
        source = str(quote.get("source") or "eod_local")
        price_s = None if raw is None else format(float(raw), ".8f")
        env = quote_envelope(
            symbol=ticker,
            price=price_s,
            source=source,
            as_of="",
            delayed=True,
            audience="owner",
        )
        shown = env.get("price")
        if shown is None or not env.get("display_allowed"):
            return None, str(env.get("license_tag") or "internal_only"), False
        return Decimal(str(shown)), str(env.get("license_tag")), True
    except Exception:
        logger.info("target_portfolio price missing ticker=%s", ticker)
        return None, "internal_only", False


def _views_for(instruments: list[Instrument]) -> list[ForecastView]:
    from app.services.forecast_core.service import forecast

    found: list[ForecastView] = []
    for item in instruments:
        if not item.display_allowed or not item.returns:
            continue
        sigma = float(np.std(np.asarray(item.returns, dtype=float), ddof=1))
        if sigma <= 0:
            continue
        try:
            payload = forecast(item.ticker)
        except Exception:
            logger.info("target_portfolio forecast missing")
            continue
        view = view_from_forecast(payload, sigma=sigma)
        if view is not None:
            found.append(view)
    return found


def _constraints_from_profile(profile: dict) -> ConstraintSet:
    return ConstraintSet(
        name_cap=_frac(profile.get("max_position_pct")),
        sector_cap=_frac(profile.get("max_sector_pct")),
        issuer_cap=_frac(profile.get("max_issuer_pct")),
        allow_shorts=_truthy(profile.get("allow_shorts")),
        liquidity_share=_frac(profile.get("liquidity_adv_share")),
        trade_budget=_money(profile.get("trade_budget")),
        banned_tickers=tuple(str(x).upper() for x in (profile.get("banned_tickers") or [])),
        banned_sectors=tuple(str(x) for x in (profile.get("banned_sectors") or [])),
        banned_issuers=tuple(str(x) for x in (profile.get("banned_issuers") or [])),
    )


def _select(
    instruments: list[Instrument], constraints: ConstraintSet
) -> tuple[list[Instrument], list[dict[str, str]]]:
    banned = {item.upper() for item in constraints.banned_tickers}
    banned_sectors = set(constraints.banned_sectors)
    banned_issuers = set(constraints.banned_issuers)
    kept: list[Instrument] = []
    excluded: list[dict[str, str]] = []
    for item in instruments:
        reason = _exclude_reason(item, constraints, banned, banned_sectors, banned_issuers)
        if reason:
            excluded.append({"ticker": item.ticker, "reason": reason})
            continue
        kept.append(item)
    return kept, excluded


def _exclude_reason(
    item: Instrument,
    constraints: ConstraintSet,
    banned: set[str],
    banned_sectors: set[str],
    banned_issuers: set[str],
) -> str:
    if item.ticker.upper() in banned:
        return "бумага в списке запрещённых"
    if item.sector and item.sector in banned_sectors:
        return "отрасль в списке запрещённых"
    if item.issuer and item.issuer in banned_issuers:
        return "эмитент в списке запрещённых"
    if item.price is None:
        return "нет цены"
    if item.license_tag == "internal_only" or not item.display_allowed:
        return "лицензия internal_only"
    if constraints.sector_cap is not None and not item.sector:
        return "нет данных по отрасли"
    if constraints.issuer_cap is not None and not item.issuer:
        return "нет данных по эмитенту"
    if constraints.liquidity_share is not None and item.adv is None:
        return "нет данных по обороту"
    return ""


def _limits(kept: list[Instrument], constraints: ConstraintSet, capital: Decimal):
    n = len(kept)
    liquidity = None
    if constraints.liquidity_share is not None and capital > 0:
        liquidity = np.array(
            [
                float(constraints.liquidity_share * (item.adv or Decimal("0")) / capital)
                for item in kept
            ],
            dtype=float,
        )
    name_cap = None if constraints.name_cap is None else float(constraints.name_cap)
    upper = prepare_upper(
        n,
        name_cap=name_cap,
        liquidity_caps=liquidity,
        allow_shorts=constraints.allow_shorts,
    )
    groups = _group_rows(
        [item.sector for item in kept],
        None if constraints.sector_cap is None else float(constraints.sector_cap),
    )
    groups.extend(
        _group_rows(
            [item.issuer for item in kept],
            None if constraints.issuer_cap is None else float(constraints.issuer_cap),
        )
    )
    return upper, groups


def _current(tickers: list[str], current: dict[str, float] | None) -> np.ndarray:
    if not current:
        return np.zeros(len(tickers), dtype=float)
    return np.array([float(current.get(ticker, 0.0)) for ticker in tickers], dtype=float)


def _dispatch(
    method: str,
    kept: list[Instrument],
    *,
    upper: np.ndarray,
    groups: list,
    w0: np.ndarray,
    capital: Decimal,
    constraints: ConstraintSet,
    views: list[ForecastView] | None,
    risk_aversion: float,
    cvar_alpha: float,
    bl_delta: float,
) -> tuple[np.ndarray, str, str, np.ndarray | None]:
    n = len(kept)
    budget = None if constraints.trade_budget is None else float(constraints.trade_budget)
    cap = float(capital)
    common = dict(
        upper=upper,
        allow_shorts=constraints.allow_shorts,
        groups=groups,
        w0=w0,
        capital=cap,
        budget=budget,
    )
    if method == "equal_weight":
        weights, solver = solve_equal(n, **common)
        return weights, solver, "", None
    panel = align_returns([item.returns for item in kept])
    if panel is None:
        raise ConstructionError("нет данных", "нет данных")
    cov, cov_note = ledoit_wolf(panel)
    mu = _mu_vector(kept, panel)
    if method == "equal_risk_contribution":
        weights, solver = solve_erc(cov, **common)
        return weights, solver, cov_note, mu
    if method == "hrp":
        raw = solve_hrp(cov)
        from app.services.target_portfolio.optimize import _project

        weights, solver = _project(raw, **common)
        return weights, solver, cov_note, mu
    if method == "mean_variance":
        if mu is None:
            raise ConstructionError("нет данных", "нет данных")
        weights, solver = solve_mean_variance(cov, mu, risk_aversion=risk_aversion, **common)
        return weights, solver, cov_note, mu
    if method == "black_litterman":
        if not views:
            raise ConstructionError("нет данных", "нет данных")
        if mu is None:
            raise ConstructionError("нет данных", "нет данных")
        w_eq = w0 / w0.sum() if float(w0.sum()) > 1e-12 else np.full(n, 1.0 / n)
        posterior = black_litterman_mu(
            cov,
            w_eq,
            views,
            [item.ticker for item in kept],
            tau=1.0 / panel.shape[0],
            delta=bl_delta,
        )
        weights, solver = solve_mean_variance(cov, posterior, risk_aversion=risk_aversion, **common)
        return weights, solver, cov_note, posterior
    scenarios = fhs_scenarios([item.returns for item in kept])
    if scenarios is None:
        raise ConstructionError("нет данных", "нет данных")
    weights, solver = solve_cvar(
        scenarios,
        alpha=cvar_alpha,
        upper=upper,
        allow_shorts=constraints.allow_shorts,
        groups=groups,
    )
    if budget is not None:
        from app.services.target_portfolio.optimize import _project

        weights, solver = _project(weights, **common)
    return weights, solver, cov_note, mu


def _mu_vector(kept: list[Instrument], panel: np.ndarray) -> np.ndarray | None:
    if all(item.mu is not None for item in kept):
        return np.array([float(item.mu) for item in kept], dtype=float)
    if panel is None:
        return None
    return sample_mu(panel)


def _gain_and_costs(
    tickers: list[str],
    weights: np.ndarray,
    w0: np.ndarray,
    mu: np.ndarray | None,
    capital: Decimal,
    kept: list[Instrument],
    *,
    broker: str,
    tariff: str,
    cost_table: dict | None,
) -> tuple[Decimal | None, dict, Decimal]:
    dw = weights - w0
    traded = capital * Decimal(str(float(np.maximum(dw, 0).sum() + np.maximum(-dw, 0).sum())))
    traded = traded.quantize(MONEY, rounding=ROUND_HALF_EVEN)
    table = cost_table if cost_table is not None else load_cost_table()
    rate = commission_rate(table, broker, tariff)
    spreads = [item.spread_bps for item in kept]
    slips = [item.slippage_bps for item in kept]
    if any(value is None for value in spreads) or any(value is None for value in slips):
        spread = None
        slip = None
    else:
        spread = _weighted_bps(dw, spreads)
        slip = _weighted_bps(dw, slips)
    block = trade_costs(traded_notional=abs(traded), rate=rate, spread_bps=spread, slippage_bps=slip)
    gain = None
    if mu is not None and capital > 0:
        gain = (capital * Decimal(str(float(dw @ mu)))).quantize(MONEY, rounding=ROUND_HALF_EVEN)
    return gain, block, traded


def _weighted_bps(dw: np.ndarray, values: list[Decimal | None]) -> Decimal | None:
    denom = float(np.abs(dw).sum())
    if denom <= 0:
        return Decimal("0")
    acc = Decimal("0")
    for delta, value in zip(dw, values):
        if value is None:
            return None
        acc += Decimal(str(abs(float(delta)))) * value
    return acc / Decimal(str(denom))


def _orders(
    kept: list[Instrument],
    weights: np.ndarray,
    w0: np.ndarray,
    capital: Decimal,
) -> list[dict[str, str]]:
    rows = []
    for item, weight, prev in zip(kept, weights, w0):
        delta = float(weight - prev)
        if abs(delta) < 1e-8 or item.price is None or item.price <= 0:
            continue
        raw = capital * Decimal(str(delta)) / item.price
        qty = _toward_zero(raw, item.lot_size if item.lot_size > 0 else Decimal("1"))
        if qty == 0:
            continue
        price = _round_step(item.price, item.price_step)
        rows.append(
            {
                "ticker": item.ticker,
                "qty_delta": format(qty, "f"),
                "price": format(price, "f"),
                "notional": format((qty * price).quantize(MONEY, rounding=ROUND_HALF_EVEN), "f"),
            }
        )
    return rows


def _toward_zero(raw: Decimal, lot: Decimal) -> Decimal:
    steps = (abs(raw) / lot).to_integral_value(rounding=ROUND_DOWN)
    sign = Decimal("1") if raw >= 0 else Decimal("-1")
    return sign * steps * lot


def _round_step(price: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return price
    units = (price / step).quantize(Decimal("1"), rounding=ROUND_HALF_EVEN)
    return units * step


def _publish(tickers: list[str], weights: np.ndarray) -> dict[str, str]:
    quantized = [
        Decimal(format(float(value), ".10f")).quantize(WEIGHT, rounding=ROUND_HALF_EVEN) for value in weights
    ]
    residual = Decimal("1") - sum(quantized, Decimal("0"))
    if abs(residual) <= Decimal("0.000001") and quantized:
        slot = max(range(len(quantized)), key=lambda i: quantized[i])
        quantized[slot] = (quantized[slot] + residual).quantize(WEIGHT, rounding=ROUND_HALF_EVEN)
    return {ticker: format(value, "f") for ticker, value in zip(tickers, quantized)}


def _sum_text(weights: dict[str, str]) -> str:
    total = sum((Decimal(value) for value in weights.values()), Decimal("0"))
    return format(total.quantize(WEIGHT, rounding=ROUND_HALF_EVEN), "f")


def _variance(kept: list[Instrument], weights: np.ndarray) -> str | None:
    panel = align_returns([item.returns for item in kept])
    if panel is None:
        return None
    try:
        cov, _note = ledoit_wolf(panel)
    except ValueError:
        return None
    value = float(weights @ cov @ weights)
    if value != value:
        return None
    return format(Decimal(format(value, ".10f")).quantize(WEIGHT, rounding=ROUND_HALF_EVEN), "f")


def _tax_block(
    lots: list[TaxLot],
    sell_plan: list[tuple[str, Decimal]],
    sale_prices: dict[str, Decimal],
    day: date,
    *,
    account_type: str,
    iis_opened_on: date | None,
    iis_contribution: Decimal | None,
) -> dict:
    from app.services.target_portfolio.tax import NDFL_RATE_LABEL, dividend_ndfl, fifo_realize

    rows: list[dict[str, str]] = []
    for ticker, qty in sell_plan:
        price = sale_prices.get(ticker)
        if price is None:
            continue
        rows.extend(fifo_realize(lots, ticker=ticker, sell_qty=qty, sale_price=price, sold_on=day))

    year = tax_base_for_year(rows, day.year) if rows else {
        "tax_base": None,
        "tax_cash": None,
        "tax_cash_reason": "нет налоговой базы операций с ценными бумагами",
        "relief_applied": False,
        "rate": NDFL_RATE_LABEL,
    }
    return {
        "lots": rows,
        "year": year,
        "dividends": dividend_ndfl(Decimal("0"), resident=None),
        "iis": iis_note(account_type=account_type, opened_on=iis_opened_on, contribution=iis_contribution),
        "tax_in_comparison": False,
        "rate": NDFL_RATE_LABEL,
    }


def _fail(status: str, reason: str, *, excluded: list | None = None, method: str = "") -> dict:
    return {
        "status": status,
        "reason": reason,
        "method": method,
        "target_source": "user",
        "model_version": MODEL_VERSION,
        "weights": None,
        "proposed_rebalance": False,
        "orders": [],
        "excluded": excluded or [],
        "note": NOTE,
        "tax_in_comparison": False,
    }


def _frac(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    number = Decimal(str(value))
    if number > 1:
        number = number / Decimal("100")
    return number


def _money(value: object) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def _truthy(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}
