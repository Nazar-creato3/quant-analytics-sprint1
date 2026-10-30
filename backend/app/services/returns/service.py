"""Portfolio returns from the book + official close (Prompt 08). Numbers from code only."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from app.core.logging import get_logger
from app.services.event_bus.bus import publish_event
from app.services.market_data.eod import EodRow, get_eod_price
from app.services.portfolio_book.store import get_book
from app.services.qa.feature_flags import is_enabled
from app.services.quant_math.book import money_weighted_return, time_weighted_return

logger = get_logger(__name__)

Period = Literal["month", "quarter", "year", "inception", "custom"]
Scope = Literal["account", "venue", "capital"]


@dataclass(frozen=True)
class ReturnsResult:
    twr: Decimal | None
    mwr: Decimal | None
    twr_net: Decimal | None
    mwr_net: Decimal | None
    period: str
    scope: str
    incomplete: bool
    coverage_from: date | None
    requested_from: date
    annualized: bool
    benchmark_id: str
    benchmark_note: str
    dietz_used: bool
    data_status: str
    reason: str | None = None
    end_value: Decimal | None = None


def period_start(kind: Period, today: date, custom_from: date | None = None) -> date:
    if kind == "custom" and custom_from is not None:
        return custom_from
    if kind == "month":
        return today.replace(day=1)
    if kind == "quarter":
        q = (today.month - 1) // 3 * 3 + 1
        return today.replace(month=q, day=1)
    if kind == "year":
        return today.replace(month=1, day=1)
    return date(1970, 1, 1)


def choose_benchmark(tickers: list[str], ccys: list[str]) -> tuple[str, str]:
    joined = " ".join(t.upper() for t in tickers)
    if any(x in joined for x in ("BTC", "ETH")):
        return "BTC-USD", "crypto: bitcoin"
    if any(c == "USD" for c in ccys) and any(t in joined for t in ("AAPL", "MSFT", "SPY")):
        return "SPXTR_PROXY", "US total-return proxy — not licensed S&P 500 TR"
    return "MCFTR", "MOEX total return + RGBITR for RUB bonds"


def _annualize(ret: Decimal, start: date, end: date) -> tuple[Decimal, bool]:
    days = (end - start).days
    if days <= 365:
        return ret, False
    years = Decimal(days) / Decimal("365")
    growth = (Decimal("1") + ret) ** (Decimal("1") / years) - Decimal("1")
    return growth, True


def _empty_result(
    *,
    period: str,
    scope: str,
    start: date,
    coverage: date | None,
    reason: str,
    bench: str,
    note: str,
) -> ReturnsResult:
    return ReturnsResult(
        twr=None,
        mwr=None,
        twr_net=None,
        mwr_net=None,
        period=period,
        scope=scope,
        incomplete=True,
        coverage_from=coverage,
        requested_from=start,
        annualized=False,
        benchmark_id=bench,
        benchmark_note=note,
        dietz_used=False,
        data_status="нет данных",
        reason=reason,
        end_value=None,
    )


def compute_returns(
    *,
    user_id: str,
    mode: str,
    period: Period = "inception",
    scope: Scope = "capital",
    today: date | None = None,
    custom_from: date | None = None,
    eod: dict[str, EodRow] | None = None,
    start_value: Decimal | None = None,
) -> ReturnsResult:
    if not is_enabled("qa_returns"):
        raise RuntimeError("qa_returns off")
    day = today or date.today()
    start = period_start(period, day, custom_from)
    txns = get_book().transactions(user_id=user_id, mode=mode)  # type: ignore[arg-type]
    pos = get_book().positions(user_id=user_id, mode=mode)  # type: ignore[arg-type]
    bench, note = choose_benchmark([p.ticker for p in pos], [p.ccy for p in pos])
    dated = [t for t in txns if t.event_time.date() >= start]
    if eod is None:
        # Value at the latest official close from the price-history store.
        from app.services.price_history import service as history

        traded = sorted({t.ticker.upper() for t in txns if t.kind == "trade" and t.ticker})
        eod = history.eod_map(traded)
        history.want([x for x in traded if x not in eod])
    coverage = min((t.event_time.date() for t in txns), default=None)
    if coverage is None:
        return _empty_result(
            period=period,
            scope=scope,
            start=start,
            coverage=None,
            reason="в книге нет операций",
            bench=bench,
            note=note,
        )

    incomplete = coverage > start and period != "inception"
    deposits = [t for t in dated if t.kind == "deposit"]
    capital = start_value
    if capital is None:
        if deposits:
            capital = sum((abs(t.amount) for t in deposits), Decimal("0"))
        else:
            return _empty_result(
                period=period,
                scope=scope,
                start=start,
                coverage=coverage,
                reason="нет стартового капитала (депозит или явный start_value)",
                bench=bench,
                note=note,
            )
    if capital <= 0:
        return _empty_result(
            period=period,
            scope=scope,
            start=start,
            coverage=coverage,
            reason="стартовый капитал неположительный",
            bench=bench,
            note=note,
        )

    fees = sum((t.amount for t in dated if t.kind in {"fee", "tax"}), Decimal("0"))
    external = {t for t in dated if t.kind in {"deposit", "withdrawal"}}
    pnl = sum((t.amount for t in dated if t not in external and t.kind != "trade"), Decimal("0"))
    trade_pnl = Decimal("0")
    missing_prices: list[str] = []
    for t in dated:
        if t.kind != "trade":
            continue
        row = (eod or {}).get(t.ticker)
        if row is None:
            missing_prices.append(t.ticker)
            continue
        try:
            price, _ = get_eod_price(row, purpose="valuation")
        except Exception as exc:
            logger.warning("official close unavailable", ticker=t.ticker, error=str(exc)[:200])
            missing_prices.append(t.ticker)
            continue
        trade_pnl += t.qty * price - t.amount if t.qty > 0 else t.amount

    if missing_prices:
        return _empty_result(
            period=period,
            scope=scope,
            start=start,
            coverage=coverage,
            reason=f"нет official close для сделок: {', '.join(sorted(set(missing_prices)))}",
            bench=bench,
            note=note,
        )

    end_gross = capital + pnl + trade_pnl
    end_net = end_gross - abs(fees)
    twr = time_weighted_return([(capital, end_gross)]) if capital > 0 else Decimal("0")
    twr_net = time_weighted_return([(capital, end_net)]) if capital > 0 and end_net > 0 else twr

    # Capital taken from deposits is already in the flows below — do not count it twice,
    # and never date the opening flow 1970-01-01 for «since inception».
    explicit_start = start_value is not None
    flows: list[tuple[date, Decimal]] = [(coverage if period == "inception" else start, -capital)] if explicit_start else []
    for t in dated:
        if t.kind == "deposit":
            flows.append((t.event_time.date(), -abs(t.amount)))
        elif t.kind == "withdrawal":
            flows.append((t.event_time.date(), abs(t.amount)))
    flows.append((day, end_gross))
    mwr_ok = True
    try:
        mwr = money_weighted_return(flows)
    except Exception as exc:
        logger.warning("mwr failed; leave empty", user_id=user_id, error=str(exc)[:200])
        mwr = None
        mwr_ok = False
    flows_net = list(flows[:-1]) + [(day, end_net)]
    try:
        mwr_net = money_weighted_return(flows_net) if end_net > 0 else mwr
    except Exception as exc:
        logger.warning("mwr_net failed; leave empty", user_id=user_id, error=str(exc)[:200])
        mwr_net = None
        mwr_ok = False

    window_start = coverage if period == "inception" else start
    twr_a, ann = _annualize(twr, window_start, day)
    if twr_net is not None and ann:
        twr_net, _ = _annualize(twr_net, window_start, day)
    mwr_a = None
    if mwr is not None:
        # XIRR is already an annual rate. Under a year we show the period figure,
        # like TWR; over a year it stays annual.
        days = max(1, (day - window_start).days)
        mwr_a = mwr if days > 365 else (Decimal("1") + mwr) ** (Decimal(days) / Decimal("365")) - Decimal("1")
        if mwr_net is not None and days <= 365:
            mwr_net = (Decimal("1") + mwr_net) ** (Decimal(days) / Decimal("365")) - Decimal("1")

    incomplete = incomplete or not mwr_ok
    if twr_a is None and not mwr_ok:
        data_status = "нет данных"
        reason: str | None = "нет данных"
    elif not mwr_ok:
        # Fail-closed for MWR only: TWR stays; do not void the whole result.
        data_status = "недостаточно данных"
        reason = "MWR не посчитан"
    elif incomplete:
        data_status = "недостаточно данных"
        reason = "история короче выбранного периода"
    else:
        data_status = "ok"
        reason = None

    result = ReturnsResult(
        twr=twr_a,
        mwr=mwr_a,
        twr_net=twr_net,
        mwr_net=mwr_net,
        period=period,
        scope=scope,
        incomplete=incomplete,
        coverage_from=coverage,
        requested_from=start,
        annualized=ann,
        benchmark_id=bench,
        benchmark_note=note,
        dietz_used=False,
        data_status=data_status,
        reason=reason,
        end_value=end_gross,
    )
    try:
        publish_event(
            "report.ready",
            {"kind": "returns", "user_id": user_id, "twr": str(result.twr) if result.twr is not None else None},
        )
    except Exception as exc:
        logger.warning("returns event publish failed", user_id=user_id, error=str(exc)[:200])
    return result


def as_dict(result: ReturnsResult) -> dict:
    return {
        "twr": str(result.twr) if result.twr is not None else None,
        "mwr": str(result.mwr) if result.mwr is not None else None,
        "twr_net": str(result.twr_net) if result.twr_net is not None else None,
        "mwr_net": str(result.mwr_net) if result.mwr_net is not None else None,
        "twr_label": "доходность решений (TWR)",
        "mwr_label": "рост денег (MWR/XIRR)",
        "period": result.period,
        "scope": result.scope,
        "incomplete": result.incomplete,
        "coverage_from": result.coverage_from.isoformat() if result.coverage_from else None,
        "requested_from": result.requested_from.isoformat(),
        "load_report_hint": "Загрузите брокерский отчёт, если история короче выбранного периода."
        if result.incomplete
        else None,
        "annualized": result.annualized,
        "benchmark_id": result.benchmark_id,
        "benchmark_note": result.benchmark_note,
        "dietz_used": result.dietz_used,
        "source": "quant_math.book + portfolio_book",
        "data_status": result.data_status,
        "reason": result.reason,
        "status": "insufficient_data" if result.data_status != "ok" else "ok",
        "end_value": str(result.end_value) if result.end_value is not None else None,
    }


def equity_vs_benchmark(
    *,
    weights: dict[str, Any],
    benchmark_id: str,
    benchmark_note: str,
) -> dict[str, Any]:
    """Cumulative growth of book weights vs the returns-module benchmark.

    Daily returns come from `risk_engine.series` (same store as VaR). Missing
    series → нет данных; cash weight is 0 return, not a filled price.
    """
    from app.services.risk_engine.series import get_series

    empty = {
        "data_status": "нет данных",
        "points": [],
        "benchmark_id": benchmark_id,
        "benchmark_note": benchmark_note,
        "reason": "нет ряда доходностей позиций",
    }
    asset_w: list[float] = []
    asset_series: list[list[float]] = []
    for ticker, raw_w in (weights or {}).items():
        if str(ticker).upper() in {"CASH", "RUB"}:
            continue
        try:
            wf = float(raw_w)
        except (TypeError, ValueError):
            continue
        if abs(wf) < 1e-12:
            continue
        series = get_series(str(ticker))
        if len(series) < 2:
            return empty
        asset_w.append(wf)
        asset_series.append(series)
    if not asset_series:
        return empty
    n = min(len(s) for s in asset_series)
    if n < 2:
        return empty
    bench = get_series(benchmark_id)
    bench_ok = len(bench) >= n
    eq = 1.0
    beq = 1.0
    points: list[dict[str, float | int | None]] = [{"t": 0, "portfolio": 1.0, "benchmark": 1.0 if bench_ok else None}]
    for i in range(n):
        port_r = sum(w * s[i] for w, s in zip(asset_w, asset_series, strict=True))
        eq *= 1.0 + port_r
        if bench_ok:
            beq *= 1.0 + bench[i]
        points.append({"t": i + 1, "portfolio": eq, "benchmark": beq if bench_ok else None})
    return {
        "data_status": "ok",
        "points": points,
        "benchmark_id": benchmark_id,
        "benchmark_note": benchmark_note,
        "reason": None if bench_ok else "нет ряда ориентира",
    }
