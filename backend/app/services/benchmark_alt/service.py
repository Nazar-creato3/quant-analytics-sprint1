"""K1: portfolio TWR/MWR next to RGBITR and a money-market sleeve on the same flows.

Portfolio numbers come from `returns.compute_returns`. Alternative sleeves replay
deposits and withdrawals into RGBITR and the configured money-market ticker.
No good/bad wording. Numbers are Decimal in code; API emits strings.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, ROUND_HALF_EVEN
from typing import Any

from app.core.logging import get_logger
from app.services.benchmark_alt.prices import load_price_series
from app.services.benchmark_alt.replay import KOPECK, replay_index_cashflows
from app.services.legal.catalog import load_ui_texts
from app.services.portfolio_book.store import get_book
from app.services.qa.feature_flags import is_enabled
from app.services.returns.service import as_dict as returns_as_dict
from app.services.returns.service import compute_returns

logger = get_logger(__name__)

RGBITR_TICKER = "RGBITR"
MONEY_MARKET_TICKER = "LQDT"
RGBITR_LABEL_KEY = "rgbitr"
MONEY_MARKET_LABEL_KEY = "money_market"
PP = Decimal("0.0001")


def _texts() -> dict[str, Any]:
    pack = load_ui_texts().get("k1") or {}
    return pack if isinstance(pack, dict) else {}


def _book_cashflows(*, user_id: str, mode: str, start: date) -> list[tuple[date, Decimal]]:
    txns = get_book().transactions(user_id=user_id, mode=mode)  # type: ignore[arg-type]
    flows: list[tuple[date, Decimal]] = []
    for txn in txns:
        day = txn.event_time.date()
        if day < start:
            continue
        if txn.kind == "deposit":
            flows.append((day, abs(txn.amount)))
        elif txn.kind == "withdrawal":
            flows.append((day, -abs(txn.amount)))
    return flows


def _dec_str(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return str(value)


def _pp(left: Decimal | None, right: Decimal | None) -> Decimal | None:
    if left is None or right is None:
        return None
    return ((left - right) * Decimal("100")).quantize(PP, rounding=ROUND_HALF_EVEN)


def _user_source(raw: str | None) -> str:
    """The screen prints this string. Keep store names off it."""
    if not raw:
        return "нет данных"
    return "официальное закрытие"


def _sleeve(
    *,
    ticker: str,
    label: str,
    cashflows: list[tuple[date, Decimal]],
    as_of: date,
    portfolio_end: Decimal | None,
    portfolio_twr: Decimal | None,
    portfolio_mwr: Decimal | None,
) -> dict[str, Any]:
    prices, meta = load_price_series(ticker)
    if not prices:
        return {
            "ticker": ticker,
            "label": label,
            "data_status": "нет данных",
            "reason": "нет ряда цен альтернативы",
            "end_value": None,
            "twr": None,
            "mwr": None,
            "diff_value": None,
            "diff_twr_pp": None,
            "diff_mwr_pp": None,
            "source": _user_source(meta.get("source")),
            "price_as_of": meta.get("as_of") or None,
        }
    replayed = replay_index_cashflows(cashflows, prices, as_of)
    end_value = replayed.get("end_value")
    twr = replayed.get("twr")
    mwr = replayed.get("mwr")
    diff_value = None
    if isinstance(portfolio_end, Decimal) and isinstance(end_value, Decimal):
        diff_value = (portfolio_end - end_value).quantize(KOPECK, rounding=ROUND_HALF_EVEN)
    return {
        "ticker": ticker,
        "label": label,
        "data_status": replayed.get("data_status"),
        "reason": replayed.get("reason"),
        "end_value": end_value if isinstance(end_value, Decimal) else None,
        "twr": twr if isinstance(twr, Decimal) else None,
        "mwr": mwr if isinstance(mwr, Decimal) else None,
        "diff_value": diff_value,
        "diff_twr_pp": _pp(portfolio_twr, twr if isinstance(twr, Decimal) else None),
        "diff_mwr_pp": _pp(portfolio_mwr, mwr if isinstance(mwr, Decimal) else None),
        "source": _user_source(meta.get("source")),
        "price_as_of": meta.get("as_of") or None,
    }


def compare_simple_alternatives(
    *,
    user_id: str,
    mode: str,
    period: str = "inception",
    today: date | None = None,
) -> dict[str, Any]:
    if not is_enabled("qa_k1_benchmark"):
        raise RuntimeError("qa_k1_benchmark off")
    texts = _texts()
    day = today or date.today()
    portfolio = compute_returns(user_id=user_id, mode=mode, period=period, today=day)  # type: ignore[arg-type]
    start = portfolio.requested_from
    flows = _book_cashflows(user_id=user_id, mode=mode, start=start)
    if not flows:
        return {
            "data_status": "нет данных",
            "reason": "в книге нет пополнений и выводов",
            "period": period,
            "as_of": day.isoformat(),
            "portfolio": returns_as_dict(portfolio),
            "alternatives": [],
            "texts": texts,
        }

    rgbitr = _sleeve(
        ticker=RGBITR_TICKER,
        label=str(texts.get("rgbitr") or RGBITR_TICKER),
        cashflows=flows,
        as_of=day,
        portfolio_end=portfolio.end_value,
        portfolio_twr=portfolio.twr,
        portfolio_mwr=portfolio.mwr,
    )
    money = _sleeve(
        ticker=MONEY_MARKET_TICKER,
        label=str(texts.get("money_market") or MONEY_MARKET_TICKER),
        cashflows=flows,
        as_of=day,
        portfolio_end=portfolio.end_value,
        portfolio_twr=portfolio.twr,
        portfolio_mwr=portfolio.mwr,
    )
    statuses = {str(rgbitr["data_status"]), str(money["data_status"]), portfolio.data_status}
    if statuses == {"ok"}:
        status = "ok"
        reason = None
    elif "ok" in statuses or "недостаточно данных" in statuses:
        status = "частично"
        missing = [row["ticker"] for row in (rgbitr, money) if row["data_status"] != "ok"]
        reason = "частично: " + ", ".join(missing) if missing else portfolio.reason
    else:
        status = "нет данных"
        reason = str(rgbitr.get("reason") or money.get("reason") or portfolio.reason)

    return {
        "data_status": status,
        "reason": reason,
        "period": period,
        "as_of": day.isoformat(),
        "portfolio": returns_as_dict(portfolio),
        "alternatives": [rgbitr, money],
        "methodology": "/methodology",
        "texts": texts,
    }


def as_dict(payload: dict[str, Any]) -> dict[str, Any]:
    """JSON-safe copy: Decimals become strings. None stays None."""
    alts = []
    for row in payload.get("alternatives") or []:
        alts.append(
            {
                **row,
                "end_value": _dec_str(row.get("end_value")),
                "twr": _dec_str(row.get("twr")),
                "mwr": _dec_str(row.get("mwr")),
                "diff_value": _dec_str(row.get("diff_value")),
                "diff_twr_pp": _dec_str(row.get("diff_twr_pp")),
                "diff_mwr_pp": _dec_str(row.get("diff_mwr_pp")),
            }
        )
    port = dict(payload.get("portfolio") or {})
    return {
        "data_status": payload.get("data_status"),
        "reason": payload.get("reason"),
        "period": payload.get("period"),
        "as_of": payload.get("as_of"),
        "portfolio": port,
        "alternatives": alts,
        "methodology": payload.get("methodology"),
        "texts": payload.get("texts") or {},
    }
