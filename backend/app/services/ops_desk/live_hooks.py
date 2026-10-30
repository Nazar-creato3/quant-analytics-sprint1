"""Free sensors for desk D: last bar, broker, day PnL/DD, own-tape TCA, nightly DR."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from app.core.config import settings
from app.core.logging import get_logger
from app.services.ops_desk.disaster import backup_last_good, seal_deploy_floor
from app.services.ops_desk.factors import load_ff_rows
from app.services.ops_desk.kills import evaluate_kills
from app.services.ops_desk.pretrade import check as pretrade_check

logger = get_logger(__name__)

# Daily EOD: Friday close → Monday must not look "stale".
EOD_STALE_HOURS = 80.0


def _parse_dt(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    text = str(raw).strip()
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            dt = datetime.strptime(text[:10], "%Y-%m-%d")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def infer_last_bar(symbols: Sequence[str] | None = None) -> datetime | None:
    """Newest bar among names. Missing files → None (does not trip stale)."""
    try:
        from app.services.market_data.equity_eod_store import read_bars
    except Exception:
        return None
    names = [str(s).upper() for s in (symbols or ()) if str(s).strip()]
    if not names:
        return None
    newest: datetime | None = None
    for sym in names[:16]:
        try:
            bars = read_bars(sym)
        except Exception:
            continue
        if not bars:
            continue
        ts = _parse_dt(bars[-1].get("timestamp") or bars[-1].get("date"))
        if ts is None:
            continue
        if newest is None or ts > newest:
            newest = ts
    return newest


def infer_hist_returns(
    symbols: Sequence[str],
    *,
    max_n: int = 80,
) -> dict[str, list[float]]:
    try:
        from app.services.market_data.equity_eod_store import read_bars
    except Exception:
        return {}
    out: dict[str, list[float]] = {}
    names = [str(s).upper() for s in symbols if str(s).strip()]
    if "SPY" not in names:
        names = names + ["SPY"]
    for sym in names[:20]:
        try:
            bars = read_bars(sym)
        except Exception:
            continue
        closes: list[float] = []
        for bar in bars[-(max_n + 1) :]:
            try:
                closes.append(float(bar["close"]))
            except (KeyError, TypeError, ValueError):
                continue
        if len(closes) < 12:
            continue
        rets = [(closes[i] / closes[i - 1] - 1.0) for i in range(1, len(closes)) if closes[i - 1]]
        if len(rets) >= 10:
            out[sym] = rets
    return out


def infer_broker_connected() -> bool | None:
    """Unknown unless a live session is unlocked and keys exist."""
    if not bool(getattr(settings, "live_trading_unlocked", False)):
        return None
    if bool(getattr(settings, "PAPER_TRADING_ENABLED", False)):
        return True
    alpaca = bool(getattr(settings, "ALPACA_API_KEY", "") and getattr(settings, "ALPACA_SECRET_KEY", ""))
    if alpaca:
        return True
    return None


def _pnl_path() -> Path:
    from app.services.ops_desk.disaster import _dr_root

    return _dr_root() / "pnl_snapshot.json"


def write_pnl_snapshot(
    *,
    day_pnl_frac: float,
    dd_frac: float,
    equity: float = 0.0,
    dest: Path | None = None,
) -> dict[str, Any]:
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "day_pnl_frac": float(day_pnl_frac),
        "dd_frac": float(dd_frac),
        "equity": float(equity),
    }
    path = dest or _pnl_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        tmp.replace(path)
        payload["persisted"] = True
    except OSError:
        payload["persisted"] = False
    return payload


class PnlSnapshotUnavailable(ValueError):
    """Missing, stale, or corrupt PnL snapshot — callers must refuse new risk."""


def read_pnl_snapshot(dest: Path | None = None, *, max_age_hours: float = 18.0) -> tuple[float, float]:
    path = dest or _pnl_path()
    if not path.is_file():
        raise PnlSnapshotUnavailable("нет данных: pnl snapshot missing")
    try:
        age_h = (
            datetime.now(timezone.utc) - datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        ).total_seconds() / 3600.0
        if age_h > max_age_hours:
            raise PnlSnapshotUnavailable("нет данных: pnl snapshot stale")
        row = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(row, dict):
            raise PnlSnapshotUnavailable("нет данных: pnl snapshot corrupt")
        ts_raw = row.get("ts")
        if ts_raw:
            ts = _parse_dt(ts_raw)
            if ts is None:
                raise PnlSnapshotUnavailable("нет данных: pnl snapshot corrupt")
            age_ts = (datetime.now(timezone.utc) - ts).total_seconds() / 3600.0
            if age_ts > max_age_hours:
                raise PnlSnapshotUnavailable("нет данных: pnl snapshot stale")
        day_raw = row.get("day_pnl_frac")
        dd_raw = row.get("dd_frac")
        if day_raw is None or dd_raw is None:
            raise PnlSnapshotUnavailable("нет данных: pnl snapshot incomplete")
        return float(day_raw), float(dd_raw)
    except PnlSnapshotUnavailable:
        raise
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise PnlSnapshotUnavailable("нет данных: pnl snapshot corrupt") from exc


def fills_grouped(fills: Sequence[Mapping[str, Any]] | None = None) -> dict[str, list[dict[str, Any]]]:
    if fills is None:
        try:
            from app.services.execution.fill_tape import load_fills

            fills = load_fills()
        except Exception as exc:
            logger.warning("fill tape unavailable; TCA groups stay empty", error=str(exc)[:200])
            fills = []
    by: dict[str, list[dict[str, Any]]] = {}
    for row in fills:
        if not isinstance(row, Mapping):
            continue
        sym = str(row.get("symbol") or row.get("ticker") or "").upper()
        if not sym:
            continue
        by.setdefault(sym, []).append(dict(row))
    return by


def last_good_sources() -> list[Path]:
    paths: list[Path] = []
    try:
        from app.services.market_data.nightly_digest import latest_path

        paths.append(latest_path())
    except Exception as exc:
        logger.warning("nightly digest path unavailable", error=str(exc)[:200])
    try:
        from app.services.forecast.feature_store import DEFAULT_STORE_DIR, get_forecast_feature_store

        paths.append(Path(get_forecast_feature_store().store_dir))
    except Exception as exc:
        from app.services.forecast.feature_store import DEFAULT_STORE_DIR

        logger.warning("forecast feature store path unavailable", error=str(exc)[:200])
        paths.append(DEFAULT_STORE_DIR)
    return paths


def live_sensors(symbols: Sequence[str] | None = None, **overrides: Any) -> dict[str, Any]:
    names = [str(s).upper() for s in (symbols or ()) if str(s).strip()]
    hist = infer_hist_returns(names) if names else {}
    pnl_error: str | None = None
    day_pnl: float | None = None
    dd: float | None = None
    try:
        day_pnl, dd = read_pnl_snapshot()
    except PnlSnapshotUnavailable as exc:
        pnl_error = str(exc)
        logger.warning("pnl snapshot unavailable; sensors stay empty", error=pnl_error[:200])
    payload: dict[str, Any] = {
        "last_bar": infer_last_bar(names),
        "broker_connected": infer_broker_connected(),
        "day_pnl_frac": day_pnl,
        "dd_frac": dd,
        "pnl_error": pnl_error,
        "fills_by_symbol": fills_grouped(),
        "hist": hist,
        "spy": hist.get("SPY"),
        "ff_rows": load_ff_rows(),
        "stale_hours": EOD_STALE_HOURS,
    }
    payload.update(overrides)
    return payload


def halt_reason(sensors: Mapping[str, Any] | None = None) -> str | None:
    sn = dict(sensors or {})
    if sn.get("day_pnl_frac") is None or sn.get("dd_frac") is None:
        return "pnl_unavailable"
    halt, items = evaluate_kills(
        day_pnl_frac=float(sn["day_pnl_frac"]),
        dd_frac=float(sn["dd_frac"]),
        last_bar=sn.get("last_bar"),
        broker_connected=sn.get("broker_connected", True),
        stale_hours=float(sn["stale_hours"]) if sn.get("stale_hours") is not None else EOD_STALE_HOURS,
    )
    if not halt:
        return None
    return ",".join(k.name for k in items if k.tripped)


def order_capital_cap(settings_cap: float | None) -> float | None:
    if settings_cap is not None:
        try:
            cap = float(settings_cap)
        except (TypeError, ValueError):
            return None
        return cap if cap > 0 else None
    raw = float(getattr(settings, "DEFAULT_PORTFOLIO_SIZE", 0.0) or 0.0)
    return raw if raw > 0 else None


def reject_new_order(
    *,
    ticker: str,
    side: str,
    qty: float,
    price: float,
    settings_cap: float | None = None,
    account_total: float | None = None,
    adv_usd: float = 0.0,
    country: str = "US",
    day_trades_5d: int = 0,
    would_day_trade: bool = False,
    sensors: Mapping[str, Any] | None = None,
    user_id: str = "paper",
    headlines: str = "",
) -> str | None:
    """None if the ticket may go out; else a short reason."""
    cap = order_capital_cap(settings_cap)
    if cap is None:
        return "нет данных"
    loaded_live = sensors is None
    sn = live_sensors([ticker]) if loaded_live else dict(sensors)
    pnl_err = sn.get("pnl_error")
    if pnl_err:
        return str(pnl_err)
    if sn.get("day_pnl_frac") is None or sn.get("dd_frac") is None:
        return "нет данных: pnl snapshot missing"
    try:
        px = float(price)
    except (TypeError, ValueError):
        return "нет данных"
    if px <= 0:
        return "нет данных"
    reason = halt_reason(sn)
    if reason:
        return f"kill_switch:{reason}"
    notional = abs(float(qty) * px)
    order_side = "short" if str(side).lower() in {"short", "sell_short"} else "long"
    pre = pretrade_check(
        settings_cap=cap,
        account_total=account_total if account_total is not None else cap,
        proposed_book_usd=notional,
        symbols=[str(ticker).upper()],
        sides=[order_side],
        notionals=[notional],
        adv=[float(adv_usd)],
        countries=[country],
        day_trades_5d=day_trades_5d,
        would_day_trade=would_day_trade,
    )
    if not pre.allow:
        return "pretrade:" + ",".join(pre.reasons)
    try:
        from app.services.platform_desk.mandate import load_ips, ticker_blocked

        block = ticker_blocked(ticker, load_ips(user_id), headlines=headlines)
        if block:
            return f"mandate:{block}"
    except Exception as exc:
        logger.warning("mandate check failed; refuse order", ticker=ticker, error=str(exc)[:200])
        return "mandate:unavailable"
    return None


def run_nightly_dr(
    *,
    settings_cap: float | None = None,
    account_total: float | None = None,
    dest_root: Path | None = None,
    seal_path: Path | None = None,
    sources: list[Path] | None = None,
) -> dict[str, Any]:
    cap = settings_cap
    if cap is None:
        raw = getattr(settings, "DEFAULT_PORTFOLIO_SIZE", None)
        try:
            cap = float(raw) if raw not in (None, "") else None
        except (TypeError, ValueError):
            cap = None
    if cap is None or float(cap) <= 0:
        return {"ok": False, "reason": "нет данных", "seal": None, "backup": None}
    seal = seal_deploy_floor(cap, account_total, dest=seal_path)
    backup = backup_last_good(list(sources or last_good_sources()), dest_root=dest_root)
    return {"seal": seal, "backup": backup}
