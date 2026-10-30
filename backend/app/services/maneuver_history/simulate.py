"""Walk-forward of four strategies. Signals use only data through the decision date.

The next session is used for the fill, not for the signal. target_source stays user.
Prompt 40 reads the control file; this module does not attribute live approvals.
"""
from __future__ import annotations

import hashlib
import logging
import time
from datetime import date, datetime, timezone
from datetime import time as clock
from decimal import Decimal
from pathlib import Path
from typing import Any

import numpy as np
from scipy import __version__ as scipy_version

from app.services.investment_profile.service import limits_from_profile
from app.services.maneuver_history.directory import (
    directory_from_notes,
    is_tradable,
    load_delist_notes,
    retain_names,
)
from app.services.maneuver_history.execute import (
    Ledger,
    fill_at_next_session,
    open_ledger,
    orders_toward_weights,
    tax_summary,
)
from app.services.maneuver_history.paths import control_path, report_path
from app.services.maneuver_history.pit import (
    business_sessions,
    detect_leak,
    quarter_decision_indexes,
    returns_through,
    slice_dates,
)
from app.services.maneuver_history.scenarios import (
    SESSION_COUNT,
    START,
    STARTING_QTY_SCALE,
    crisis_window_status,
    load_goldens,
    paths_for,
    synthetic_profiles,
)
from app.services.maneuver_history.stats import (
    cscv_probability,
    deflated_sharpe_ratio,
    period_sharpe,
    summarize_metrics,
    wealth_ratio,
)
from app.services.qa.feature_flags import is_enabled
from app.services.quant_math.core import expected_shortfall, value_at_risk

logger = logging.getLogger(__name__)

MODEL_VERSION = "maneuver_history.v1"
TARGET_METHOD = "mean_variance"
MANEUVER_METHOD = "mean_variance"
STRATEGIES = (
    "do_nothing",
    "quarterly_equal_weight",
    "target_no_views",
    "maneuvers",
)
TRIAL_METHODS = (
    "equal_weight",
    "equal_risk_contribution",
    "hrp",
    "mean_variance",
    "cvar",
)


def _stamp(day: date) -> datetime:
    return datetime.combine(day, clock(0), tzinfo=timezone.utc)


def _boot_seed(seed: int, label: str) -> int:
    digest = hashlib.sha256(f"{seed}:{label}".encode()).digest()
    return int.from_bytes(digest[:4], "little")


def _prices_at(paths: dict[str, list[Decimal]], index: int) -> dict[str, Decimal]:
    return {ticker: series[index] for ticker, series in paths.items()}


def _breached(
    ledger: Ledger,
    prices: dict[str, Decimal],
    wealth: Decimal,
    returns: list[float],
    peak: Decimal,
    limits: dict[str, str],
    max_position: Decimal,
) -> bool:
    hit = False
    if wealth > 0:
        for ticker, qty in ledger.qty.items():
            px = prices.get(ticker)
            if qty <= 0 or px is None:
                continue
            if qty * px / wealth > max_position:
                hit = True
        if peak > 0 and (peak - wealth) / peak > Decimal(limits["max_drawdown"]):
            hit = True
    if len(returns) >= 2:
        var = value_at_risk(returns, 0.95)
        es_var = value_at_risk(returns, 0.975)
        es = expected_shortfall(returns, 0.975, es_var)
        if var > float(limits["var_95"]) or es > float(limits["es_975"]):
            hit = True
    return hit


def _prepare_book(
    user_id: str,
    qty: dict[str, Decimal],
    prices: dict[str, Decimal],
    when: datetime,
    answers: dict[str, str],
) -> None:
    from app.services.act_desk.service import reset as reset_act
    from app.services.act_desk.service import save_profile
    from app.services.portfolio_book.service import ensure_account, record_transaction
    from app.services.portfolio_book.store import get_book
    from app.services.risk_engine.series import reset as reset_series
    from app.services.risk_engine.service import invalidate
    from app.services.stress_library.service import _reset as reset_stress

    get_book().reset()
    reset_act()
    reset_series()
    invalidate()
    reset_stress()
    save_profile(user_id, answers)
    ensure_account(account_id=f"p38-{user_id}", user_id=user_id, venue="p38hist", mode="paper")
    deposit = sum((amount * prices[ticker] for ticker, amount in qty.items()), Decimal("0"))
    record_transaction(
        account_id=f"p38-{user_id}",
        user_id=user_id,
        mode="paper",
        venue="p38hist",
        external_id=f"{user_id}-dep",
        kind="deposit",
        instrument_id="CASH",
        ticker="CASH",
        qty="0",
        amount=format(deposit, "f"),
        ccy="RUB",
        event_time=when,
    )
    for ticker, amount in sorted(qty.items()):
        record_transaction(
            account_id=f"p38-{user_id}",
            user_id=user_id,
            mode="paper",
            venue="p38hist",
            external_id=f"{user_id}-open-{ticker}",
            kind="trade",
            instrument_id=ticker,
            ticker=ticker,
            qty=format(amount, "f"),
            amount=format(amount * prices[ticker], "f"),
            ccy="RUB",
            event_time=when,
        )


