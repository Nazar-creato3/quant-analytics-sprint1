"""Read-only Phase 4 pilot status aggregation for /ops/pilot UI."""
from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from app.schemas.ops import (
    AuditPathsOut,
    DocsLinkOut,
    ForecastRefreshStatusOut,
    GridBotTestCountsOut,
    GridBotTickStatusOut,
    KillSwitchDrillOut,
    LastPipelineRunOut,
    PilotLimitsOut,
    PilotStatusOut,
    PilotVenueOut,
    VenueConnectivityOut,
)

PHASE4_BUNDLE_COMMAND = (
    "python -m pytest "
    "grid_bot/tests/test_pilot_risk_limits.py "
    "grid_bot/tests/test_pilot_single_venue.py "
    "grid_bot/tests/integration/test_live_fill_reconcile_smoke.py "
    "grid_bot/tests/test_monitoring_hooks.py -q"
)

FULL_GATE_COMMAND = (
    "python -m pytest grid_bot/tests grid_bot/connectivity/tests grid_bot/topology/tests -q"
)

KILL_SWITCH_DRILL_COMMAND = (
    "python -m backend.grid_bot.scripts.staging_kill_switch_drill "
    "--session-id staging-kill-switch-drill-01 "
    "--data-dir backend/var/staging/kill_switch_drill"
)

KILL_SWITCH_DRILL_REL = Path("var") / "staging" / "kill_switch_drill"
KILL_SWITCH_AUDIT_NAME = "kill_switch_drill_audit.jsonl"

_DOC_NAMES = (
    "LIVE_PILOT_SIGNOFF.md",
    "LIVE_INCIDENT_RUNBOOK.md",
    "PHASE_4_EXIT_CHECKLIST.md",
)


def _backend_dir() -> Path:
    return Path(__file__).resolve().parents[3]


@lru_cache(maxsize=1)
def _dotenv_file() -> dict[str, str | None]:
    """Load backend/.env for keys not exported into os.environ by Pydantic Settings."""
    path = _backend_dir() / ".env"
    if path.is_file():
        return dotenv_values(path)
    return {}


def _env(key: str, default: str | None = None) -> str | None:
    """Resolve env var from process environment, then backend/.env fallback."""
    value = os.getenv(key)
    if value is not None:
        return value
    file_val = _dotenv_file().get(key)
    if file_val is not None:
        return file_val
    return default


def _var_pilot_root() -> Path:
    override = (_env("GRID_PILOT_DATA_DIR") or "").strip()
    if override:
        return Path(override)
    return _backend_dir() / "var" / "pilot"


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _load_pilot_config_json() -> dict[str, Any] | None:
    for candidate in (
        _var_pilot_root() / "config.json",
        _backend_dir() / "var" / "pilot" / "config.json",
    ):
        if candidate.is_file():
            try:
                payload = json.loads(candidate.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict):
                return payload
    return None


PAPER_PILOT_DEFAULTS = {
    "max_notional_per_order": 100.0,
    "max_daily_loss": 200.0,
    "max_orders_per_session": 3,
    "allowed_venue": "paper-sim",
}


def _pilot_limits_from_sources() -> PilotLimitsOut:
    from app.core.config import settings

    config = _load_pilot_config_json()
    pilot_raw = config.get("pilot", {}) if config else {}

    env_enabled = _env("GRID_PILOT_ENABLED")
    enabled = (
        _truthy(env_enabled)
        if env_enabled is not None
        else bool(pilot_raw.get("enabled", False))
    )

    def _float(key: str, env_key: str, default: float = 0.0) -> float:
        env_val = (_env(env_key) or "").strip()
        if env_val:
            try:
                return float(env_val)
            except ValueError:
                pass
        raw = pilot_raw.get(key, default)
        try:
            return float(raw)
        except (TypeError, ValueError):
            return default

    def _int(key: str, env_key: str, default: int = 0) -> int:
        env_val = (_env(env_key) or "").strip()
        if env_val:
            try:
                return int(env_val)
            except ValueError:
                pass
        raw = pilot_raw.get(key, default)
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default

    source = "env" if any(
        _env(k)
        for k in (
            "GRID_PILOT_ENABLED",
            "GRID_PILOT_MAX_NOTIONAL_PER_ORDER",
            "GRID_PILOT_MAX_DAILY_LOSS",
            "GRID_PILOT_MAX_ORDERS_PER_SESSION",
        )
    ) else ("config.json" if pilot_raw else "static")

    max_notional = _float(
        "max_notional_per_order",
        "GRID_PILOT_MAX_NOTIONAL_PER_ORDER",
        PAPER_PILOT_DEFAULTS["max_notional_per_order"],
    )
    max_daily_loss = _float(
        "max_daily_loss",
        "GRID_PILOT_MAX_DAILY_LOSS",
        PAPER_PILOT_DEFAULTS["max_daily_loss"],
    )
    max_orders = _int(
        "max_orders_per_session",
        "GRID_PILOT_MAX_ORDERS_PER_SESSION",
        PAPER_PILOT_DEFAULTS["max_orders_per_session"],
    )

    if settings.PAPER_TRADING_ENABLED and not settings.live_trading_unlocked and not enabled:
        enabled = True
        source = "paper-default"

    return PilotLimitsOut(
        enabled=enabled,
        max_notional_per_order=max_notional,
        max_daily_loss=max_daily_loss,
        max_orders_per_session=max_orders,
        source=source,
    )


