"""Concentration and hidden overlaps (Prompt 14).

Weights and HHI come from quant_math.book. Ratings are «нет данных» until a licensed provider exists.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from app.services.catalog.resolve import resolve
from app.services.portfolio_book.store import get_book
from app.services.qa.feature_flags import is_enabled
from app.services.quant_math.book import Position, PriceQuote, weights_and_hhi
from app.services.risk_engine.euler import euler_allocate
from app.services.risk_engine.series import get_series

CONFIG_VERSION = "concentration.v1"
SECTORS = {
    "SBER": "banks",
    "SBERP": "banks",
    "VTBR": "banks",
    "TCSG": "banks",
    "GAZP": "energy",
    "LKOH": "energy",
    "ROSN": "energy",
    "NVTK": "energy",
    "SNGS": "energy",
    "SNGSP": "energy",
    "AAPL": "tech",
    "AAPLX": "tech",
    "MSFT": "tech",
    "BTC-USD": "crypto",
    "ETH-USD": "crypto",
}
ISSUERS = {
    "SBERP": "SBER",
    "SNGSP": "SNGS",
    "AAPLX": "AAPL",
    "TSLAX": "TSLA",
}


def _reset() -> None:
    return None


def _explain(code: str, number: str, *, nav: Decimal | None = None, ccy: str | None = None, enb: Decimal | None = None) -> dict[str, str]:
    if code == "hhi":
        try:
            from app.services.explanations.service import render
            from app.services.qa.feature_flags import is_enabled as flag

            if flag("qa_explanations"):
                if nav is None or ccy is None:
                    nav_clause = "Сумма портфеля в рублях — нет данных, поэтому рубли не подставляются."
                elif ccy.upper() == "RUB":
                    nav_clause = (
                        f"Для портфеля {nav} ₽ это значит, что крупные доли "
                        "сильнее влияют на результат, чем мелкие."
                    )
                else:
                    nav_clause = (
                        f"Для портфеля {nav} {ccy} это значит, что крупные доли "
                        "сильнее влияют на результат, чем мелкие."
                    )
                return render(
                    "hhi",
                    {"hhi": number, "nav_clause": nav_clause, "enb": str(enb or 1)},
                )
        except Exception:
            pass
    table = {
        "hhi": (
            f"Индекс концентрации HHI {number}.",
            "HHI — сумма квадратов весов. 1.0 значит одна позиция; ниже — более ровный портфель.",
            "Эффективное число ставок ≈ 1/HHI. Это не прогноз доходности.",
        ),
        "overlap": (
            f"Скрытое совпадение: {number}.",
            "Один эмитент или базовый актив встречается в нескольких инструментах.",
            "Акция и преф, токен и акция, фьючерс на тот же актив считаются одной ставкой.",
        ),
        "rating": (
            "Кредитный рейтинг: нет данных.",
            "Лицензированный источник рейтинга не подключён. Поле не заполняется выдумкой.",
            "Когда появится провайдер, сюда придёт рейтинг с датой и источником.",
        ),
    }
    phrase, detail, learn = table[code]
    return {"phrase": phrase, "detail": detail, "learn": learn}


def _hit_meta(ticker: str) -> dict[str, str]:
    try:
        hit = resolve(ticker)
        issuer = ISSUERS.get(hit.symbol, hit.asset_id.split(":")[-1].upper())
        return {
            "symbol": hit.symbol,
            "asset_id": hit.asset_id,
            "issuer": ISSUERS.get(ticker.upper(), issuer),
            "venue": hit.venue,
            "kind": hit.instrument_kind,
            "sector": SECTORS.get(ticker.upper()) or SECTORS.get(hit.symbol) or "unknown",
        }
    except (KeyError, ValueError):
        return {
            "symbol": ticker.upper(),
            "asset_id": f"unk:{ticker.upper()}",
            "issuer": ISSUERS.get(ticker.upper(), ticker.upper()),
            "venue": "unknown",
            "kind": "unknown",
            "sector": SECTORS.get(ticker.upper(), "unknown"),
        }


def holdings_nav(holdings: list[dict[str, Any]]) -> tuple[Decimal | None, str | None]:
    """Notional from qty×price. Mixed currencies or a missing price → no ruble NAV."""
    total = Decimal("0")
    ccys: set[str] = set()
    for h in holdings:
        if h.get("price") is None:
            return None, None
        ccys.add(str(h.get("ccy") or "RUB").upper())
        total += Decimal(str(h.get("qty") or "0")) * Decimal(str(h["price"]))
    if total <= 0 or len(ccys) != 1:
        return None, None
    return total, next(iter(ccys))


def analyze_holdings(holdings: list[dict[str, Any]]) -> dict[str, Any]:
    if not is_enabled("qa_concentration"):
        raise RuntimeError("qa_concentration off")
    positions: list[Position] = []
    quotes: dict[str, PriceQuote] = {}
    for h in holdings:
        sym = str(h["ticker"]).upper()
        if h.get("price") is None:
            continue
        if h.get("qty") in (None, ""):
            continue
        qty = Decimal(str(h["qty"]))
        px = Decimal(str(h["price"]))
        ccy = str(h.get("ccy") or "RUB")
        raw_as_of = h.get("as_of")
        try:
            as_of = date.fromisoformat(str(raw_as_of)[:10]) if raw_as_of else date.today()
        except ValueError:
            as_of = date.today()
        raw_type = str(h.get("price_type") or "last_available")
        price_type = raw_type if raw_type in {"official_close", "last_available"} else "last_available"
        positions.append(Position(symbol=sym, qty=qty, ccy=ccy, instrument="equity"))
        quotes[sym] = PriceQuote(
            symbol=sym,
            as_of=as_of,
            price=px,
            ccy=ccy,
            source="concentration",
            price_type=price_type,  # type: ignore[arg-type]
        )
    if not positions:
        return {
            "source": "concentration",
            "empty": True,
            "weights": {},
            "hhi": None,
            "data_status": "нет данных",
            "status": "insufficient_data",
            "reason": "нет цен для весов",
            "explain": {
                "hhi": _explain("hhi", "нет данных", nav=None, ccy=None, enb=None),
                "overlap": _explain("overlap", "нет"),
                "rating": _explain("rating", ""),
            },
        }
    weights, hhi = weights_and_hhi(positions, quotes, {}, Decimal("0"))
    by_sector: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    by_issuer: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    by_venue: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    by_ccy: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    by_asset: dict[str, list[str]] = defaultdict(list)
    rows = []
    for h in holdings:
        meta = _hit_meta(str(h["ticker"]))
        w = weights.get(meta["symbol"]) or weights.get(str(h["ticker"]).upper()) or Decimal("0")
        by_sector[meta["sector"]] += w
        by_issuer[meta["issuer"]] += w
        by_venue[meta["venue"]] += w
        by_ccy[str(h.get("ccy") or "RUB")] += w
        by_asset[meta["asset_id"]].append(meta["symbol"])
        rows.append({**meta, "weight": str(w), "qty": str(h.get("qty") or "0")})
    overlaps = [
        {"asset_id": aid, "tickers": sorted(set(ts)), "via": "asset"}
        for aid, ts in by_asset.items()
        if len(set(ts)) > 1
    ]
    by_iss_tickers: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        by_iss_tickers[r["issuer"]].append(r["symbol"])
    for iss, ts in by_iss_tickers.items():
        if len(set(ts)) > 1 and not any(o["asset_id"].endswith(iss.lower()) or set(o["tickers"]) == set(ts) for o in overlaps):
            overlaps.append({"asset_id": f"issuer:{iss}", "tickers": sorted(set(ts)), "via": "issuer"})
    issuer_overlaps = [
        {"issuer": iss, "weight": str(w)}
        for iss, w in by_issuer.items()
        if w > Decimal("0") and sum(1 for r in rows if r["issuer"] == iss) > 1
    ]
    enb = (Decimal("1") / hhi) if hhi > 0 else Decimal("0")
    nav, nav_ccy = holdings_nav(holdings)
    components = _components(list(weights.keys()))
    return {
        "source": "concentration",
        "config_version": CONFIG_VERSION,
        "weights": {k: str(v) for k, v in weights.items()},
        "hhi": str(hhi),
        "effective_bets": str(enb),
        "nav": str(nav) if nav is not None else None,
        "nav_ccy": nav_ccy,
        "by_sector": {k: str(v) for k, v in by_sector.items()},
        "by_issuer": {k: str(v) for k, v in by_issuer.items()},
        "by_venue": {k: str(v) for k, v in by_venue.items()},
        "by_ccy": {k: str(v) for k, v in by_ccy.items()},
        "positions": rows,
        "hidden_overlaps": overlaps,
        "issuer_overlaps": issuer_overlaps,
        "component_var": components,
        "hidden_risks": {
            "credit_rating": "нет данных",
            "rating_source": None,
            "nearest_offer": None,
            "margin_distance": None,
            "perp_carry": None,
            "liquidity_days": None,
            "venue_risk": "оценка площадки не подставляется без данных",
        },
        "explain": {
            "hhi": _explain("hhi", str(hhi), nav=nav, ccy=nav_ccy, enb=enb),
            "overlap": _explain("overlap", ", ".join(o["asset_id"] for o in overlaps) or "нет"),
            "rating": _explain("rating", ""),
        },
        "disclaimer": "Концентрация описывает состав портфеля, не совет купить или продать.",
    }


def _trade_price(user_id: str, mode: str, ticker: str) -> Decimal | None:
    txns = get_book().transactions(user_id=user_id, mode=mode)  # type: ignore[arg-type]
    for t in reversed(txns):
        if t.ticker.upper() == ticker.upper() and t.kind == "trade" and t.qty != 0:
            return abs(t.amount / t.qty)
    return None


def _rub_holdings(user_id: str, mode: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Book positions priced in roubles (official close → last trade; FX by the Bank of Russia rate)."""
    from app.services.risk_engine.service import _holdings_from_book, _value_rub

    out: list[dict[str, Any]] = []
    missing: list[str] = []
    for h in _holdings_from_book(user_id, mode):
        value = _value_rub(h)
        if value is None:
            missing.append(str(h["ticker"]))
            continue
        qty = abs(float(h["qty"]))
        out.append({"ticker": h["ticker"], "qty": str(qty), "price": str(value / qty if qty else 0.0), "ccy": "RUB"})
    return out, missing