def _book_fill(
    user_id: str,
    index: int,
    applied: dict[str, str],
    prices: dict[str, Decimal],
    when: datetime,
) -> None:
    from app.services.portfolio_book.service import record_transaction

    for ticker, signed_txt in sorted(applied.items()):
        signed = Decimal(signed_txt)
        record_transaction(
            account_id=f"p38-{user_id}",
            user_id=user_id,
            mode="paper",
            venue="p38hist",
            external_id=f"{user_id}-f{index}-{ticker}",
            kind="trade",
            instrument_id=ticker,
            ticker=ticker,
            qty=format(signed, "f"),
            amount=format(abs(signed) * prices[ticker], "f"),
            ccy="RUB",
            event_time=when,
        )


def _generate(
    user_id: str,
    method: str,
    price_map: dict[str, Decimal],
    returns_map: dict[str, tuple[float, ...]],
) -> dict[str, Any]:
    from unittest.mock import patch

    from app.services.maneuvers.service import generate_maneuvers
    from app.services.risk_engine.series import put_series
    from app.services.risk_engine.series import reset as reset_series
    from app.services.risk_engine.service import invalidate
    from app.services.stress_library.service import _reset as reset_stress

    reset_series()
    reset_stress()
    invalidate()
    for ticker, series in returns_map.items():
        put_series(ticker, list(series))

    def _load(ticker: str) -> tuple[Decimal | None, str, bool]:
        px = price_map.get(ticker.upper())
        if px is None:
            return None, "synthetic", False
        return px, "synthetic", True

    def _trade(_user_id: str, _mode: str, ticker: str) -> Decimal | None:
        return price_map.get(str(ticker).upper())

    with (
        patch("app.services.target_portfolio.service.load_market_price", _load),
        patch("app.services.concentration.service._trade_price", _trade),
    ):
        batch = generate_maneuvers(user_id=user_id, mode="paper", method=method)
    source = (batch.get("target") or {}).get("target_source")
    if source not in (None, "user"):
        batch["items"] = []
        batch["skipped"] = list(batch.get("skipped") or []) + [
            {"kind": "target_source", "reason": str(source)}
        ]
    return batch


def _target_orders(
    *,
    method: str,
    ledger: Ledger,
    paths: dict[str, list[Decimal]],
    names: list,
    index: int,
    day: date,
    max_position: Decimal,
    lot: Decimal,
) -> tuple[list[dict[str, str]], str]:
    from app.services.target_portfolio.service import construct
    from app.services.target_portfolio.types import ConstraintSet, Instrument

    if method != "black_litterman" and not is_enabled("qa_target_portfolio"):
        return [], "qa_target_portfolio выключен"
    px = _prices_at(paths, index)
    nav = ledger.wealth(px)
    if nav is None or nav <= 0:
        return [], "нет данных"
    instruments: list[Instrument] = []
    for ticker, series in sorted(paths.items()):
        name = next((item for item in names if item.ticker == ticker), None)
        if name is not None and not is_tradable(name, day):
            continue
        window = returns_through(series, index)
        if len(window) != index:
            raise RuntimeError("leak")
        instruments.append(
            Instrument(
                ticker=ticker,
                price=series[index],
                license_tag="synthetic",
                display_allowed=True,
                returns=window,
            )
        )
    current: dict[str, float] = {}
    for ticker, qty in ledger.qty.items():
        if qty > 0 and ticker in px and nav > 0:
            current[ticker] = float(qty * px[ticker] / nav)
    built = construct(
        instruments,
        method=method,
        capital=nav,
        constraints=ConstraintSet(name_cap=max_position, allow_shorts=False),
        current_weights=current,
        views=None,
        as_of=day,
    )
    if built.get("target_source") not in (None, "user"):
        return [], "target_source"
    if built.get("status") != "ok" or not built.get("weights"):
        return [], str(built.get("reason") or built.get("status") or "нет данных")
    weights = {ticker: Decimal(str(value)) for ticker, value in built["weights"].items()}
    orders = orders_toward_weights(qty=ledger.qty, prices=px, weights=weights, nav=nav, lot=lot)
    note = ""
    if not built.get("proposed_rebalance"):
        reason = str(built.get("rebalance_reason") or "издержки без тарифа")
        note = f"веса цели применены; заявка сервиса не создана: {reason}"
    return orders, note


