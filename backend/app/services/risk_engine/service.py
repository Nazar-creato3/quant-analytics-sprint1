"""One risk path for ticker and portfolio (Prompt 09)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Sequence

from app.core.logging import get_logger
from app.services.event_bus.bus import publish_event
from app.services.portfolio_book.store import get_book
from app.services.qa.feature_flags import is_enabled
from app.services.quant_math.core import historical_volatility
from app.services.returns.service import choose_benchmark
from app.services.risk_engine.backtest import evaluate_series
from app.services.risk_engine.contribution import attribute
from app.services.risk_engine.euler import euler_allocate
from app.services.risk_engine.fhs import (
    CONFIG_VERSION,
    EWMA_LAMBDA,
    fhs_bundle,
    historical_bundle,
    monte_carlo_bundle,
    parametric_bundle,
)
from app.services.risk_engine.series import get_series
from app.services.risk_engine.shadow import shadow_compare

logger = get_logger(__name__)

_CACHE: dict[str, dict] = {}
_BACKTESTS: dict[str, dict] = {}


@dataclass(frozen=True)
class RiskResult:
    var_95: float | None
    var_99: float | None
    es_975: float | None
    vol: float | None
    beta: float | None
    max_dd: float | None
    method: str
    status: str
    traffic_light: str
    incomplete: bool
    rubles_var_95: float | None
    explain: str
    benchmark_id: str
    data_status: str = "ok"
    reason: str | None = None


def max_drawdown(returns: Sequence[float]) -> float:
    equity = 1.0
    peak = 1.0
    dd = 0.0
    for r in returns:
        equity *= 1.0 + float(r)
        peak = max(peak, equity)
        dd = min(dd, equity / peak - 1.0)
    return abs(dd)


def _beta(asset: Sequence[float], bench: Sequence[float]) -> float | None:
    if len(asset) < 3 or len(bench) < 3:
        return None
    n = min(len(asset), len(bench))
    a, b = list(asset)[-n:], list(bench)[-n:]
    vb = historical_volatility(b) ** 2
    if vb <= 0:
        return None
    # beta = corr * sa / sb = cov / var_b
    from app.services.quant_math.core import covariance

    return covariance(a, b) / vb


def compute_risk(
    returns: Sequence[float],
    *,
    nav_rub: float | None = None,
    tickers: list[str] | None = None,
    bench_returns: Sequence[float] | None = None,
    primary: str = "fhs_ewma",
) -> RiskResult:
    if not is_enabled("qa_risk_engine"):
        raise RuntimeError("qa_risk_engine off")
    values = [float(x) for x in returns]
    bench_id, _ = choose_benchmark(tickers or [], ["RUB"])
    if len(values) < 2:
        reason = "пустой ряд доходностей" if not values else "один пункт ряда недостаточен для VaR"
        return RiskResult(
            var_95=None,
            var_99=None,
            es_975=None,
            vol=None,
            beta=None,
            max_dd=None,
            method=primary,
            status="insufficient_data",
            traffic_light="gray",
            incomplete=True,
            rubles_var_95=None,
            explain="нет данных для расчёта риска",
            benchmark_id=bench_id,
            data_status="нет данных",
            reason=reason,
        )
    incomplete = len(values) < 40
    methods = {
        "fhs_ewma": fhs_bundle(values),
        "historical": historical_bundle(values),
        "parametric": parametric_bundle(values),
        "monte_carlo": monte_carlo_bundle(values),
    }
    chosen = methods[primary]
    bt = evaluate_series(values, window=min(250, max(20, len(values) // 3))) if len(values) >= 30 else {
        "status": "beta",
        "traffic_light": "yellow",
        "kupiec_lr_95": None,
    }
    if bt["status"] == "beta":
        try:
            publish_event("risk.warning", {"reason": "var_backtest_reject", "status": "beta"})
        except Exception as exc:
            logger.warning("risk.warning publish failed", error=str(exc)[:200])
    try:
        shadow_compare(values)
    except Exception as exc:
        logger.warning("risk shadow_compare failed", error=str(exc)[:200])
    rub = None
    if nav_rub is not None and chosen.get("var_95") is not None:
        rub = float(nav_rub) * float(chosen["var_95"])
    explain = (
        f"VaR 95% — потеря, которую дневная модель считает редкой (1 день из 20). "
        f"В рублях это около {rub:.0f}." if rub is not None else
        "VaR 95% — потеря, которую дневная модель считает редкой (1 день из 20)."
    )
    return RiskResult(
        var_95=float(chosen["var_95"]),
        var_99=float(chosen["var_99"]),
        es_975=float(chosen["es_975"]),
        vol=historical_volatility(values),
        beta=_beta(values, bench_returns) if bench_returns else None,
        max_dd=max_drawdown(values),
        method=primary,
        status=str(bt["status"]),
        traffic_light=str(bt["traffic_light"]),
        incomplete=incomplete,
        rubles_var_95=rub,
        explain=explain,
        benchmark_id=bench_id,
        data_status="недостаточно данных" if incomplete else "ok",
        reason="короткий ряд (<40 наблюдений)" if incomplete else None,
    )


def _risk_payload_for_tickers(
    tickers: list[str],
    *,
    nav_rub: float | None,
    weights: list[float] | None = None,
    cash_nav: float = 0.0,
) -> dict:
    """FHS on names that have a series. Shared by the book and a hypothetical book.

    Weights are NAV shares when provided. Missing prices fall back to equal
    weight and the payload is marked partial (no zeros invented).
    """
    cols: list[list[float]] = []
    used: list[str] = []
    used_weights: list[float] = []
    raw_weights = list(weights) if weights is not None and len(weights) == len(tickers) else None
    for idx, t in enumerate(tickers):
        s = get_series(t)
        if s:
            cols.append(s)
            used.append(t)
            if raw_weights is not None:
                used_weights.append(float(raw_weights[idx]))
    if not cols:
        result = compute_risk([], tickers=tickers)
        payload = as_dict(result)
        payload["load_report_hint"] = "Нет ряда доходности по позициям."
        payload["components"] = []
        payload["daily_returns"] = []
        payload["attribution"] = {
            "components": [],
            "enb": None,
            "data_status": "нет данных",
            "reason": "нет ряда доходности",
        }
        return payload
    n = min(len(c) for c in cols)
    matrix = [c[-n:] for c in cols]
    weight_basis = "nav"
    if not used_weights or abs(sum(used_weights)) <= 1e-18:
        used_weights = [1.0 / len(matrix)] * len(matrix)
        weight_basis = "equal"
    if cash_nav and cash_nav > 0:
        risk_nav = float(nav_rub or 0.0)
        total_nav = risk_nav + float(cash_nav) if risk_nav > 0 else float(cash_nav) + sum(used_weights)
        if total_nav > 0 and risk_nav > 0:
            scale = risk_nav / total_nav
            used_weights = [w * scale for w in used_weights]
        matrix.append([0.0] * n)
        used.append("CASH")
        used_weights.append(float(cash_nav) / (risk_nav + float(cash_nav)) if (risk_nav + float(cash_nav)) > 0 else 0.0)
        cols.append([0.0] * n)
    total_w = sum(used_weights)
    used_weights = [w / total_w for w in used_weights]
    port = [sum(w * matrix[i][t] for i, w in enumerate(used_weights)) for t in range(n)]
    result = compute_risk(port, tickers=used, nav_rub=nav_rub)
    t_by_n = list(map(list, zip(*matrix)))
    alloc = euler_allocate(t_by_n, used_weights)
    payload = as_dict(result)
    payload["daily_returns"] = [float(x) for x in port]
    payload["components"] = [
        {"ticker": used[i], "var": alloc["component_var"][i], "es": alloc["component_es"][i]}
        for i in range(len(used))
    ]
    try:
        attr = attribute(
            t_by_n,
            used_weights,
            tickers=used,
            lengths=[len(c) for c in cols],
        )
        attr["weight_basis"] = weight_basis
        if weight_basis == "equal":
            attr["data_status"] = "частично"
            attr["reason"] = "нет цен для весов NAV — равные доли"
            attr["partial"] = True
        payload["attribution"] = attr
        by_ticker = {row["ticker"]: row for row in attr["components"]}
        for row in payload["components"]:
            extra = by_ticker.get(row["ticker"]) or {}
            row["weight"] = extra.get("weight")
            row["pct_of_vol"] = extra.get("pct_of_vol")
            row["pct_of_cvar"] = extra.get("pct_of_cvar")
            row["history_note"] = extra.get("history_note")
    except Exception as exc:
        logger.warning("risk attribution failed", error=str(exc)[:200])
        payload["attribution"] = {
            "components": [],
            "enb": None,
            "data_status": "нет данных",
            "reason": "нет данных",
        }
    payload["method_controls"] = {
        "historical": historical_bundle(port),
        "parametric": parametric_bundle(port),
        "monte_carlo": monte_carlo_bundle(port),
        "fhs_ewma": fhs_bundle(port),
    }
    return payload


def _holdings_from_book(user_id: str, mode: str) -> list[dict]:
    """Positions with a price: latest official close when history exists, else last trade price.

    ``price`` stays in the instrument currency; ``fx`` is roubles per unit of it
    (None when the rate is unknown), so NAV and weights are always in roubles.
    """
    from app.services.price_history import service as history

    positions = get_book().positions(user_id=user_id, mode=mode)  # type: ignore[arg-type]
    txns = get_book().transactions(user_id=user_id, mode=mode)  # type: ignore[arg-type]
    prices: dict[str, float] = {}
    for t in txns:
        if t.ticker and t.kind == "trade" and t.qty != 0:
            prices[t.ticker.upper()] = float(abs(t.amount / t.qty))
    rows: list[dict] = []
    tickers: list[str] = []
    for p in positions:
        ticker = (p.ticker or "").upper()
        if not ticker or ticker == "CASH":
            continue
        tickers.append(ticker)
        ccy = (getattr(p, "ccy", None) or "RUB").upper()
        mark = history.last(ticker)
        px = mark[1] if mark else prices.get(ticker)
        rows.append(
            {
                "ticker": ticker,
                "qty": str(abs(p.qty)),
                "price": None if px is None else str(px),
                "price_source": "official_close" if mark else ("trade" if px is not None else None),
                "price_as_of": mark[0].isoformat() if mark else None,
                "ccy": ccy,
                "fx": history.fx_rate(ccy),
            }
        )
    history.want(tickers)
    return rows


def _value_rub(h: dict) -> float | None:
    """|qty| × price in roubles, or None when the price or the FX rate is missing."""
    if h.get("price") in (None, "") or h.get("qty") in (None, ""):
        return None
    ccy = str(h.get("ccy") or "RUB").upper()
    fx = h.get("fx")
    if fx is None:
        if ccy == "RUB":
            fx = 1.0
        else:
            from app.services.price_history import service as history

            fx = history.fx_rate(ccy)
    if fx is None:
        return None
    try:
        return abs(float(h["qty"])) * float(h["price"]) * float(fx)
    except (TypeError, ValueError):
        return None


def compute_risk_for_user(user_id: str, mode: str = "paper") -> dict:
    holdings = _holdings_from_book(user_id, mode)
    risk_holdings = [h for h in holdings if str(h.get("ticker") or "").upper() != "CASH"]
    tickers = [str(h["ticker"]) for h in risk_holdings]
    nav_rub = _nav_rub([h for h in risk_holdings if h.get("price") is not None])
    cash_nav = _cash_nav(holdings)
    weights = _nav_weights(risk_holdings)
    payload = _risk_payload_for_tickers(
        tickers, nav_rub=nav_rub, weights=weights, cash_nav=cash_nav or 0.0
    )
    if any(get_series(t) for t in tickers):
        _CACHE[f"{user_id}:{mode}"] = payload
    return _attach_stress(payload, user_id, mode)


def compute_risk_for_holdings(holdings: list[dict]) -> dict:
    """VaR, ES, and stress on an explicit book.

    VaR and ES use the same series math as ``compute_risk_for_user``.
    Stress uses ``run_holdings`` with notional = |qty| × price, the same
    inputs ``run_portfolio`` builds from the live book.
    """
    ordered = sorted(
        (h for h in holdings if str(h.get("ticker") or "").upper() not in {"", "CASH"}),
        key=lambda h: str(h.get("ticker") or "").upper(),
    )
    tickers = [str(h["ticker"]).upper() for h in ordered]
    payload = _risk_payload_for_tickers(
        tickers,
        nav_rub=_nav_rub(ordered),
        weights=_nav_weights(ordered),
        cash_nav=_cash_nav(holdings),
    )
    payload["stress"] = _stress_for_holdings(ordered)
    try:
        from app.services.concentration.service import analyze_holdings

        if is_enabled("qa_concentration"):
            payload["concentration"] = analyze_holdings(ordered)
    except Exception as exc:
        logger.warning("what-if concentration failed", error=str(exc)[:200])
    return payload


def _cash_nav(holdings: list[dict]) -> float:
    total = 0.0
    for h in holdings:
        if str(h.get("ticker") or "").upper() != "CASH":
            continue
        try:
            total += abs(float(h.get("qty") or 0)) * float(h.get("price") or 1)
        except (TypeError, ValueError):
            continue
    return total


def _nav_weights(holdings: list[dict]) -> list[float] | None:
    notionals: list[float] = []
    for h in holdings:
        if str(h.get("ticker") or "").upper() == "CASH":
            notionals.append(0.0)
            continue
        value = _value_rub(h)
        if value is None:
            return None
        notionals.append(value)
    total = sum(notionals)
    if total <= 0:
        return None
    return [x / total for x in notionals]


def apply_what_if(
    base: list[dict],
    *,
    remove: list[str] | None = None,
    add: list[dict] | None = None,
    set_weight: dict[str, float] | None = None,
    add_cash_rub: float | None = None,
) -> list[dict]:
    """Mutate a hypothetical book. Does not write the portfolio store."""
    drop = {str(t).upper() for t in (remove or [])}
    rows = [dict(h) for h in base if str(h.get("ticker") or "").upper() not in drop]
    for extra in add or []:
        ticker = str(extra.get("ticker") or "").upper()
        if not ticker or ticker == "CASH":
            continue
        rows.append(
            {
                "ticker": ticker,
                "qty": extra.get("qty") or extra.get("value") or "1",
                "price": extra.get("price"),
                "ccy": extra.get("ccy") or "RUB",
            }
        )
    if set_weight:
        nav = _nav_rub([h for h in rows if str(h.get("ticker") or "").upper() != "CASH"]) or 0.0
        if nav > 0:
            locked = {str(k).upper(): float(v) for k, v in set_weight.items()}
            locked_sum = sum(max(0.0, v) for v in locked.values())
            if locked_sum > 1.0 + 1e-9:
                raise ValueError("set_weight shares exceed 1")
            free = [h for h in rows if str(h.get("ticker") or "").upper() not in locked]
            free_nav = _nav_rub(free) or 0.0
            remain = max(0.0, 1.0 - locked_sum)
            for h in rows:
                ticker = str(h.get("ticker") or "").upper()
                price = float(h["price"]) if h.get("price") not in (None, "") else 1.0
                one = _value_rub({**h, "qty": "1", "price": str(price)}) or price  # roubles per unit
                if ticker in locked:
                    target = locked[ticker] * nav
                    h["qty"] = str(target / one if one else 0.0)
                    h["price"] = str(price)
                elif free_nav > 0 and remain >= 0:
                    current = _value_rub(h) or 0.0
                    target = (current / free_nav) * remain * nav
                    h["qty"] = str(target / one if one else 0.0)
    if add_cash_rub and float(add_cash_rub) > 0:
        rows.append(
            {
                "ticker": "CASH",
                "qty": str(float(add_cash_rub)),
                "price": "1",
                "ccy": "RUB",
            }
        )
    return rows


def compute_what_if(
    *,
    user_id: str,
    mode: str = "paper",
    holdings: list[dict] | None = None,
    remove: list[str] | None = None,
    add: list[dict] | None = None,
    set_weight: dict[str, float] | None = None,
    add_cash_rub: float | None = None,
) -> dict:
    if not is_enabled("qa_k4_risk_attribution"):
        raise RuntimeError("qa_k4_risk_attribution off")
    base = holdings if holdings is not None else _holdings_from_book(user_id, mode)
    hypothetical = apply_what_if(
        base,
        remove=remove,
        add=add,
        set_weight=set_weight,
        add_cash_rub=add_cash_rub,
    )
    payload = compute_risk_for_holdings(hypothetical)
    payload["what_if"] = True
    payload["persisted"] = False
    payload["holdings"] = [
        {
            "ticker": str(h.get("ticker") or "").upper(),
            "qty": h.get("qty"),
            "price": h.get("price"),
            "ccy": h.get("ccy") or "RUB",
        }
        for h in hypothetical
    ]
    return payload


def _nav_rub(holdings: list[dict]) -> float | None:
    """Portfolio value in roubles; None if any position lacks a price or an FX rate."""
    total = 0.0
    for h in holdings:
        value = _value_rub(h)
        if value is None:
            return None
        total += value
    if total <= 0:
        return None
    return total


def _stress_for_holdings(holdings: list[dict]) -> dict:
    from app.services.stress_library.service import run_holdings

    rows: list[dict] = []
    for h in holdings:
        if h.get("price") is None or h.get("qty") in (None, ""):
            continue
        try:
            value = abs(float(h["qty"])) * float(h["price"])
        except (TypeError, ValueError):
            continue
        rows.append(
            {
                "ticker": str(h["ticker"]).upper(),
                "value": value,
                "ccy": str(h.get("ccy") or "RUB"),
            }
        )
    try:
        return run_holdings(rows)
    except Exception as exc:
        logger.warning("stress_library holdings failed", error=str(exc)[:200])
        return {
            "scenarios": [],
            "empty": True,
            "data_status": "нет данных",
            "reason": "нет данных",
            "source": "stress_library",
        }


def _attach_stress(payload: dict, user_id: str, mode: str) -> dict:
    try:
        from app.services.qa.feature_flags import is_enabled
        from app.services.stress_library.service import run_portfolio

        if is_enabled("qa_stress_library"):
            payload["stress"] = run_portfolio(user_id=user_id, mode=mode)
        from app.services.concentration.service import analyze_portfolio

        if is_enabled("qa_concentration"):
            payload["concentration"] = analyze_portfolio(user_id=user_id, mode=mode)
        from app.services.behavior.service import analyze_user

        if is_enabled("qa_behavior"):
            payload["behavior"] = analyze_user(user_id=user_id, mode=mode)
    except Exception as exc:
        logger.warning(
            "risk attach stress/concentration/behavior failed",
            user_id=user_id,
            error=str(exc)[:200],
        )
        payload.setdefault(
            "stress",
            {
                "scenarios": [],
                "empty": True,
                "data_status": "нет данных",
                "reason": "нет данных",
                "source": "risk_engine",
            },
        )
    return payload


def as_dict(result: RiskResult) -> dict:
    return {
        "var_95": result.var_95,
        "var_99": result.var_99,
        "es_975": result.es_975,
        "volatility": result.vol,
        "beta": result.beta,
        "max_drawdown": result.max_dd,
        "method": result.method,
        "config_version": CONFIG_VERSION,
        "ewma_lambda": EWMA_LAMBDA,
        "status": result.status,
        "traffic_light": result.traffic_light,
        "incomplete": result.incomplete,
        "rubles_var_95": result.rubles_var_95,
        "var_95_unit": "fraction",
        "rubles_var_95_unit": "RUB",
        "explain": result.explain,
        "benchmark_id": result.benchmark_id,
        "source": "оценка риска",
        "as_of": date.today().isoformat(),
        "data_status": result.data_status,
        "reason": result.reason,
    }


def cached(user_id: str, mode: str = "paper") -> dict | None:
    return _CACHE.get(f"{user_id}:{mode}")


def invalidate(_name: str | None = None, _env=None) -> None:
    _CACHE.clear()


def store_backtest(name: str, payload: dict) -> None:
    _BACKTESTS[name] = payload


def backtests() -> dict[str, dict]:
    return dict(_BACKTESTS)