def _pilot_venue_from_sources() -> PilotVenueOut:
    from app.core.config import settings

    config = _load_pilot_config_json()
    venue_raw = config.get("pilot_venue", {}) if config else {}

    env_enabled = _env("GRID_PILOT_VENUE_ENABLED")
    enabled = (
        _truthy(env_enabled)
        if env_enabled is not None
        else bool(venue_raw.get("enabled", False))
    )

    allowed_venue = (
        (_env("GRID_PILOT_ALLOWED_VENUE") or "").strip()
        or str(venue_raw.get("allowed_venue", "")).strip()
    )

    symbols_env = (_env("GRID_PILOT_ALLOWED_SYMBOLS") or "").strip()
    if symbols_env:
        allowed_symbols = [s.strip().upper() for s in symbols_env.split(",") if s.strip()]
        source = "env"
    else:
        raw_symbols = venue_raw.get("allowed_symbols", [])
        if isinstance(raw_symbols, str):
            allowed_symbols = [s.strip().upper() for s in raw_symbols.split(",") if s.strip()]
        elif isinstance(raw_symbols, (list, tuple)):
            allowed_symbols = [str(s).strip().upper() for s in raw_symbols if str(s).strip()]
        else:
            allowed_symbols = []
        source = "config.json" if venue_raw else "static"

    if _env("GRID_PILOT_ALLOWED_VENUE") or _env("GRID_PILOT_VENUE_ENABLED"):
        source = "env"

    if settings.PAPER_TRADING_ENABLED and not settings.live_trading_unlocked:
        if not enabled:
            enabled = True
            source = "paper-default"
        if not allowed_venue:
            allowed_venue = PAPER_PILOT_DEFAULTS["allowed_venue"]
        if not allowed_symbols:
            allowed_symbols = list(settings.default_watchlist_list)

    return PilotVenueOut(
        enabled=enabled,
        allowed_venue=allowed_venue,
        allowed_symbols=sorted(allowed_symbols),
        source=source,
    )


def _audit_paths() -> AuditPathsOut:
    root = _var_pilot_root()
    return AuditPathsOut(
        stop_drill=str(root / "stop_drill"),
        signoff=str(root / "signoff"),
        pilot_root=str(root),
    )


def _scan_drill_files() -> list[str]:
    root = _var_pilot_root()
    if not root.exists():
        return []

    files: list[str] = []
    for pattern in ("**/*.json", "**/*.jsonl"):
        for path in sorted(root.glob(pattern)):
            if path.is_file():
                files.append(str(path.relative_to(_backend_dir())))
    return files


def _docs_links() -> list[DocsLinkOut]:
    docs_dir = _backend_dir() / "grid_bot" / "docs"
    links: list[DocsLinkOut] = []
    for name in _DOC_NAMES:
        path = docs_dir / name
        links.append(DocsLinkOut(name=name, path=str(path)))
    return links


def _parse_latest_kill_switch_drill(audit_path: Path) -> dict[str, Any] | None:
    if not audit_path.is_file():
        return None

    latest: dict[str, Any] | None = None
    try:
        for line in audit_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if event.get("event_type") != "kill_switch_drill":
                continue
            payload = event.get("payload", {})
            report = payload.get("kill_switch_drill")
            if isinstance(report, dict):
                latest = report
    except OSError:
        return None
    return latest


def _kill_switch_drill_status() -> KillSwitchDrillOut:
    data_dir = _backend_dir() / KILL_SWITCH_DRILL_REL
    audit_path = data_dir / KILL_SWITCH_AUDIT_NAME
    docs_path = _backend_dir() / "grid_bot" / "docs" / "KILL_SWITCH_DRILL.md"
    report = _parse_latest_kill_switch_drill(audit_path) if data_dir.exists() else None

    return KillSwitchDrillOut(
        data_dir=str(data_dir),
        exists=data_dir.exists(),
        audit_file=str(audit_path) if audit_path.is_file() else None,
        passed=report.get("passed") if report else None,
        session_id=report.get("session_id") if report else None,
        drill_id=report.get("drill_id") if report else None,
        ts_utc=report.get("ts_utc") if report else None,
        drill_command=KILL_SWITCH_DRILL_COMMAND,
        docs_path=str(docs_path),
    )


