"""Market Pulse — Fear & Greed composite, breadth, gainers/losers, global snapshot.

Fear & Greed formula (auditable, not a black box):
  Components (equal weight among those available):
  1. VIX inverted: score = clamp(100 - (vix - 12) * 4.0, 0, 100)
     — VIX 12 ≈ 100 (greed), VIX 37 ≈ 0 (fear)
  2. Breadth: score = 100 * advancers / (advancers + decliners) when counts exist
  3. Risk-asset momentum: avg of BTC + SPX daily % mapped via
     score = clamp(50 + change_pct * 8, 0, 100)
  Final fear_greed = round(mean of available component scores).
  Label zones: <=25 Extreme Fear, <=45 Fear, <=55 Neutral, <=75 Greed, else Extreme Greed.
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.services.terminal_platform.market.quotes import (
    GLOBAL_SNAPSHOT_UNIVERSE,
)
from app.services.terminal_platform.market.schemas import (
    BreadthRow,
    GlobalSnapshotItem,
    MarketPulseBlock,
    MoverRow,
)

logger = get_logger(__name__)
FMP_BASE = "https://financialmodelingprep.com/api/v3"


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


def fear_greed_label(score: int) -> str:
    if score <= 25:
        return "Extreme Fear"
    if score <= 45:
        return "Fear"
    if score <= 55:
        return "Neutral"
    if score <= 75:
        return "Greed"
    return "Extreme Greed"


def volatility_regime_from_vix(vix: Optional[float]) -> str:
    if vix is None:
        return "unknown"
    if vix < 15:
        return "calm"
    if vix < 20:
        return "moderate"
    if vix < 30:
        return "elevated"
    return "extreme"


def compute_fear_greed(
    *,
    vix: Optional[float],
    advancers: Optional[int],
    decliners: Optional[int],
    momentum_pcts: list[float],
) -> tuple[Optional[int], dict[str, Any]]:
    components: dict[str, Any] = {}
    scores: list[float] = []

    if vix is not None and vix > 0:
        vix_score = _clamp(100.0 - (vix - 12.0) * 4.0)
        components["vix"] = {"level": vix, "score": round(vix_score, 2)}
        scores.append(vix_score)

    if advancers is not None and decliners is not None and (advancers + decliners) > 0:
        breadth_score = 100.0 * advancers / (advancers + decliners)
        components["breadth"] = {
            "advancers": advancers,
            "decliners": decliners,
            "score": round(breadth_score, 2),
        }
        scores.append(breadth_score)

    moms = [m for m in momentum_pcts if m is not None]
    if moms:
        avg = sum(moms) / len(moms)
        mom_score = _clamp(50.0 + avg * 8.0)
        components["momentum"] = {"avg_change_pct": round(avg, 4), "score": round(mom_score, 2)}
        scores.append(mom_score)

    if not scores:
        return None, {"note": "insufficient_inputs"}

    final = int(round(sum(scores) / len(scores)))
    components["weights"] = "equal among available"
    components["formula"] = (
        "mean(VIX_inverted, breadth_ratio*100, momentum_mapped) — see module docstring"
    )
    return final, components


async def _fmp_movers(kind: str, limit: int = 5) -> list[MoverRow]:
    key = (settings.FMP_API_KEY or "").strip()
    if not key:
        return []
    path = "/stock_market/gainers" if kind == "gainers" else "/stock_market/losers"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=8.0)) as client:
            resp = await client.get(f"{FMP_BASE}{path}", params={"apikey": key})
            resp.raise_for_status()
            data = resp.json()
        if not isinstance(data, list):
            return []
        out: list[MoverRow] = []
        for row in data[:limit]:
            sym = str(row.get("symbol") or "").upper()
            if not sym:
                continue
            chg = row.get("changesPercentage")
            try:
                chg_f = float(chg) if chg is not None else None
            except (TypeError, ValueError):
                chg_f = None
            price = None
            try:
                if row.get("price") is not None:
                    price = float(row["price"])
            except (TypeError, ValueError):
                price = None
            vol = None
            try:
                if row.get("volume") is not None:
                    vol = float(row["volume"])
            except (TypeError, ValueError):
                vol = None
            out.append(
                MoverRow(
                    symbol=sym,
                    change_pct=chg_f,
                    price=price,
                    volume=vol,
                    name=row.get("name"),
                )
            )
        return out
    except Exception as exc:
        logger.warning("FMP movers failed", kind=kind, error=str(exc))
        return []


async def _moex_breadth() -> BreadthRow:
    """Best-effort MOEX advancers/decliners from ISS securities list sample."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(12.0, connect=8.0)) as client:
            url = (
                "https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities.json"
                "?iss.meta=off&iss.only=securities&securities.columns=SECID,LASTTOPREVPRICE"
            )
            resp = await client.get(url)
            resp.raise_for_status()
            payload = resp.json()
        block = (payload or {}).get("securities") or {}
        cols = block.get("columns") or []
        rows = block.get("data") or []
        if "LASTTOPREVPRICE" not in cols:
            return BreadthRow(
                exchange="MOEX",
                status="no_data",
                reason="LASTTOPREVPRICE column missing",
            )
        idx = cols.index("LASTTOPREVPRICE")
        adv = dec = unch = 0
        for row in rows:
            if not row or len(row) <= idx:
                continue
            raw = row[idx]
            if raw is None:
                continue
            try:
                chg = float(raw)
            except (TypeError, ValueError):
                continue
            if chg > 0:
                adv += 1
            elif chg < 0:
                dec += 1
            else:
                unch += 1
        if adv + dec + unch == 0:
            return BreadthRow(exchange="MOEX", status="no_data", reason="empty_board")
        return BreadthRow(
            exchange="MOEX",
            advancers=adv,
            decliners=dec,
            unchanged=unch,
            status="ok",
        )
    except Exception as exc:
        return BreadthRow(exchange="MOEX", status="no_data", reason=str(exc))


