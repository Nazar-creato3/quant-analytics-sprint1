"""Paper book from beat ranks: who, weight, later vs-benchmark realize."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def _construct_retail(
    rows: list[Mapping[str, Any]],
    cap: float,
    *,
    hist_returns: Mapping[str, list[float]] | None = None,
) -> dict[str, Any] | None:
    try:
        from app.services.construction.construct import construct_sleeve
        from app.services.ops_desk.live_hooks import live_sensors

        symbols = [str(r.get("symbol") or "").upper() for r in rows if r.get("symbol")]
        sn = live_sensors(symbols)
        hist = dict(hist_returns or {}) or dict(sn.get("hist") or {})
        spy = list(hist.get("SPY") or sn.get("spy") or []) or None
        return construct_sleeve(
            rows,
            settings_cap=cap,
            account_total=cap,
            sleeve="retail_long_only",
            hist=hist or None,
            spy=spy,
            fills_by_symbol=sn.get("fills_by_symbol"),
            ff_rows=sn.get("ff_rows"),
            day_pnl_frac=float(sn.get("day_pnl_frac") or 0.0),
            dd_frac=float(sn.get("dd_frac") or 0.0),
            last_bar=sn.get("last_bar"),
            broker_connected=sn.get("broker_connected", True),
            stale_hours=float(sn.get("stale_hours") or 80.0),
        )
    except Exception as exc:
        logger.debug("construction skip", error=str(exc)[:160])
        return None


def _book_dir() -> Path:
    raw = getattr(settings, "DAILY_BOOK_DIR", "") or ""
    return Path(raw) if raw.strip() else Path("/app/data/daily_books")


def build_daily_book(
    rows: list[Mapping[str, Any]],
    *,
    top_n: int = 8,
    min_score: int = 6,
    hist_returns: Mapping[str, list[float]] | None = None,
    retail_cap_usd: float | None = None,
    sectors: Sequence[str] | None = None,
    size: Sequence[float] | None = None,
    beta: Sequence[float] | None = None,
) -> dict[str, Any]:
    """Conviction-weighted names with score_20 >= min_score. Honest empty book if none.

    Also attaches CS long-short and retail long-only sleeves (alpha factory).
    """
    picked = [
        r
        for r in rows
        if int(r.get("score_21") or r.get("score_5") or r.get("score_20") or 0) >= min_score
        and str(r.get("symbol") or "").strip()
    ]
    picked.sort(
        key=lambda r: int(r.get("score_21") or r.get("score_5") or r.get("score_20") or 0),
        reverse=True,
    )
    picked = picked[:top_n]
    n = len(picked)
    from app.services.forecast.book_allocator import allocate_book_weights

    weights, scheme = allocate_book_weights(picked, hist_returns=hist_returns)
    holdings = [
        {
            "symbol": str(r["symbol"]).upper(),
            "score_21": int(r.get("score_21") or r.get("score_20") or 0),
            "score_5": int(r.get("score_5") or 0),
            "score_1": int(r.get("score_1") or 0),
            "score_20": int(r.get("score_21") or r.get("score_20") or 0),
            "p_beat_21": r.get("p_beat_21", r.get("p_beat_20")),
            "p_beat_20": r.get("p_beat_21", r.get("p_beat_20")),
            "weight": round(weights[i], 6) if i < len(weights) else 0.0,
        }
        for i, r in enumerate(picked)
    ]
    as_of = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    cap = float(retail_cap_usd) if retail_cap_usd is not None else float(
        getattr(settings, "DEFAULT_PORTFOLIO_SIZE", 0.0) or 0.0
    )
    if cap <= 0:
        cap = 250.0
    from app.services.alpha.books import dual_books, sleeve_to_dict

    dual = dual_books(
        list(rows),
        as_of=as_of,
        cap_usd=cap,
        sectors=sectors,
        size=size,
        beta=beta,
        min_score=float(min_score),
    )
    return {
        "as_of": as_of,
        "holdings": holdings,
        "count": n,
        "scheme": scheme,
        "sleeves": {
            "cross_sectional": sleeve_to_dict(dual.cross_sectional),
            "retail_long_only": sleeve_to_dict(dual.retail_long_only),
        },
        "construction": _construct_retail(picked, cap, hist_returns=hist_returns),
        "note_ru": (
            "Бумажная книга из рангов. Вес ∝ (p_beat−0.5)×score, потолок 25%. "
            "CS long-short — нейтральный residual; retail — long-only под cap. "
            "Не live-ордера. Пусто, если никто не набрал 6."
        ),
    }


def realize_book(
    book: Mapping[str, Any],
    asset_returns: Mapping[str, float],
    benchmark_return: float,
) -> dict[str, Any]:
    """Book excess vs benchmark using provided 1-day (or 20d) returns. No fetch."""
    holdings = list(book.get("holdings") or [])
    if not holdings:
        return {**dict(book), "realized": False, "book_return": None, "excess": None}
    port = 0.0
    used = 0.0
    for h in holdings:
        sym = str(h.get("symbol") or "").upper()
        w = float(h.get("weight") or 0.0)
        if sym not in asset_returns:
            continue
        port += w * float(asset_returns[sym])
        used += w
    if used <= 1e-12:
        return {**dict(book), "realized": False, "book_return": None, "excess": None}
    port /= used
    excess = port - float(benchmark_return)
    return {
        **dict(book),
        "realized": True,
        "book_return": round(port, 6),
        "benchmark_return": round(float(benchmark_return), 6),
        "excess": round(excess, 6),
    }


def persist_rank_index(items: list[Mapping[str, Any]]) -> Path | None:
    folder = _book_dir()
    try:
        folder.mkdir(parents=True, exist_ok=True)
        payload = {
            str(r.get("symbol") or "").upper(): {
                "score_21": int(r.get("score_21") or r.get("score_20") or 0),
                "score_5": int(r.get("score_5") or 0),
                "score_1": int(r.get("score_1") or 0),
                "score_20": int(r.get("score_21") or r.get("score_20") or 0),
                "p_beat_21": r.get("p_beat_21", r.get("p_beat_20")),
                "p_beat_20": r.get("p_beat_21", r.get("p_beat_20")),
            }
            for r in items
            if str(r.get("symbol") or "").strip()
        }
        path = folder / "latest_ranks.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path
    except OSError:
        return None


def score_20_for_symbol(symbol: str) -> int | None:
    path = _book_dir() / "latest_ranks.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    row = payload.get((symbol or "").strip().upper())
    if not row:
        return None
    try:
        return int(row.get("score_21") or row.get("score_20"))
    except (TypeError, ValueError):
        return None


def persist_daily_book(book: Mapping[str, Any]) -> Path | None:
    folder = _book_dir()
    day = str(book.get("as_of") or datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    try:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{day}.json"
        path.write_text(json.dumps(book, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
    except OSError as exc:
        logger.debug("daily book persist skip", error=str(exc)[:120])
        return None


def load_book(day: str | None = None) -> dict[str, Any] | None:
    folder = _book_dir()
    if day:
        path = folder / f"{day}.json"
    else:
        files = sorted(folder.glob("????-??-??.json"))
        path = files[-1] if files else None
    if path is None or not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def persist_realized(book: Mapping[str, Any]) -> Path | None:
    folder = _book_dir()
    day = str(book.get("as_of") or datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    try:
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{day}.realized.json"
        path.write_text(json.dumps(book, ensure_ascii=False, indent=2), encoding="utf-8")
        hist = folder / "excess_history.jsonl"
        if book.get("realized") and book.get("excess") is not None:
            with hist.open("a", encoding="utf-8") as fh:
                fh.write(
                    json.dumps(
                        {"as_of": day, "excess": book.get("excess"), "book_return": book.get("book_return")}
                    )
                    + "\n"
                )
        return path
    except OSError as exc:
        logger.debug("realized book persist skip", error=str(exc)[:120])
        return None


def excess_history() -> list[float]:
    path = _book_dir() / "excess_history.jsonl"
    if not path.is_file():
        return []
    out: list[float] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("excess") is not None:
                out.append(float(row["excess"]))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return out
    return out
