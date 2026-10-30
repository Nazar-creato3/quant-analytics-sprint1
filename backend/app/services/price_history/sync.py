"""Fill the price-history store: MOEX securities from ISS, the rest from the US EOD providers."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

from app.core.logging import get_logger
from app.services.price_history import moex, store

logger = get_logger(__name__)

BENCHMARKS = ("IMOEX", "RGBITR")
FX = ("USD", "EUR", "CNY")
STALE_AFTER = timedelta(hours=20)


def fx_key(ccy: str) -> str:
    return f"FX_{ccy.upper()}"


def universe() -> list[str]:
    from app.services.portfolio_book.store import get_book
    from app.services.sample_portfolio.service import sample_tickers

    seen: dict[str, None] = {}
    for t in [*get_book().all_tickers(), *sample_tickers(), *BENCHMARKS]:
        seen[t.upper()] = None
    return list(seen)


def _fresh(ticker: str) -> bool:
    data = store.read(ticker) or {}
    raw = data.get("synced_at")
    if not raw or not data.get("bars"):
        return False
    try:
        at = datetime.fromisoformat(str(raw))
    except ValueError:
        return False
    return datetime.now(timezone.utc) - at < STALE_AFTER


async def _us_bars(ticker: str) -> list[list[Any]]:
    from app.services.market_data.equity_eod_store import fetch_symbol_bars, read_bars

    rows = read_bars(ticker)
    if len(rows) < 30:
        rows, _ = await fetch_symbol_bars(ticker)
    out: list[list[Any]] = []
    for b in rows:
        try:
            close = float(b["close"])
            vol = float(b.get("volume") or 0) or None
            out.append([str(b["timestamp"])[:10], close, None, vol])
        except (KeyError, TypeError, ValueError):
            continue
    return out


async def _sync_payouts(ticker: str, where: dict[str, Any]) -> None:
    """Dividends (shares) or coupons/amortisations (bonds) next to the price file."""
    try:
        if where.get("market") == "bonds":
            sched = await moex.bondization(ticker)
            store.write(f"PAY_{ticker}", {"source": "moex_iss", "kind": "bond", **sched})
        elif where.get("market") == "shares" and where.get("board") in {"TQBR", "TQDE", "SMAL"}:
            store.write(f"PAY_{ticker}", {"source": "moex_iss", "kind": "dividend", "dividends": await moex.dividends(ticker)})
    except Exception as exc:  # noqa: BLE001
        logger.warning("price_history_payouts_failed", ticker=ticker, error=str(exc)[:200])


async def sync_one(ticker: str, *, force: bool = False) -> dict[str, Any]:
    ticker = ticker.upper()
    if not force and _fresh(ticker):
        return {"ticker": ticker, "status": "fresh"}
    try:
        if ticker in BENCHMARKS:
            where = {"engine": "stock", "market": "index", "board": "SNDX", "ccy": "RUB"}
        else:
            where = await moex.locate(ticker)
        if where:
            bars = await moex.history(ticker, where)
            if bars:
                store.write(ticker, {"source": "moex_iss", **where, "bars": bars})
                await _sync_payouts(ticker, where)
                return {"ticker": ticker, "status": "ok", "source": "moex_iss", "n": len(bars)}
        bars = await _us_bars(ticker)
        if bars:
            store.write(ticker, {"source": "us_eod", "market": "us", "ccy": "USD", "bars": bars})
            return {"ticker": ticker, "status": "ok", "source": "us_eod", "n": len(bars)}
    except Exception as exc:  # noqa: BLE001 — one bad ticker must not stop the run
        logger.warning("price_history_sync_failed", ticker=ticker, error=str(exc)[:200])
        return {"ticker": ticker, "status": "error", "error": str(exc)[:200]}
    return {"ticker": ticker, "status": "no_data"}


async def sync_fx(*, force: bool = False) -> list[dict[str, Any]]:
    out = []
    for ccy in FX:
        key = fx_key(ccy)
        if not force and _fresh(key):
            out.append({"ticker": key, "status": "fresh"})
            continue
        bars = await moex.fx_history(ccy)
        if bars:
            store.write(key, {"source": "cbr", "market": "fx", "ccy": "RUB", "bars": bars})
        out.append({"ticker": key, "status": "ok" if bars else "no_data", "n": len(bars)})
    return out


async def sync(tickers: Iterable[str] | None = None, *, force: bool = False, concurrency: int = 4) -> dict[str, Any]:
    names = [t.upper() for t in (tickers or universe())]
    sem = asyncio.Semaphore(concurrency)

    async def run(t: str) -> dict[str, Any]:
        async with sem:
            return await sync_one(t, force=force)

    results = await asyncio.gather(*(run(t) for t in names))
    fx = await sync_fx(force=force)
    ok = sum(1 for r in results if r["status"] in {"ok", "fresh"})
    logger.info("price_history_sync", total=len(names), ok=ok)
    return {"total": len(names), "ok": ok, "items": results, "fx": fx}


def schedule(tickers: Iterable[str]) -> None:
    """Fire-and-forget sync from a request (e.g. right after the sample portfolio is loaded)."""
    import os
    import time

    now = time.monotonic()
    for k in [k for k, at in _ASKED.items() if now - at > 900]:
        _ASKED.pop(k, None)
    names = [t.upper() for t in tickers if t.upper() not in _IN_FLIGHT and t.upper() not in _ASKED and not _fresh(t)]
    if not names:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # Called from a worker thread (sync endpoint): hand it to Celery instead.
        if os.environ.get("APP_ENV", "").strip().lower() not in {"production", "staging"}:
            return
        for n in names:
            _ASKED[n] = now
        try:
            from app.tasks.price_history import sync_price_history_task

            sync_price_history_task.apply_async(kwargs={"tickers": names}, queue="ingestion")
        except Exception as exc:  # noqa: BLE001 — broker down: the nightly run catches up
            logger.debug("price_history_enqueue_failed", error=str(exc)[:160])
        return
    _IN_FLIGHT.update(names)
    for n in names:
        _ASKED[n] = now
    task = loop.create_task(sync(names))
    _BACKGROUND.add(task)

    def _done(t: asyncio.Task) -> None:
        _BACKGROUND.discard(t)
        _IN_FLIGHT.difference_update(names)

    task.add_done_callback(_done)


_BACKGROUND: set[asyncio.Task] = set()
_IN_FLIGHT: set[str] = set()
_ASKED: dict[str, float] = {}  # ticker → monotonic time it was handed to Celery
