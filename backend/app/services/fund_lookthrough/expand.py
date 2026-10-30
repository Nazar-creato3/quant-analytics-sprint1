"""Recursive fund expand (depth ≤ 3). Missing composition stays one line."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from app.services.fund_lookthrough.models import MAX_DEPTH, STALE_DAYS
from app.services.fund_lookthrough.store import get_holdings, get_meta, resolve_figi


def _age_days(as_of: date) -> int:
    today = datetime.now(timezone.utc).date()
    return (today - as_of).days


def _leaf(
    *,
    key: str,
    name: str,
    weight: Decimal,
    asset_class: str,
    currency: str,
    issuer: str,
    sector: str,
    country: str,
    source_url: str,
    as_of: date | None,
    note: str,
    disclosed: bool,
    path: tuple[str, ...],
) -> dict[str, Any]:
    stale = as_of is not None and _age_days(as_of) > STALE_DAYS
    return {
        "key": key,
        "holding_isin": key,
        "holding_name": name,
        "weight": weight,
        "asset_class": asset_class,
        "currency": currency,
        "issuer": issuer,
        "sector": sector,
        "country": country,
        "source_url": source_url,
        "as_of": as_of.isoformat() if as_of else None,
        "stale": stale,
        "composition_note": note,
        "disclosed": disclosed,
        "path": list(path),
    }


def expand_fund(figi: str, scale: Decimal, depth: int = 0, path: tuple[str, ...] = ()) -> list[dict[str, Any]]:
    meta = get_meta(figi)
    rows = get_holdings(figi)
    if meta is None or rows is None or not rows:
        return [
            _leaf(
                key=figi,
                name=figi,
                weight=scale,
                asset_class="fund",
                currency="RUB",
                issuer=figi,
                sector="fund",
                country="RU",
                source_url="",
                as_of=None,
                note="состав не раскрыт",
                disclosed=False,
                path=path + (figi,),
            )
        ]
    if depth >= MAX_DEPTH:
        return [
            _leaf(
                key=figi,
                name=meta.ticker,
                weight=scale,
                asset_class="fund",
                currency="RUB",
                issuer=figi,
                sector="fund",
                country="RU",
                source_url=meta.source_url,
                as_of=meta.as_of,
                note=meta.composition_note,
                disclosed=True,
                path=path + (figi,),
            )
        ]
    out: list[dict[str, Any]] = []
    for row in rows:
        child_scale = scale * row.weight
        child_path = path + (figi,)
        if row.is_fund and row.child_figi:
            out.extend(expand_fund(row.child_figi, child_scale, depth + 1, child_path))
            continue
        out.append(
            _leaf(
                key=row.holding_isin or row.holding_name,
                name=row.holding_name,
                weight=child_scale,
                asset_class=row.asset_class,
                currency=row.currency,
                issuer=row.issuer,
                sector=row.sector,
                country=row.country,
                source_url=row.source_url,
                as_of=row.as_of,
                note=meta.composition_note,
                disclosed=True,
                path=child_path,
            )
        )
    return out


def expand_position(ticker: str, weight: Decimal) -> list[dict[str, Any]]:
    figi = resolve_figi(ticker)
    if figi is None:
        return [
            _leaf(
                key=ticker.upper(),
                name=ticker.upper(),
                weight=weight,
                asset_class="equity",
                currency="RUB",
                issuer=ticker.upper(),
                sector="unknown",
                country="RU",
                source_url="",
                as_of=None,
                note="",
                disclosed=True,
                path=(ticker.upper(),),
            )
        ]
    return expand_fund(figi, weight)


def merge_leaves(leaves: list[dict[str, Any]], dimension: str) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for leaf in leaves:
        if dimension == "issuer":
            key = str(leaf["issuer"])
        elif dimension == "sector":
            key = str(leaf["sector"])
        elif dimension == "asset_class":
            key = str(leaf["asset_class"])
        elif dimension == "currency":
            key = str(leaf["currency"])
        elif dimension == "country":
            key = str(leaf["country"])
        else:
            key = str(leaf["key"])
        bucket = buckets.setdefault(
            key,
            {
                "key": key,
                "weight": Decimal("0"),
                "as_of": leaf.get("as_of"),
                "stale": bool(leaf.get("stale")),
                "source_url": leaf.get("source_url") or "",
                "composition_note": leaf.get("composition_note") or "",
                "disclosed": bool(leaf.get("disclosed")),
                "asset_class": leaf.get("asset_class"),
                "issuer": leaf.get("issuer"),
            },
        )
        bucket["weight"] += leaf["weight"]
        if leaf.get("stale"):
            bucket["stale"] = True
        if not leaf.get("disclosed"):
            bucket["disclosed"] = False
    merged = list(buckets.values())
    merged.sort(key=lambda r: r["weight"], reverse=True)
    return merged


def composition_map(figi: str) -> dict[str, Decimal]:
    leaves = expand_fund(figi, Decimal("1"))
    acc: dict[str, Decimal] = {}
    for leaf in leaves:
        key = str(leaf["holding_isin"] or leaf["key"])
        acc[key] = acc.get(key, Decimal("0")) + leaf["weight"]
    return acc


def pair_overlap(left_figi: str, right_figi: str) -> Decimal:
    a = composition_map(left_figi)
    b = composition_map(right_figi)
    keys = set(a) | set(b)
    return sum((min(a.get(k, Decimal("0")), b.get(k, Decimal("0"))) for k in keys), Decimal("0"))
