"""Admin-only fleet book: all platform accounts, never the maneuver factory.

Reads internal maneuvers + grid cache + last per-user audits.
Does not call venue APIs and must not be imported from pipeline/generator.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.db.models import Maneuver, ManeuverReport, ManeuverStatus, PositionAudit, User
from app.services.portfolio.capital_overlap import grid_occupied_tickers
from app.services.portfolio.exposure import OPEN_EXPOSURE_STATUSES
from app.utils.cache import cache_get, cache_set

logger = get_logger(__name__)

FLEET_CACHE_KEY = "admin:fleet_audit:latest"
FLEET_CACHE_TTL = 26 * 60 * 60
CLOSED_LOOKBACK_DAYS = 90
OVERLAP_MIN_SHARED = 2
NOTE_RU = (
    "Сводка площадки для оператора. Не используется при подборе манёвров. "
    "Только внутренняя книга: маневры, грид, прошлые аудиты."
)


def fleet_digest_dir() -> Path:
    raw = (settings.EQUITY_EOD_DIR or "").strip()
    if raw:
        return Path(raw).resolve().parent / "admin_fleet"
    return Path(settings.EUROSTAT_STORE_DIR).resolve().parent / "admin_fleet"


def latest_path() -> Path:
    return fleet_digest_dir() / "latest.json"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _norm_status(value: Any) -> str:
    return str(getattr(value, "value", value) or "").lower()


def _ticker(value: Any) -> str:
    return str(value or "").strip().upper()


def concentrate_holdings(holdings: list[tuple[str, str, float]]) -> list[dict[str, Any]]:
    """ticker, user_id, notional → platform concentration."""
    by_ticker: dict[str, dict[str, Any]] = {}
    for ticker, user_id, notional in holdings:
        t = _ticker(ticker)
        if not t:
            continue
        row = by_ticker.setdefault(t, {"ticker": t, "user_count": 0, "users": set(), "notional_usd": 0.0})
        if user_id not in row["users"]:
            row["users"].add(user_id)
            row["user_count"] += 1
        row["notional_usd"] += float(notional or 0.0)
    out = []
    for row in by_ticker.values():
        out.append(
            {
                "ticker": row["ticker"],
                "user_count": row["user_count"],
                "notional_usd": round(float(row["notional_usd"]), 2),
            }
        )
    out.sort(key=lambda r: (r["user_count"], r["notional_usd"]), reverse=True)
    return out[:40]


def user_overlaps(
    by_user: dict[str, set[str]],
    *,
    emails: dict[str, str],
    min_shared: int = OVERLAP_MIN_SHARED,
) -> list[dict[str, Any]]:
    ids = [uid for uid, tickers in by_user.items() if tickers]
    pairs: list[dict[str, Any]] = []
    for i, left in enumerate(ids):
        for right in ids[i + 1 :]:
            shared = sorted(by_user[left] & by_user[right])
            if len(shared) < min_shared:
                continue
            pairs.append(
                {
                    "user_a": emails.get(left, left),
                    "user_b": emails.get(right, right),
                    "shared_count": len(shared),
                    "shared_tickers": shared[:12],
                }
            )
    pairs.sort(key=lambda r: r["shared_count"], reverse=True)
    return pairs[:30]


def calibrate_closed(closed: list[dict[str, Any]]) -> dict[str, Any]:
    """Post-hoc: did closed ideas make money? Never used at generation time."""
    if not closed:
        return {
            "trade_count": 0,
            "win_rate": None,
            "avg_pnl_usd": None,
            "avg_confidence": None,
            "by_ticker": [],
            "by_strategy": [],
        }
    wins = sum(1 for t in closed if float(t.get("realized_pnl") or 0) > 0)
    pnls = [float(t.get("realized_pnl") or 0) for t in closed]
    confs = [float(t.get("confidence") or 0) for t in closed if t.get("confidence") is not None]
    by_t: dict[str, list[float]] = defaultdict(list)
    by_s: dict[str, list[float]] = defaultdict(list)
    for t in closed:
        by_t[_ticker(t.get("ticker"))].append(float(t.get("realized_pnl") or 0))
        strat = str(t.get("strategy") or "unknown")
        by_s[strat].append(float(t.get("realized_pnl") or 0))

    def _agg(mapping: dict[str, list[float]], key: str) -> list[dict[str, Any]]:
        rows = []
        for name, vals in mapping.items():
            if not name:
                continue
            rows.append(
                {
                    key: name,
                    "n": len(vals),
                    "win_rate": round(sum(1 for v in vals if v > 0) / len(vals), 4),
                    "pnl_usd": round(sum(vals), 2),
                }
            )
        rows.sort(key=lambda r: r["pnl_usd"])
        return rows[:20]

    return {
        "trade_count": len(closed),
        "win_rate": round(wins / len(closed), 4),
        "avg_pnl_usd": round(sum(pnls) / len(pnls), 2),
        "avg_confidence": round(sum(confs) / len(confs), 4) if confs else None,
        "by_ticker": _agg(by_t, "ticker"),
        "by_strategy": _agg(by_s, "strategy"),
    }


async def build_fleet_snapshot(db: AsyncSession) -> dict[str, Any]:
    users = (
        await db.execute(select(User).where(User.is_active.is_(True)).order_by(User.created_at))
    ).scalars().all()
    emails = {u.id: u.email for u in users}
    roles = {u.id: str(getattr(u.role, "value", u.role)) for u in users}

    open_rows = (
        await db.execute(
            select(Maneuver, ManeuverReport.created_by)
            .join(ManeuverReport, Maneuver.report_id == ManeuverReport.id)
            .where(
                Maneuver.status.in_(OPEN_EXPOSURE_STATUSES),
                ManeuverReport.created_by.is_not(None),
            )
        )
    ).all()

    since = _utcnow() - timedelta(days=CLOSED_LOOKBACK_DAYS)
    closed_rows = (
        await db.execute(
            select(Maneuver, ManeuverReport.created_by)
            .join(ManeuverReport, Maneuver.report_id == ManeuverReport.id)
            .where(
                Maneuver.status == ManeuverStatus.CLOSED,
                Maneuver.closed_at.is_not(None),
                Maneuver.closed_at >= since,
                ManeuverReport.created_by.is_not(None),
            )
        )
    ).all()

    orphan_n = int(
        (
            await db.execute(
                select(func.count(Maneuver.id))
                .join(ManeuverReport, Maneuver.report_id == ManeuverReport.id)
                .where(ManeuverReport.created_by.is_(None))
            )
        ).scalar_one()
        or 0
    )

    latest_completed = (
        select(
            PositionAudit.user_id.label("user_id"),
            func.max(PositionAudit.completed_at).label("completed_at"),
        )
        .where(
            PositionAudit.status == "complete",
            PositionAudit.completed_at.is_not(None),
        )
        .group_by(PositionAudit.user_id)
        .subquery()
    )
    audits = (
        await db.execute(
            select(PositionAudit).join(
                latest_completed,
                (PositionAudit.user_id == latest_completed.c.user_id)
                & (PositionAudit.completed_at == latest_completed.c.completed_at),
            )
        )
    ).scalars().all()
    last_audit: dict[str, PositionAudit] = {}
    for row in audits:
        last_audit.setdefault(row.user_id, row)

    key_modes: dict[str, set[str]] = defaultdict(set)
    key_venues: dict[str, set[str]] = defaultdict(set)
    try:
        from app.domain.trading_keys import TradingKeyMetadataORM

        keys = (
            await db.execute(
                select(
                    TradingKeyMetadataORM.user_id,
                    TradingKeyMetadataORM.venue,
                    TradingKeyMetadataORM.account_mode,
                    TradingKeyMetadataORM.status,
                    TradingKeyMetadataORM.revoked_at,
                )
            )
        ).all()
        for uid, venue, mode, status, revoked in keys:
            if revoked or str(status or "").lower() == "revoked":
                continue
            key_venues[str(uid)].add(str(venue))
            key_modes[str(uid)].add(str(mode or "paper"))
    except Exception as exc:
        logger.debug("fleet_keys_skipped", error=str(exc)[:120])

    bots: dict[str, Any] = {}
    try:
        cached = await cache_get("grid:bots")
        if isinstance(cached, dict):
            bots = cached
    except Exception:
        bots = {}

    holdings: list[tuple[str, str, float]] = []
    user_tickers: dict[str, set[str]] = {u.id: set() for u in users}
    per_user_open: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for maneuver, owner_id in open_rows:
        if not owner_id:
            continue
        t = _ticker(maneuver.ticker)
        notional = float(maneuver.position_size_usd or 0.0)
        holdings.append((t, owner_id, notional))
        user_tickers[owner_id].add(t)
        per_user_open[owner_id].append(
            {
                "ticker": t,
                "direction": str(getattr(maneuver.direction, "value", maneuver.direction)),
                "notional_usd": round(notional, 2),
                "status": _norm_status(maneuver.status),
            }
        )

    closed_payload: list[dict[str, Any]] = []
    per_user_closed_pnl: dict[str, list[float]] = defaultdict(list)
    for maneuver, owner_id in closed_rows:
        if not owner_id:
            continue
        pnl = float(maneuver.realized_pnl or 0.0)
        per_user_closed_pnl[owner_id].append(pnl)
        closed_payload.append(
            {
                "ticker": _ticker(maneuver.ticker),
                "strategy": str(getattr(maneuver.strategy_type, "value", maneuver.strategy_type)),
                "realized_pnl": pnl,
                "confidence": float(maneuver.confidence) if maneuver.confidence is not None else None,
            }
        )

    accounts: list[dict[str, Any]] = []
    for user in users:
        grid_tickers = sorted(grid_occupied_tickers(bots, user.email))
        for t in grid_tickers:
            user_tickers[user.id].add(t)
            holdings.append((t, user.id, 0.0))
        opens = per_user_open.get(user.id, [])
        closed_pnls = per_user_closed_pnl.get(user.id, [])
        audit = last_audit.get(user.id)
        summary = audit.user_summary if audit and isinstance(audit.user_summary, dict) else {}
        modes = key_modes.get(user.id) or set()
        account_mode = "live" if "live" in modes else ("paper" if modes else "paper")
        accounts.append(
            {
                "user_id": user.id,
                "email": user.email,
                "role": roles.get(user.id),
                "account_mode": account_mode,
                "venues_connected": sorted(key_venues.get(user.id) or []),
                "open_maneuvers": len(opens),
                "open_notional_usd": round(sum(x["notional_usd"] for x in opens), 2),
                "open_tickers": sorted({x["ticker"] for x in opens}),
                "grid_tickers": grid_tickers,
                "occupied_tickers": sorted(user_tickers[user.id]),
                "closed_90d": len(closed_pnls),
                "closed_pnl_90d": round(sum(closed_pnls), 2) if closed_pnls else 0.0,
                "last_audit_win_rate": summary.get("win_rate"),
                "last_audit_at": audit.completed_at.isoformat() if audit and audit.completed_at else None,
                "two_factor": bool(getattr(user, "two_factor_enabled", False)),
            }
        )

    accounts.sort(key=lambda a: a["open_notional_usd"], reverse=True)
    snapshot = {
        "as_of": _utcnow().isoformat(),
        "note_ru": NOTE_RU,
        "feeds_maneuver_factory": False,
        "venue_api_called": False,
        "user_count": len(accounts),
        "open_maneuver_count": sum(a["open_maneuvers"] for a in accounts),
        "open_notional_usd": round(sum(a["open_notional_usd"] for a in accounts), 2),
        "live_key_users": sum(1 for a in accounts if a["account_mode"] == "live"),
        "orphan_maneuvers": orphan_n,
        "concentration": concentrate_holdings(holdings),
        "overlaps": user_overlaps(user_tickers, emails=emails),
        "calibration_90d": calibrate_closed(closed_payload),
        "accounts": accounts,
    }
    return snapshot


def save_fleet_snapshot(payload: dict[str, Any]) -> Path:
    import json

    base = fleet_digest_dir()
    base.mkdir(parents=True, exist_ok=True)
    dated = base / f"{_utcnow().date().isoformat()}.json"
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    dated.write_text(text, encoding="utf-8")
    latest_path().write_text(text, encoding="utf-8")
    old = sorted(base.glob("????-??-??.json"))
    for path in old[:-14]:
        try:
            path.unlink()
        except OSError:
            continue
    return dated


async def persist_fleet_snapshot(payload: dict[str, Any]) -> None:
    try:
        await cache_set(FLEET_CACHE_KEY, payload, ttl=FLEET_CACHE_TTL)
    except Exception as exc:
        logger.debug("fleet_cache_set_failed", error=str(exc)[:120])
    try:
        save_fleet_snapshot(payload)
    except Exception as exc:
        logger.warning("fleet_disk_save_failed", error=str(exc)[:160])


def snapshot_is_fresh(payload: dict[str, Any] | None, *, max_age_hours: float = 26.0) -> bool:
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
    age = (_utcnow() - dt).total_seconds()
    return -300 <= age <= max_age_hours * 3600


def load_disk_snapshot() -> dict[str, Any] | None:
    import json

    path = latest_path()
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


async def load_latest_fleet_snapshot() -> dict[str, Any] | None:
    cached = await cache_get(FLEET_CACHE_KEY)
    if snapshot_is_fresh(cached if isinstance(cached, dict) else None):
        return cached
    disk = load_disk_snapshot()
    if snapshot_is_fresh(disk):
        return disk
    return None


async def refresh_fleet_snapshot(db: AsyncSession) -> dict[str, Any]:
    payload = await build_fleet_snapshot(db)
    await persist_fleet_snapshot(payload)
    return payload