def _env_nonempty(*keys: str) -> bool:
    return any((_env(key) or "").strip() for key in keys)


def _venue_connectivity_status() -> list[VenueConnectivityOut]:
    """Read-only venue credential presence for /ops/pilot UI (no network I/O)."""
    from app.core.config import settings

    binance_ok = _env_nonempty("BINANCE_API_KEY", "BINANCE_API_SECRET")
    finam_key = _env_nonempty("FINAM_API_KEY", "FINAM_TOKEN")
    finam_account = _env_nonempty("FINAM_ACCOUNT_ID")
    finam_ok = finam_key
    tinkoff_ok = _env_nonempty("TINKOFF_API_TOKEN", "TINKOFF_TOKEN")
    ibkr_ok = _env_nonempty("IBKR_API_KEY", "IBKR_API_SECRET", "IBKR_ACCOUNT_ID")
    paper_enabled = settings.PAPER_TRADING_ENABLED

    binance_url = _env("BINANCE_BASE_URL") or ""
    if paper_enabled and not binance_ok:
        binance_mode = "paper-sim"
        binance_detail = "Paper mode — simulated fills via in-memory adapter (no live keys required)"
    else:
        binance_mode = "testnet" if "testnet.binance" in binance_url else ("live" if binance_ok else "pending")
        binance_detail = (
            "Spot testnet"
            if "testnet" in binance_mode
            else ("production URL — use testnet in staging" if binance_ok else "missing BINANCE_API_KEY/SECRET")
        )

    return [
        VenueConnectivityOut(
            venue="binance",
            configured=binance_ok or paper_enabled,
            mode=binance_mode if (binance_ok or paper_enabled) else "disabled",
            detail=binance_detail,
        ),
        VenueConnectivityOut(
            venue="finam",
            configured=finam_ok or paper_enabled,
            mode="paper-sim" if (paper_enabled and not finam_ok) else ("demo" if finam_ok else "disabled"),
            detail=(
                "Paper mode — MOX equities simulated"
                if paper_enabled and not finam_ok
                else (
                    "MOEX demo key present"
                    + (" + account id" if finam_account else " (add FINAM_ACCOUNT_ID from portal)")
                    if finam_ok
                    else "missing FINAM_API_KEY — optional for paper"
                )
            ),
        ),
        VenueConnectivityOut(
            venue="tinkoff",
            configured=tinkoff_ok or paper_enabled,
            mode="paper-sim" if (paper_enabled and not tinkoff_ok) else ("market_data" if tinkoff_ok else "disabled"),
            detail=(
                "Учебный режим — сделки на виртуальном счёте"
                if paper_enabled and not tinkoff_ok
                else (
                    "Токен платформы — данные Мосбиржи; сделки по токенам пользователей"
                    if tinkoff_ok
                    else "нет TINKOFF_API_TOKEN — для учебного режима не обязателен"
                )
            ),
        ),
        VenueConnectivityOut(
            venue="ibkr",
            configured=ibkr_ok or paper_enabled,
            mode="paper-sim" if (paper_enabled and not ibkr_ok) else ("paper" if ibkr_ok else "disabled"),
            detail=(
                "Paper mode — IBKR gateway simulated"
                if paper_enabled and not ibkr_ok
                else ("paper gateway credentials present" if ibkr_ok else "pending — IB Gateway not ready")
            ),
        ),
    ]


def _paper_capabilities() -> dict[str, bool]:
    from app.core.config import settings

    return {
        "grid_bots": True,
        "maneuver_execution": settings.PAPER_TRADING_ENABLED,
        "pipeline_auto_execute": settings.PAPER_TRADING_ENABLED,
        "market_data": True,
        "news_ingestion": True,
        "backtest": True,
        "requires_live_keys_for": ["live_binance", "live_finam", "live_ibkr"],
    }


def _app_trading_mode() -> str:
    from app.core.config import settings

    if settings.PAPER_TRADING_ENABLED:
        return "paper"
    if settings.live_trading_unlocked:
        return "live"
    return "disabled"


async def _last_pipeline_run(db) -> LastPipelineRunOut:
    """Latest completed pipeline report from Postgres."""
    from sqlalchemy import desc, select

    from app.db.models import ManeuverReport

    try:
        result = await db.execute(
            select(ManeuverReport)
            .order_by(desc(ManeuverReport.created_at))
            .limit(1)
        )
        report = result.scalar_one_or_none()
        if report is None:
            return LastPipelineRunOut(status="none")

        created = report.created_at.isoformat() if report.created_at else None
        return LastPipelineRunOut(
            run_id=report.pipeline_run_id,
            report_id=report.id,
            status=report.status or "complete",
            triggered_by=report.created_by,
            completed_at=created,
            watchlist_count=len(report.watchlist or []),
        )
    except Exception:
        return LastPipelineRunOut(status="unknown")


