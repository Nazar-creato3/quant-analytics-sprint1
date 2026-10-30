"""Compact nightly market digest — replace re-reading world ZIPs at analysis time.

Raw Stooq/EOD files stay as *fallback bars*. The digest is what pipelines should
read first: coverage, regime, movers, macro hint, content hash.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


def digest_dir() -> Path:
    raw = (settings.EQUITY_EOD_DIR or "").strip()
    if raw:
        return Path(raw).resolve().parent / "digests"
    return Path(settings.EUROSTAT_STORE_DIR).resolve().parent / "digests"


def latest_path() -> Path:
    return digest_dir() / "latest.json"


DIGEST_MAX_AGE_HOURS = 96.0


def digest_is_fresh(payload: dict[str, Any] | None, *, max_age_hours: float = DIGEST_MAX_AGE_HOURS) -> bool:
    if not isinstance(payload, dict):
        return False
    raw = payload.get("as_of")
    if not raw:
        return False
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    age = (datetime.now(timezone.utc) - dt).total_seconds()
    return -300 <= age <= max_age_hours * 3600


def load_latest_digest() -> dict[str, Any] | None:
    path = latest_path()
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None
        if not digest_is_fresh(payload):
            logger.info("nightly_digest_stale_ignored", as_of=str(payload.get("as_of") or "")[:32])
            return None
        return payload
    except Exception as exc:
        logger.warning("nightly_digest_read_failed", error=str(exc)[:160])
        return None


def _hash_manifest(path: Path) -> str:
    if not path.is_file():
        return ""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    except OSError:
        return ""


def build_nightly_digest() -> dict[str, Any]:
    """CPU-only snapshot from already-synced local stores (no live Yahoo storm)."""
    from app.services.market_data.equity_eod_store import read_latest_quote, store_status as eod_status
    from app.services.market_data.market_overview import BOARD, LIQUID_UNIVERSE, _coverage, _board_from_local_only
    from app.services.market_data.stooq_bulk_store import store_status as stooq_status

    groups = _board_from_local_only() or {}
    movers: list[dict[str, Any]] = []
    for rows in groups.values():
        for row in rows:
            chg = row.get("change_pct")
            if chg is None:
                continue
            movers.append({"symbol": row.get("symbol"), "change_pct": chg, "source": row.get("source")})
    movers.sort(key=lambda r: abs(float(r["change_pct"])), reverse=True)

    try:
        from app.services.market_data.equity_eod_store import bulk_root, read_latest_quote

        current = bulk_root() / "current"
        if current.is_dir():
            seen = {str(m.get("symbol") or "").upper() for m in movers}
            for path in current.glob("*.json"):
                sym = path.stem.upper()
                if not sym or sym in seen:
                    continue
                q = read_latest_quote(sym)
                chg = q.get("change_pct")
                if chg is None:
                    continue
                movers.append({"symbol": sym, "change_pct": chg, "source": q.get("source")})
                seen.add(sym)
            movers.sort(key=lambda r: abs(float(r["change_pct"])), reverse=True)
    except Exception as exc:
        logger.warning("nightly movers eod enrich failed", error=str(exc)[:200])

    spy = read_latest_quote("SPY")
    regime = "unknown"
    anchor_votes: dict[str, str] = {}
    try:
        from app.services.market_data.equity_eod_store import read_bars
        from app.services.pipeline.market_regime import REGIME_ANCHORS, compute_market_regime
        import pandas as pd

        dfs: dict[str, Any] = {}
        for sym in REGIME_ANCHORS:
            bars = read_bars(sym) or []
            if len(bars) >= 30:
                df = pd.DataFrame(bars)
                if "close" in df.columns:
                    dfs[sym] = df
        if dfs:
            mr = compute_market_regime(dfs)
            regime = str(mr.get("regime") or "insufficient")
            anchor_votes = dict(mr.get("anchor_votes") or {})
    except Exception as exc:
        logger.warning("nightly regime compute failed", error=str(exc)[:200])
        regime = "unknown"

    advances = sum(1 for m in movers if float(m["change_pct"]) > 0)
    declines = sum(1 for m in movers if float(m["change_pct"]) < 0)
    counted = advances + declines
    breadth = ((advances - declines) / counted) if counted else 0.0
    by_sym = {str(m.get("symbol") or "").upper(): m for m in movers}
    vxx = float((by_sym.get("VXX") or {}).get("change_pct") or 0.0)
    uup = float((by_sym.get("UUP") or {}).get("change_pct") or 0.0)
    tlt = float((by_sym.get("TLT") or {}).get("change_pct") or 0.0)
    regime_macro = {
        "trend_up": 0.35,
        "trend_down": -0.35,
        "volatility": -0.1,
        "range": 0.0,
        "crisis": -0.35,
        "insufficient": 0.0,
        "bull": 0.35,
        "bear": -0.35,
        "volatile": -0.1,
        "sideways": 0.0,
    }.get(regime, 0.0)
    macro_score = max(
        -1.0,
        min(
            1.0,
            0.55 * regime_macro
            + 0.25 * breadth
            + 0.12 * max(-1.0, min(1.0, -vxx / 4.0))
            + 0.08 * max(-1.0, min(1.0, tlt / 3.0 - uup / 4.0)),
        ),
    )
    screen_top = [
        {"symbol": m.get("symbol"), "change_pct": m.get("change_pct"), "source": m.get("source")}
        for m in movers[:40]
        if m.get("symbol")
    ]

    eod = eod_status()
    stooq = stooq_status()
    alt = {}
    try:
        from app.services.quant_desk.alt_macro import load_local_alt_macro
        from app.services.quant_desk.public_alt import refresh_public_alt_cache

        refresh_public_alt_cache()
        alt = load_local_alt_macro()
        tilt = float(alt.get("tilt") or 0.0)
        macro_score = max(-1.0, min(1.0, 0.75 * macro_score + 0.25 * tilt))
    except Exception:
        alt = {}
    payload = {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "coverage": _coverage(groups) if groups else 0,
        "regime": regime,
        "macro_score": macro_score,
        "breadth": round(breadth, 4),
        "anchor_votes": anchor_votes,
        "fred_proxy": {"vxx_change_pct": vxx, "uup_change_pct": uup, "tlt_change_pct": tlt},
        "alt_macro": {
            "tilt": (alt or {}).get("tilt"),
            "fred_tilt": (alt or {}).get("fred_tilt"),
            "ff_tilt": (alt or {}).get("ff_tilt"),
            "ff_as_of": (alt or {}).get("ff_as_of"),
            "esi_tilt": (alt or {}).get("esi_tilt"),
            "cftc_tilt": (alt or {}).get("cftc_tilt"),
            "brain_tilt": (alt or {}).get("brain_tilt"),
            "benzinga_tilt": (alt or {}).get("benzinga_tilt"),
            "quiver_tilt": (alt or {}).get("quiver_tilt"),
        },
        "spy_price": spy.get("price"),
        "spy_change_pct": spy.get("change_pct"),
        "top_movers": movers[:12],
        "screen_top": screen_top,
        "liquid_count": len(LIQUID_UNIVERSE),
        "board_groups": {k: len(v) for k, v in (groups or {}).items()},
        "eod": {
            "symbol_count": eod.get("symbol_count"),
            "synced_at": eod.get("synced_at"),
            "root": eod.get("root"),
        },
        "stooq": {
            "symbol_count": stooq.get("symbol_count"),
            "synced_at": stooq.get("synced_at"),
            "current_size_mb": stooq.get("current_size_mb"),
            "empty": stooq.get("empty"),
            "manifest_hash": _hash_manifest(Path(str(stooq.get("root") or "")) / "manifest.json"),
        },
        "note_ru": (
            "Выжимка для пайплайна. Полный ZIP не нужен, пока current/ и EOD живы. "
            "Вернуть сырьё = положить пакет в inbox и прогнать ingest."
        ),
    }
    return payload


def save_digest(payload: dict[str, Any]) -> Path:
    base = digest_dir()
    base.mkdir(parents=True, exist_ok=True)
    dated = base / f"{datetime.now(timezone.utc).date().isoformat()}.json"
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    dated.write_text(text, encoding="utf-8")
    latest_path().write_text(text, encoding="utf-8")
    # Keep two weeks of dated digests.
    old = sorted(base.glob("????-??-??.json"))
    for path in old[:-14]:
        try:
            path.unlink()
        except OSError:
            pass
    return dated


def prune_stooq_inbox(*, keep_days: int = 2) -> int:
    """Drop processed inbox ZIPs; extracted current/ stays as bar fallback."""
    from datetime import timedelta

    from app.services.market_data.stooq_bulk_store import ensure_layout

    inbox = ensure_layout() / "inbox"
    if not inbox.is_dir():
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)
    removed = 0
    for zpath in inbox.glob("*.zip"):
        try:
            mtime = datetime.fromtimestamp(zpath.stat().st_mtime, tz=timezone.utc)
            if mtime < cutoff:
                zpath.unlink()
                removed += 1
        except OSError:
            continue
    return removed