def _movers_from_quotes(quotes: list[dict[str, Any]], limit: int = 5) -> tuple[list[MoverRow], list[MoverRow]]:
    scored: list[MoverRow] = []
    for q in quotes:
        if q.get("status") != "ok":
            continue
        chg = q.get("change_pct")
        if chg is None:
            continue
        scored.append(
            MoverRow(
                symbol=str(q.get("display") or q.get("symbol")),
                change_pct=float(chg),
                price=q.get("price"),
                volume=q.get("volume"),
            )
        )
    gainers = sorted([m for m in scored if (m.change_pct or 0) > 0], key=lambda m: m.change_pct or 0, reverse=True)[
        :limit
    ]
    losers = sorted([m for m in scored if (m.change_pct or 0) < 0], key=lambda m: m.change_pct or 0)[:limit]
    return gainers, losers


async def build_global_snapshot() -> list[GlobalSnapshotItem]:
    from app.services.terminal_platform.market.index_fallbacks import fetch_index_quote_with_fallbacks

    async def one(key: str, ui: str, api: str, label: str) -> GlobalSnapshotItem:
        preferred = "binance_public" if key == "BTC" else None
        q = await fetch_index_quote_with_fallbacks(
            api,
            preferred_provider=preferred,
            chain_budget_s=4.0,
            try_native=True,
        )
        price = q.get("price") if q.get("status") == "ok" else None
        chg = q.get("change_pct") if q.get("status") == "ok" else None
        provider = q.get("provider")
        if price is None and chg is None:
            return GlobalSnapshotItem(
                key=key,
                symbol=ui,
                label=label,
                status="no_data",
                reason=str(q.get("reason") or "no_data"),
                provider=provider,
            )
        return GlobalSnapshotItem(
            key=key,
            symbol=ui,
            label=label,
            price=price,
            change_pct=chg,
            provider=provider,
            status="ok",
        )

    return list(
        await asyncio.gather(
            *[one(k, ui, api, label) for k, ui, api, label in GLOBAL_SNAPSHOT_UNIVERSE]
        )
    )