async def _grid_bot_tick_status() -> GridBotTickStatusOut:
    """Active grid bots + last Celery tick metadata (best-effort)."""
    from app.utils.cache import cache_get

    active_bots = 0
    try:
        bots = await cache_get("grid:bots") or {}
        active_bots = sum(1 for b in bots.values() if b.get("is_active", True))
    except Exception:
        pass

    last_tick = await cache_get("ops:grid_bot_last_tick")
    last_tick_at = None
    last_status = None
    last_updated = 0
    last_fills = 0
    if isinstance(last_tick, dict):
        last_tick_at = last_tick.get("ts_utc")
        last_status = last_tick.get("status")
        last_updated = int(last_tick.get("updated") or 0)
        last_fills = int(last_tick.get("fills") or 0)

    return GridBotTickStatusOut(
        enabled=True,
        schedule="every minute (Celery beat)",
        active_bots=active_bots,
        last_tick_at=last_tick_at,
        last_tick_status=last_status,
        last_updated_bots=last_updated,
        last_fills=last_fills,
    )


async def _forecast_refresh_status(db) -> ForecastRefreshStatusOut:
    """Latest forecast snapshot timestamps + last Celery refresh metadata."""
    from sqlalchemy import desc, func, select

    from app.core.config import settings
    from app.db.models import ForecastSnapshot
    from app.utils.cache import cache_get

    watchlist_size = len(settings.default_watchlist_list)
    last_refresh_at = None
    last_status = None
    symbols_saved = 0

    last_run = await cache_get("ops:forecast_last_refresh")
    if isinstance(last_run, dict):
        last_refresh_at = last_run.get("ts_utc")
        last_status = last_run.get("status")
        symbols_saved = int(last_run.get("saved") or 0)

    try:
        result = await db.execute(select(func.max(ForecastSnapshot.snapshot_date)))
        max_date = result.scalar_one_or_none()
        if max_date is not None:
            db_ts = max_date.isoformat()
            if last_refresh_at is None or db_ts > last_refresh_at:
                last_refresh_at = db_ts

        count_result = await db.execute(select(func.count()).select_from(ForecastSnapshot))
        total_snapshots = count_result.scalar_one_or_none() or 0
        if symbols_saved == 0 and total_snapshots:
            symbols_saved = int(total_snapshots)

        latest_rows = await db.execute(
            select(ForecastSnapshot.symbol)
            .order_by(desc(ForecastSnapshot.snapshot_date))
            .limit(1)
        )
        if latest_rows.first() and last_status is None:
            last_status = "snapshots_present"
    except Exception:
        pass

    return ForecastRefreshStatusOut(
        enabled=True,
        schedule="daily 05:00 UTC (Celery beat)",
        last_refresh_at=last_refresh_at,
        last_status=last_status,
        symbols_saved=symbols_saved,
        watchlist_size=watchlist_size,
    )


async def build_pilot_status_async(db) -> PilotStatusOut:
    """Aggregate read-only Phase 4 pilot visibility payload with runtime status."""
    base = build_pilot_status()
    pipeline = await _last_pipeline_run(db)
    grid_tick = await _grid_bot_tick_status()
    forecast = await _forecast_refresh_status(db)
    return base.model_copy(
        update={
            "last_pipeline_run": pipeline,
            "grid_bot_tick": grid_tick,
            "forecast_refresh": forecast,
        }
    )


def build_pilot_status() -> PilotStatusOut:
    """Aggregate read-only Phase 4 pilot visibility payload."""
    from app.core.config import settings

    return PilotStatusOut(
        phase4_bundle_command=PHASE4_BUNDLE_COMMAND,
        pilot_limits=_pilot_limits_from_sources(),
        pilot_venue=_pilot_venue_from_sources(),
        venue_connectivity=_venue_connectivity_status(),
        app_trading_mode=_app_trading_mode(),
        paper_trading_enabled=settings.PAPER_TRADING_ENABLED,
        live_trading_enabled=settings.live_trading_unlocked,
        paper_capabilities=_paper_capabilities(),
        last_pipeline_run=LastPipelineRunOut(),
        grid_bot_tick=GridBotTickStatusOut(),
        forecast_refresh=ForecastRefreshStatusOut(),
        audit_paths=_audit_paths(),
        last_drill_files=_scan_drill_files(),
        grid_bot_test_counts=GridBotTestCountsOut(
            gate_label="Full release gate (994 tests)",
            command=FULL_GATE_COMMAND,
            expected_count=994,
        ),
        docs_links=_docs_links(),
        kill_switch_drill=_kill_switch_drill_status(),
    )
