"""Look-through exposure, overlaps, hidden concentration.

Methodology: docs/methodology/fund-look-through.md
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from time import perf_counter
from typing import Any

from app.services.fund_lookthrough.expand import (
    expand_position,
    merge_leaves,
    pair_overlap,
)
from app.services.fund_lookthrough.store import all_figi, get_meta, load_manual_dir, resolve_figi
from app.services.qa.feature_flags import is_enabled
from app.services.risk_engine.service import _holdings_from_book, _nav_weights

HIDDEN_GAP = Decimal("0.05")
HIDDEN_SHARE = Decimal("0.10")
BY_VALUES = frozenset({"issuer", "sector", "asset_class", "currency", "country"})


def _empty(reason: str) -> dict[str, Any]:
    return {
        "data_status": "нет данных",
        "reason": reason,
        "view": None,
        "by": None,
        "rows": [],
        "hidden": [],
        "overlaps": [],
        "missing": [],
        "methodology": "/methodology/fund-look-through",
    }


def _direct_weights(holdings: list[dict], weights: list[float]) -> list[tuple[str, Decimal]]:
    out: list[tuple[str, Decimal]] = []
    for holding, weight in zip(holdings, weights, strict=False):
        ticker = str(holding.get("ticker") or "").upper()
        if not ticker:
            continue
        out.append((ticker, Decimal(str(weight))))
    return out


def issuer_weights(user_id: str, *, mode: str = "paper") -> dict[str, Decimal]:
    """Public API for K4 / 60 / 62: look-through issuer weights. Empty dict = нет данных."""
    payload = lookthrough_portfolio(user_id, mode=mode, by="issuer", view="lookthrough")
    if payload.get("data_status") == "нет данных":
        return {}
    return {str(row["key"]): Decimal(str(row["weight"])) for row in payload.get("rows") or []}


def lookthrough_rows(user_id: str, *, mode: str = "paper", by: str = "issuer") -> list[dict[str, Any]]:
    payload = lookthrough_portfolio(user_id, mode=mode, by=by, view="lookthrough")
    return list(payload.get("rows") or [])


def lookthrough_portfolio(
    user_id: str,
    *,
    mode: str = "paper",
    by: str = "issuer",
    view: str = "lookthrough",
) -> dict[str, Any]:
    started = perf_counter()
    if not is_enabled("qa_fund_lookthrough"):
        return _empty("нет данных")
    if not all_figi():
        load_manual_dir()
    if by not in BY_VALUES:
        return _empty("нет данных")
    holdings = _holdings_from_book(user_id, mode)
    weights = _nav_weights(holdings)
    if not holdings or weights is None:
        return _empty("нет весов позиций")
    pairs = _direct_weights(holdings, weights)
    missing: list[str] = []
    leaves: list[dict[str, Any]] = []
    if view == "broker":
        by_ticker = {
            str(h.get("ticker") or "").upper(): h
            for h in holdings
            if h.get("ticker")
        }
        for ticker, weight in pairs:
            holding = by_ticker.get(ticker) or {}
            currency = holding.get("currency")
            country = holding.get("country")
            sector = holding.get("sector")
            asset_class = holding.get("asset_class")
            leaves.extend(
                [
                    {
                        "key": ticker,
                        "holding_isin": ticker,
                        "holding_name": str(holding.get("name") or ticker),
                        "weight": weight,
                        "asset_class": str(asset_class) if asset_class else "unknown",
                        "currency": str(currency) if currency else "unknown",
                        "issuer": ticker,
                        "sector": str(sector) if sector else "unknown",
                        "country": str(country) if country else "unknown",
                        "source_url": "",
                        "as_of": None,
                        "stale": False,
                        "composition_note": "как у брокера",
                        "disclosed": True,
                    }
                ]
            )
    else:
        for ticker, weight in pairs:
            figi = resolve_figi(ticker)
            if figi and get_meta(figi) is None:
                missing.append(ticker)
            expanded = expand_position(ticker, weight)
            if figi and any(not leaf.get("disclosed") for leaf in expanded):
                missing.append(ticker)
            leaves.extend(expanded)
    rows = merge_leaves(leaves, by)
    hidden = _hidden(pairs, leaves) if view == "lookthrough" and by == "issuer" else []
    overlaps = _overlaps(pairs) if view == "lookthrough" else []
    as_of_values = [leaf.get("as_of") for leaf in leaves if leaf.get("as_of")]
    stale = any(leaf.get("stale") for leaf in leaves)
    status = "ok"
    if missing:
        status = "частично"
    serialized = []
    for row in rows:
        serialized.append(
            {
                "key": row["key"],
                "weight": str(row["weight"]),
                "as_of": row.get("as_of"),
                "stale": bool(row.get("stale")),
                "source_url": row.get("source_url") or "",
                "composition_note": row.get("composition_note") or "",
                "disclosed": bool(row.get("disclosed", True)),
                "asset_class": row.get("asset_class"),
            }
        )
    return {
        "data_status": status,
        "reason": "состав не раскрыт: " + ", ".join(sorted(set(missing))) if missing else None,
        "view": view,
        "by": by,
        "rows": serialized,
        "hidden": hidden,
        "overlaps": overlaps,
        "missing": sorted(set(missing)),
        "as_of": max(as_of_values) if as_of_values else None,
        "stale": stale,
        "source": "состав фонда",
        "methodology": "/methodology/fund-look-through",
        "elapsed_ms": round((perf_counter() - started) * 1000.0, 3),
    }


def _hidden(pairs: list[tuple[str, Decimal]], leaves: list[dict[str, Any]]) -> list[dict[str, Any]]:
    direct: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for ticker, weight in pairs:
        if resolve_figi(ticker):
            continue
        direct[ticker] += weight
    look: dict[str, Decimal] = defaultdict(lambda: Decimal("0"))
    for leaf in leaves:
        look[str(leaf["issuer"])] += leaf["weight"]
    cards = []
    for issuer, lt in look.items():
        d = direct.get(issuer, Decimal("0"))
        if lt > HIDDEN_SHARE or (lt - d) > HIDDEN_GAP:
            cards.append(
                {
                    "issuer": issuer,
                    "lookthrough": str(lt),
                    "direct": str(d),
                    "gap": str(lt - d),
                }
            )
    cards.sort(key=lambda c: Decimal(c["lookthrough"]), reverse=True)
    return cards


def _overlaps(pairs: list[tuple[str, Decimal]]) -> list[dict[str, Any]]:
    funds = []
    for ticker, _weight in pairs:
        figi = resolve_figi(ticker)
        if figi and get_meta(figi) is not None:
            funds.append((ticker, figi))
    matrix: list[dict[str, Any]] = []
    for i, (left_t, left_f) in enumerate(funds):
        for right_t, right_f in funds[i + 1 :]:
            matrix.append(
                {
                    "left": left_t,
                    "right": right_t,
                    "overlap": str(pair_overlap(left_f, right_f)),
                }
            )
    return matrix


def fund_holdings_payload(figi_or_ticker: str) -> dict[str, Any]:
    if not is_enabled("qa_fund_lookthrough"):
        return {"data_status": "нет данных", "reason": "нет данных", "holdings": []}
    if not all_figi():
        load_manual_dir()
    figi = resolve_figi(figi_or_ticker) or figi_or_ticker
    meta = get_meta(figi)
    from app.services.fund_lookthrough.store import get_holdings

    rows = get_holdings(figi)
    if meta is None or rows is None:
        return {
            "data_status": "нет данных",
            "reason": "состав не раскрыт",
            "fund_figi": figi,
            "holdings": [],
            "methodology": "/methodology/fund-look-through",
        }
    from app.services.fund_lookthrough.expand import _age_days

    stale = _age_days(meta.as_of) > 95
    return {
        "data_status": "ok",
        "fund_figi": figi,
        "ticker": meta.ticker,
        "index_code": meta.index_code,
        "ter": None if meta.ter is None else str(meta.ter),
        "as_of": meta.as_of.isoformat(),
        "stale": stale,
        "source": meta.source,
        "composition_note": meta.composition_note,
        "source_url": meta.source_url,
        "holdings": [
            {
                "holding_isin": row.holding_isin,
                "holding_name": row.holding_name,
                "weight": str(row.weight),
                "asset_class": row.asset_class,
                "currency": row.currency,
                "issuer": row.issuer,
                "sector": row.sector,
                "country": row.country,
                "is_fund": row.is_fund,
                "child_figi": row.child_figi,
            }
            for row in rows
        ],
        "methodology": "/methodology/fund-look-through",
    }