def _equal_orders(
    ledger: Ledger,
    paths: dict[str, list[Decimal]],
    names: list,
    index: int,
    day: date,
    lot: Decimal,
) -> tuple[list[dict[str, str]], str]:
    px = _prices_at(paths, index)
    tradable = []
    for ticker in sorted(paths):
        name = next((item for item in names if item.ticker == ticker), None)
        if name is not None and not is_tradable(name, day):
            continue
        tradable.append(ticker)
    if not tradable:
        return [], "нет данных"
    nav = ledger.wealth(px)
    if nav is None or nav <= 0:
        return [], "нет данных"
    weight = Decimal(1) / Decimal(len(tradable))
    weights = {ticker: weight for ticker in tradable}
    return orders_toward_weights(qty=ledger.qty, prices=px, weights=weights, nav=nav, lot=lot), ""


def _walk(
    *,
    strategy: str,
    method: str,
    paths: dict[str, list[Decimal]],
    qty: dict[str, Decimal],
    names: list,
    sessions: list[date],
    decisions: list[int],
    limits: dict[str, str],
    max_position: Decimal,
    seed: int,
    label: str,
    user_id: str,
    sync_book: bool,
) -> dict[str, Any]:
    from app.services.maneuvers.service import load_maneuver_config, maneuver_expired

    lot = load_maneuver_config()["default_lot"]
    if not paths or not qty:
        tax = tax_summary([], year=sessions[-1].year)
        metrics = summarize_metrics(
            wealth_before=[],
            return_after="нет данных",
            after_status="нет данных",
            period_returns=[],
            trades=0,
            tax=tax,
            turnover=Decimal("0"),
            maneuver_hits=0,
            decisions=len(decisions),
            breach_days=0,
            priced_days=0,
            bootstrap_seed=_boot_seed(seed, label),
        )
        return {
            "metrics": metrics,
            "note": "нет данных",
            "leak_failures": 0,
            "period_returns": [],
            "target_sources": [],
            "skipped": [],
        }
    ledger = open_ledger(qty, _prices_at(paths, 0), sessions[0])
    pending: dict[str, Any] | None = None
    wealth: list[Decimal] = []
    after_wealth: list[Decimal] = []
    returns: list[float] = []
    lost_costs = False
    turnover = Decimal("0")
    trades = 0
    hits = 0
    breach_days = 0
    priced = 0
    leaks = 0
    peak = Decimal("0")
    notes: list[str] = []
    sources: list[str] = []
    skipped: list[dict[str, str]] = []
    for index, day in enumerate(sessions):
        px = _prices_at(paths, index)
        if pending is not None:
            orders = list(pending["orders"])
            if pending["kind"] == "maneuvers":
                kept: list[dict[str, str]] = []
                for item in pending["items"]:
                    expired, reason = maneuver_expired(item, now=_stamp(day), prices=px)
                    if expired:
                        notes.append(reason)
                        continue
                    kept.extend(item.get("orders") or [])
                orders = kept
            fill = fill_at_next_session(fill_on=day, prices=px, orders=orders, ledger=ledger)
            turnover += Decimal(str(fill["turnover"]))
            trades += int(fill["filled"])
            if pending["kind"] == "maneuvers" and int(fill["filled"]) > 0:
                hits += 1
            if sync_book and fill["applied"]:
                _book_fill(user_id, index, fill["applied"], px, _stamp(day))  # type: ignore[arg-type]
            if fill["costs_status"] == "нет данных":
                lost_costs = True
            pending = None
        marked = ledger.wealth(px)
        if marked is None:
            continue
        if wealth:
            previous = wealth[-1]
            if previous != 0:
                returns.append(float((marked - previous) / previous))
        wealth.append(marked)
        if not lost_costs and ledger.costs_complete:
            after_marked = ledger.wealth_after_costs(px)
            if after_marked is not None:
                after_wealth.append(after_marked)
        else:
            lost_costs = True
        if marked > peak:
            peak = marked
        priced += 1
        if _breached(ledger, px, marked, returns, peak, limits, max_position):
            breach_days += 1
        if index not in decisions:
            continue
        signal = slice_dates(sessions, day)
        if detect_leak(day, signal):
            leaks += 1
        for series in paths.values():
            if len(returns_through(series, index)) != index:
                leaks += 1
                break
        if strategy == "do_nothing":
            continue
        if strategy == "quarterly_equal_weight":
            orders, note = _equal_orders(ledger, paths, names, index, day, lot)
            if note:
                notes.append(note)
            pending = {"kind": "weights", "orders": orders, "items": []}
            continue
        if strategy == "target_no_views":
            try:
                orders, note = _target_orders(
                    method=method,
                    ledger=ledger,
                    paths=paths,
                    names=names,
                    index=index,
                    day=day,
                    max_position=max_position,
                    lot=lot,
                )
            except RuntimeError:
                leaks += 1
                orders, note = [], "нет данных"
            except Exception:
                logger.exception("target walk")
                orders, note = [], "нет данных"
            if note:
                notes.append(note)
            pending = {"kind": "weights", "orders": orders, "items": []}
            continue
        if not is_enabled("qa_maneuver_generator"):
            notes.append("qa_maneuver_generator выключен")
            continue
        try:
            batch = _generate(
                user_id,
                method,
                px,
                {ticker: returns_through(series, index) for ticker, series in paths.items()},
            )
        except Exception:
            logger.exception("maneuver walk")
            notes.append("нет данных")
            continue
        source = (batch.get("target") or {}).get("target_source")
        if source:
            sources.append(str(source))
        for row in batch.get("skipped") or []:
            skipped.append({"date": day.isoformat(), "kind": str(row.get("kind")), "reason": str(row.get("reason"))})
        pending = {"kind": "maneuvers", "orders": [], "items": list(batch.get("items") or [])}
    tax = tax_summary(ledger.realized, year=sessions[-1].year)
    if (not lost_costs) and len(after_wealth) == len(wealth) and len(wealth) >= 2:
        after = wealth_ratio(after_wealth[0], after_wealth[-1])
        after_status = "ok"
    else:
        after = "нет данных"
        after_status = "нет данных"
    metrics = summarize_metrics(
        wealth_before=wealth,
        return_after=after,
        after_status=after_status,
        period_returns=returns,
        trades=trades,
        tax=tax,
        turnover=turnover,
        maneuver_hits=hits,
        decisions=len(decisions),
        breach_days=breach_days,
        priced_days=priced,
        bootstrap_seed=_boot_seed(seed, label),
    )
    unique_notes = []
    for note in notes:
        if note and note not in unique_notes:
            unique_notes.append(note)
    return {
        "metrics": metrics,
        "note": "; ".join(unique_notes),
        "leak_failures": leaks,
        "period_returns": returns,
        "target_sources": sources,
        "skipped": skipped,
    }


