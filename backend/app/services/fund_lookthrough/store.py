"""Versioned fund composition store. File tables, no invented zeros."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from app.services.fund_lookthrough.models import FundHolding, FundMeta

_ROOT = Path(__file__).resolve().parents[3]
_MANUAL = _ROOT / "data" / "funds" / "manual"

_holdings: dict[str, list[FundHolding]] = {}
_meta: dict[str, FundMeta] = {}
_ticker_to_figi: dict[str, str] = {}


def reset() -> None:
    _holdings.clear()
    _meta.clear()
    _ticker_to_figi.clear()


def load_manual_dir(path: Path | None = None) -> None:
    folder = path or _MANUAL
    if not folder.is_dir():
        return
    for file in sorted(folder.glob("*.yaml")):
        upsert_yaml(yaml.safe_load(file.read_text(encoding="utf-8")) or {})


def upsert_yaml(doc: dict[str, Any]) -> None:
    figi = str(doc.get("fund_figi") or "").strip()
    if not figi:
        return
    as_of = date.fromisoformat(str(doc["as_of"]))
    ticker = str(doc.get("ticker") or figi).upper()
    ter_raw = doc.get("ter")
    meta = FundMeta(
        fund_figi=figi,
        index_code=doc.get("index_code"),
        ter=None if ter_raw in (None, "") else Decimal(str(ter_raw)),
        as_of=as_of,
        source=str(doc.get("source") or "manual"),
        composition_note=str(doc.get("composition_note") or ""),
        source_url=str(doc.get("source_url") or ""),
        ticker=ticker,
    )
    rows: list[FundHolding] = []
    for raw in doc.get("holdings") or []:
        rows.append(
            FundHolding(
                fund_figi=figi,
                as_of=as_of,
                holding_isin=str(raw.get("holding_isin") or raw.get("isin") or ""),
                holding_name=str(raw.get("holding_name") or raw.get("name") or ""),
                weight=Decimal(str(raw["weight"])),
                asset_class=str(raw.get("asset_class") or "unknown"),
                currency=str(raw["currency"]) if raw.get("currency") else "unknown",
                source_url=str(raw.get("source_url") or meta.source_url),
                issuer=str(raw.get("issuer") or raw.get("holding_name") or "").upper(),
                sector=str(raw.get("sector") or "unknown"),
                country=str(raw["country"]) if raw.get("country") else "unknown",
                is_fund=bool(raw.get("is_fund") or raw.get("child_figi")),
                child_figi=(str(raw["child_figi"]) if raw.get("child_figi") else None),
            )
        )
    _meta[figi] = meta
    _holdings[figi] = rows
    _ticker_to_figi[ticker] = figi
    _ticker_to_figi[figi.upper()] = figi


def resolve_figi(ticker_or_figi: str) -> str | None:
    key = ticker_or_figi.upper()
    return _ticker_to_figi.get(key)


def get_meta(figi: str) -> FundMeta | None:
    return _meta.get(figi)


def get_holdings(figi: str) -> list[FundHolding] | None:
    if figi not in _holdings:
        return None
    return list(_holdings[figi])


def all_figi() -> list[str]:
    return sorted(_meta)