async def build_pulse(
    *,
    seed_quotes: Optional[list[dict[str, Any]]] = None,
    index_change_pcts: Optional[dict[str, Optional[float]]] = None,
) -> MarketPulseBlock:
    """Assemble Market Pulse block (best-effort; honest no_data where missing)."""
    from app.services.terminal_platform.market.batch_enrich import (
        PULSE_MOVER_UNIVERSE,
        enrich_change_map,
    )

    seed_quotes = seed_quotes or []
    index_change_pcts = index_change_pcts or {}

    global_snap, moex_breadth, fmp_gainers, fmp_losers, mover_batch = await asyncio.gather(
        build_global_snapshot(),
        _moex_breadth(),
        _fmp_movers("gainers", limit=8),
        _fmp_movers("losers", limit=8),
        enrich_change_map(list(PULSE_MOVER_UNIVERSE)),
    )

    vix_item = next((g for g in global_snap if g.key == "VIX"), None)
    vix = vix_item.price if vix_item and vix_item.status == "ok" else None

    # Build mover quotes from batch universe (always has change_pct when history works)
    batch_quotes: list[dict[str, Any]] = []
    for sym, row in mover_batch.items():
        if row.get("status") != "ok" or row.get("change_pct") is None:
            continue
        batch_quotes.append(
            {
                "symbol": sym,
                "display": sym.replace("-USD", ""),
                "status": "ok",
                "price": row.get("price"),
                "change_pct": row.get("change_pct"),
                "volume": row.get("volume"),
            }
        )

    local_gainers, local_losers = _movers_from_quotes(seed_quotes + batch_quotes, limit=6)
    batch_gainers, batch_losers = _movers_from_quotes(batch_quotes, limit=6)

    # Prefer FMP exchange movers; fall back to batch universe ranked by real %
    gainers = fmp_gainers or batch_gainers or local_gainers
    losers = fmp_losers or batch_losers or local_losers
    # If FMP returned rows without change_pct, merge batch
    if gainers and all(g.change_pct is None for g in gainers):
        gainers = batch_gainers or local_gainers
    if losers and all(g.change_pct is None for g in losers):
        losers = batch_losers or local_losers

    breadth: list[BreadthRow] = [moex_breadth]

    # US liquid-universe breadth estimate from batch mover set
    if batch_quotes:
        adv = sum(1 for q in batch_quotes if (q.get("change_pct") or 0) > 0)
        dec = sum(1 for q in batch_quotes if (q.get("change_pct") or 0) < 0)
        unch = len(batch_quotes) - adv - dec
        breadth.append(
            BreadthRow(
                exchange="US_LIQUID",
                advancers=adv,
                decliners=dec,
                unchanged=unch,
                status="estimated",
                reason="adv/dec from liquid US+ETF+crypto universe via yfinance/FMP batch",
            )
        )
    if local_gainers or local_losers:
        breadth.append(
            BreadthRow(
                exchange="WATCHLIST",
                advancers=len([g for g in local_gainers if (g.change_pct or 0) > 0]),
                decliners=len([g for g in local_losers if (g.change_pct or 0) < 0]),
                status="estimated",
                reason="derived from watchlist/index quote set",
            )
        )
    if len(breadth) == 1 and breadth[0].status == "no_data":
        breadth.append(
            BreadthRow(
                exchange="NYSE",
                status="no_data",
                reason="full NYSE breadth feed not wired; liquid-universe estimate also empty",
            )
        )

    moms: list[float] = []
    for key in ("SPX", "BTC"):
        v = index_change_pcts.get(key)
        if v is not None:
            moms.append(float(v))
    btc = next((g for g in global_snap if g.key == "BTC"), None)
    if btc and btc.change_pct is not None and "BTC" not in index_change_pcts:
        moms.append(float(btc.change_pct))
    # Also pull SPY/BTC from mover batch if missing
    if "SPX" not in index_change_pcts or index_change_pcts.get("SPX") is None:
        spy = mover_batch.get("SPY") or {}
        if spy.get("change_pct") is not None:
            moms.append(float(spy["change_pct"]))
    if btc is None or btc.change_pct is None:
        btc_b = mover_batch.get("BTC-USD") or {}
        if btc_b.get("change_pct") is not None:
            moms.append(float(btc_b["change_pct"]))

    adv = moex_breadth.advancers if moex_breadth.status == "ok" else None
    dec = moex_breadth.decliners if moex_breadth.status == "ok" else None
    us_row = next((b for b in breadth if b.exchange == "US_LIQUID" and b.status == "estimated"), None)
    if adv is None and us_row is not None:
        adv = us_row.advancers
        dec = us_row.decliners
    if adv is None and (local_gainers or batch_gainers):
        adv = len(gainers)
        dec = len(losers)

    score, components = compute_fear_greed(
        vix=vix,
        advancers=adv,
        decliners=dec,
        momentum_pcts=moms,
    )

    return MarketPulseBlock(
        fear_greed=score,
        label=fear_greed_label(score) if score is not None else None,
        fear_greed_components=components,
        breadth=breadth,
        gainers=gainers[:6],
        losers=losers[:6],
        global_snapshot=global_snap,
        volatility_regime=volatility_regime_from_vix(vix),
    )