def _strip(outcome: dict[str, Any]) -> dict[str, Any]:
    return {
        "metrics": outcome["metrics"],
        "note": outcome["note"],
        "target_sources": outcome["target_sources"],
        "skipped": outcome["skipped"],
    }


def _parameter_grid(
    *,
    book: dict[str, Any] | None,
    paths: dict[str, list[Decimal]] | None,
    names: list,
    sessions: list[date],
    decisions: list[int],
    answers: dict[str, str],
    limits: dict[str, str],
    seed: int,
) -> dict[str, Any]:
    if book is None or paths is None:
        return {"status": "нет данных", "reason": "нет портфеля с двумя именами"}
    max_position = Decimal(answers["max_position_pct"])
    trials = []
    columns: list[list[float]] = []
    sharpes: list[float] = []
    entered: list[str] = []
    for method in TRIAL_METHODS:
        outcome = _walk(
            strategy="target_no_views",
            method=method,
            paths=paths,
            qty=book["qty"],
            names=names,
            sessions=sessions,
            decisions=decisions,
            limits=limits,
            max_position=max_position,
            seed=seed,
            label=f"grid-{book['id']}-{method}",
            user_id="p38-grid",
            sync_book=False,
        )
        score = period_sharpe(np.asarray(outcome["period_returns"], dtype=float))
        trials.append(
            {
                "method": method,
                "views": None,
                "return_before_costs": outcome["metrics"]["return_before_costs"],
                "sharpe": outcome["metrics"]["sharpe"],
                "note": outcome["note"],
                "period_sharpe": None if score is None else format(score, ".8f"),
            }
        )
        if score is not None and outcome["period_returns"]:
            columns.append(list(outcome["period_returns"]))
            sharpes.append(score)
            entered.append(method)
    litterman = _walk(
        strategy="target_no_views",
        method="black_litterman",
        paths=paths,
        qty=book["qty"],
        names=names,
        sessions=sessions,
        decisions=decisions,
        limits=limits,
        max_position=max_position,
        seed=seed,
        label=f"grid-{book['id']}-black_litterman",
        user_id="p38-grid",
        sync_book=False,
    )
    if not columns:
        return {
            "status": "нет данных",
            "portfolio_id": book["id"],
            "profile": "moderate",
            "headline_method": TARGET_METHOD,
            "trials": trials,
            "black_litterman_without_views": litterman["note"] or "нет данных",
            "deflated_sharpe": {"status": "нет данных"},
            "cscv": {"status": "нет данных"},
            "selected_for_statistic": None,
        }
    winner = max(range(len(sharpes)), key=lambda index: (sharpes[index], -index))
    return {
        "status": "ok",
        "portfolio_id": book["id"],
        "profile": "moderate",
        "headline_method": TARGET_METHOD,
        "headline_not_replaced": True,
        "trials": trials,
        "black_litterman_without_views": litterman["note"] or litterman["metrics"]["return_before_costs"],
        "deflated_sharpe": deflated_sharpe_ratio(columns[winner], sharpes),
        "cscv": cscv_probability(columns),
        "selected_for_statistic": entered[winner],
    }


