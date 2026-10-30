"""Data freshness SLAs, model drift, confidence vs hit-rate calibration."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from app.core.config import settings
from app.services.ops_desk.live_hooks import infer_last_bar


def _dir() -> Path:
    raw = getattr(settings, "PLATFORM_MONITOR_DIR", "") or ""
    return Path(raw) if str(raw).strip() else Path("/app/data/platform")


def _age_hours(ts: datetime | None, now: datetime | None = None) -> float | None:
    if ts is None:
        return None
    clock = now or datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return (clock - ts).total_seconds() / 3600.0


def _parse(raw: Any) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def freshness_slas() -> list[dict[str, Any]]:
    """Missing source = miss, not a crash. Daily EOD SLA 80h (weekend-safe)."""
    rows: list[dict[str, Any]] = []
    try:
        from app.services.market_data.nightly_digest import load_latest_digest, latest_path

        digest = load_latest_digest()
        path = latest_path()
        ts = _parse((digest or {}).get("as_of"))
        if ts is None and path.is_file():
            ts = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        age = _age_hours(ts)
        rows.append(
            {
                "name": "nightly_digest",
                "sla_hours": 96.0,
                "age_hours": None if age is None else round(age, 2),
                "ok": age is not None and age <= 96.0,
                "present": bool(digest) or path.is_file(),
            }
        )
    except Exception:
        rows.append({"name": "nightly_digest", "sla_hours": 96.0, "age_hours": None, "ok": False, "present": False})

    bar = infer_last_bar(["SPY"])
    age = _age_hours(bar)
    rows.append(
        {
            "name": "eod_spy",
            "sla_hours": 80.0,
            "age_hours": None if age is None else round(age, 2),
            "ok": age is not None and age <= 80.0,
            "present": bar is not None,
        }
    )

    try:
        from app.services.forecast.feature_store import DEFAULT_STORE_DIR, get_forecast_feature_store

        store = Path(get_forecast_feature_store().store_dir)
    except Exception:
        from app.services.forecast.feature_store import DEFAULT_STORE_DIR

        store = DEFAULT_STORE_DIR
    files = list(store.glob("*.json")) if store.is_dir() else []
    mtimes = [datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc) for p in files]
    newest = max(mtimes) if mtimes else None
    age = _age_hours(newest)
    rows.append(
        {
            "name": "feature_store",
            "sla_hours": 80.0,
            "age_hours": None if age is None else round(age, 2),
            "ok": age is not None and age <= 80.0,
            "present": bool(files),
        }
    )
    return rows


def calibration_vs_hit(
    confidences: Sequence[float],
    hits: Sequence[bool],
    *,
    bins: int = 5,
) -> dict[str, Any]:
    """Reliability: mean confidence vs hit rate. None if < 20 pairs."""
    n = min(len(confidences), len(hits))
    if n < 20:
        return {"n": n, "ece": None, "bins": [], "note": "need_20_pairs"}
    pairs = [(max(0.0, min(1.0, float(confidences[i]))), bool(hits[i])) for i in range(n)]
    edges = [i / bins for i in range(bins + 1)]
    rows = []
    ece = 0.0
    for b in range(bins):
        lo, hi = edges[b], edges[b + 1]
        chunk = [p for p in pairs if (p[0] >= lo and (p[0] < hi or (b == bins - 1 and p[0] <= hi)))]
        if not chunk:
            rows.append({"lo": lo, "hi": hi, "n": 0, "mean_p": None, "hit_rate": None})
            continue
        mean_p = sum(p for p, _ in chunk) / len(chunk)
        hr = sum(1 for _, h in chunk if h) / len(chunk)
        ece += abs(mean_p - hr) * (len(chunk) / n)
        rows.append(
            {
                "lo": round(lo, 4),
                "hi": round(hi, 4),
                "n": len(chunk),
                "mean_p": round(mean_p, 4),
                "hit_rate": round(hr, 4),
            }
        )
    return {"n": n, "ece": round(ece, 4), "bins": rows, "ok": ece <= 0.15}


def _pairs_from_books() -> tuple[list[float], list[bool]]:
    from app.services.forecast.daily_book import _book_dir

    folder = _book_dir()
    conf: list[float] = []
    hits: list[bool] = []
    if not folder.is_dir():
        return conf, hits
    for path in sorted(folder.glob("????-??-??.realized.json"))[-60:]:
        try:
            book = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        excess = book.get("excess")
        if excess is None:
            continue
        for h in book.get("holdings") or []:
            p = h.get("p_beat_21", h.get("p_beat_20"))
            if p is None:
                continue
            try:
                conf.append(float(p))
                hits.append(float(excess) > 0)
            except (TypeError, ValueError):
                continue
    return conf, hits


def snapshot() -> dict[str, Any]:
    sla = freshness_slas()
    drift: dict[str, Any] = {"source": "file", "alert": False}
    try:
        from app.services.forecast.tear_sheet import load_latest_tear_sheet

        tear = load_latest_tear_sheet() or {}
        ece = tear.get("ece") or {}
        drift = {
            "source": "tear_sheet",
            "ece": ece,
            "deflated_sharpe": tear.get("deflated_sharpe"),
            "alert": bool(ece) and float(ece.get("n") or 0) >= 40 and not ece.get("reliable", True),
        }
    except Exception:
        pass
    try:
        from app.services.prediction_hierarchy.calibration_tracker import get_live_calibration_error

        live_ce = get_live_calibration_error()
        if live_ce is not None:
            drift["live_calibration_error"] = live_ce
            if live_ce > 0.15:
                drift["alert"] = True
    except Exception:
        pass
    conf, hits = _pairs_from_books()
    cal = calibration_vs_hit(conf, hits)
    if cal.get("ece") is not None and float(cal["ece"]) > 0.15:
        drift["alert"] = True
    return {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "freshness": sla,
        "freshness_ok": all(bool(r.get("ok")) for r in sla),
        "drift": drift,
        "calibration": cal,
    }


def _safe_uid(user_id: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._@+-" else "_" for ch in str(user_id).strip()) or "paper"


def persist_snapshot(
    row: dict[str, Any] | None = None,
    *,
    user_id: str = "paper",
) -> dict[str, Any]:
    payload = dict(row or snapshot())
    payload["user_id"] = str(user_id)
    path = _dir() / "monitors" / _safe_uid(user_id) / "monitor.json"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        payload["persisted"] = False
    return payload


def load_snapshot(*, user_id: str = "paper") -> dict[str, Any] | None:
    path = _dir() / "monitors" / _safe_uid(user_id) / "monitor.json"
    if not path.is_file():
        return None
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(row, dict):
            return None
        owner = str(row.get("user_id") or user_id)
        if owner != str(user_id):
            return None
        return row
    except (OSError, json.JSONDecodeError):
        return None