def nav_from_book(*, user_id: str, mode: str = "paper") -> tuple[Decimal | None, str | None]:
    holdings, missing = _rub_holdings(user_id, mode)
    if missing or not holdings:
        return None, None
    return holdings_nav(holdings)


def analyze_portfolio(*, user_id: str, mode: str = "paper") -> dict[str, Any]:
    holdings, missing = _rub_holdings(user_id, mode)
    if not holdings:
        return {
            "source": "concentration",
            "empty": True,
            "weights": {},
            "hidden_overlaps": [],
            "data_status": "нет данных",
            "status": "insufficient_data",
            "reason": "нет цен" if missing else "пустая книга",
            "missing_prices": missing,
        }
    payload = analyze_holdings(holdings)
    payload["empty"] = False
    if missing:
        payload["data_status"] = "недостаточно данных"
        payload["status"] = "insufficient_data"
        payload["reason"] = f"нет цены для: {', '.join(missing)}"
        payload["missing_prices"] = missing
    else:
        payload["data_status"] = "ok"
        book_nav, book_ccy = nav_from_book(user_id=user_id, mode=mode)
        if book_nav is not None:
            payload["nav"] = str(book_nav)
            payload["nav_ccy"] = book_ccy
    return payload


def _components(tickers: list[str]) -> list[dict[str, Any]]:
    cols = []
    used = []
    for t in tickers:
        if t == "CASH":
            continue
        s = get_series(t)
        if len(s) >= 20:
            cols.append(s)
            used.append(t)
    if len(cols) < 2:
        return []
    n = min(len(c) for c in cols)
    matrix = [c[-n:] for c in cols]
    w = [1.0 / len(used)] * len(used)
    alloc = euler_allocate(list(map(list, zip(*matrix))), w)
    return [
        {"ticker": used[i], "component_var": alloc["component_var"][i]}
        for i in range(len(used))
    ]