def run_validation(
    *,
    seed: int = 38,
    start: date | None = None,
    sessions: int | None = None,
    portfolio_ids: list[str] | None = None,
    profile_names: list[str] | None = None,
    write: bool = False,
    report_file: Path | None = None,
    control_file: Path | None = None,
    include_parameter_grid: bool = True,
) -> dict[str, Any]:
    """One seeded run. `write` stores the report and the prompt-40 control file."""
    if not is_enabled("qa_maneuver_history"):
        return {"status": "off", "reason": "qa_maneuver_history выключен", "model_version": MODEL_VERSION}
    started = time.perf_counter()
    calendar = business_sessions(start or START, sessions or SESSION_COUNT)
    decisions = quarter_decision_indexes(calendar)
    profiles = synthetic_profiles()
    chosen_profiles = profile_names or list(profiles)
    books = load_goldens()
    if portfolio_ids is not None:
        wanted = set(portfolio_ids)
        books = [book for book in books if book["id"] in wanted]
    crisis = crisis_window_status()
    scenarios: list[dict[str, Any]] = []
    leaks = 0
    sources: set[str] = set()
    for profile_name in chosen_profiles:
        answers = profiles[profile_name]
        limits = limits_from_profile(
            {
                "risk_tolerance": profile_name,
                "max_position_pct": answers["max_position_pct"],
                "max_crisis_loss_pct": answers["max_crisis_loss_pct"],
            }
        )
        max_position = Decimal(answers["max_position_pct"])
        for book in books:
            paths = paths_for(book, len(calendar), seed)
            tickers = sorted(set(book["qty"]) | set(book["unpriced"]))
            notes = load_delist_notes(tickers)
            names = retain_names(directory_from_notes(notes), as_of=calendar[0])
            dropped = len(tickers) - len(names)
            user_id = f"p38-{profile_name}-{book['id']}"
            strategies: dict[str, Any] = {}
            for strategy in STRATEGIES:
                if strategy == "maneuvers" and book["qty"]:
                    _prepare_book(user_id, book["qty"], _prices_at(paths, 0), _stamp(calendar[0]), answers)
                method = MANEUVER_METHOD if strategy == "maneuvers" else TARGET_METHOD
                try:
                    outcome = _walk(
                        strategy=strategy,
                        method=method,
                        paths=paths,
                        qty=book["qty"],
                        names=names,
                        sessions=calendar,
                        decisions=decisions,
                        limits=limits,
                        max_position=max_position,
                        seed=seed,
                        label=f"{book['id']}-{profile_name}-{strategy}",
                        user_id=user_id,
                        sync_book=strategy == "maneuvers",
                    )
                except Exception:
                    logger.exception("scenario %s %s %s", book["id"], profile_name, strategy)
                    outcome = {
                        "metrics": summarize_metrics(
                            wealth_before=[],
                            return_after="нет данных",
                            after_status="нет данных",
                            period_returns=[],
                            trades=0,
                            tax=tax_summary([], year=calendar[-1].year),
                            turnover=Decimal("0"),
                            maneuver_hits=0,
                            decisions=len(decisions),
                            breach_days=0,
                            priced_days=0,
                            bootstrap_seed=1,
                        ),
                        "note": "нет данных",
                        "leak_failures": 0,
                        "period_returns": [],
                        "target_sources": [],
                        "skipped": [],
                    }
                leaks += int(outcome["leak_failures"])
                sources.update(outcome["target_sources"])
                strategies[strategy] = _strip(outcome)
            scenarios.append(
                {
                    "portfolio_id": book["id"],
                    "profile": profile_name,
                    "unpriced": list(book["unpriced"]),
                    "directory": [
                        {"ticker": name.ticker, "delist_note": name.delist_note, "retained": True} for name in names
                    ],
                    "directory_dropped": dropped,
                    "strategies": strategies,
                }
            )
            logger.info("scenario %s %s", book["id"], profile_name)
    grid_book = next((book for book in books if book["id"] == "p2_three_cashflows" and len(book["qty"]) >= 2), None)
    if grid_book is None:
        grid_book = next((book for book in books if len(book["qty"]) >= 2), None)
    if include_parameter_grid and "moderate" in profiles and grid_book is not None:
        grid_answers = profiles["moderate"]
        grid_limits = limits_from_profile(
            {
                "risk_tolerance": "moderate",
                "max_position_pct": grid_answers["max_position_pct"],
                "max_crisis_loss_pct": grid_answers["max_crisis_loss_pct"],
            }
        )
        grid_names = retain_names(
            directory_from_notes(load_delist_notes(sorted(grid_book["qty"]))),
            as_of=calendar[0],
        )
        parameter_selection = _parameter_grid(
            book=grid_book,
            paths=paths_for(grid_book, len(calendar), seed),
            names=grid_names,
            sessions=calendar,
            decisions=decisions,
            answers=grid_answers,
            limits=grid_limits,
            seed=seed,
        )
    else:
        parameter_selection = {"status": "нет данных", "reason": "сетка не запускалась"}
    result: dict[str, Any] = {
        "status": "ok",
        "model_version": MODEL_VERSION,
        "seed": seed,
        "numpy": np.__version__,
        "scipy": scipy_version,
        "sessions": [day.isoformat() for day in calendar],
        "decision_dates": [calendar[index].isoformat() for index in decisions],
        "calendar_note": "сессии — будни; календарь праздников площадки в репозитории нет",
        "qty_scale": format(STARTING_QTY_SCALE, "f"),
        "headline_method": TARGET_METHOD,
        "maneuver_method": MANEUVER_METHOD,
        "target_source": "user",
        "target_sources_seen": sorted(sources),
        "tax_cash_computed": False,
        "crisis_windows": crisis,
        "delistings": "нет данных" if all(value == "нет данных" for value in load_delist_notes(["SAMPLE"]).values()) else "файл прочитан",
        "leak_failures": leaks,
        "point_in_time_ok": leaks == 0,
        "scenario_count": len(scenarios),
        "scenarios": scenarios,
        "parameter_selection": parameter_selection,
        "elapsed_sec": round(time.perf_counter() - started, 3),
    }
    if write:
        from app.services.maneuver_history.handoff import (
            read_control_input,
            write_control_input,
        )
        from app.services.maneuver_history.report import render_validation

        text_path = report_file or report_path()
        data_path = control_file or control_path()
        text_path.parent.mkdir(parents=True, exist_ok=True)
        text_path.write_text(render_validation(result), encoding="utf-8")
        write_control_input(result, data_path)
        read_control_input(data_path)
    return result
