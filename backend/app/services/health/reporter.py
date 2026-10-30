"""Synthetic health checks + Telegram (quiet) vs Twilio (critical wake-up) alerting."""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.services.alerts.critical_escalation import classify_critical_failures, escalate_critical
from app.services.alerts.telegram import send_telegram_message
from app.services.health.auto_remediation import apply_remediations

logger = get_logger(__name__)

__all__ = [
    "run_health_report",
    "check_market_data_freshness",
    "check_cross_user_position_isolation",
    "check_chat_no_raw_debug",
    "check_auth_login",
    "check_forecast_availability",
    "check_forecast_direction_accuracy",
    "check_forecast_sample_growth",
    "check_news_feed_freshness",
    "check_orderbook_ws_liveness",
    "check_aitunnel_token_balance",
]

_DEBUG_LEAK_RE = re.compile(r"confidence\s*\d+%.*horizon", re.IGNORECASE | re.DOTALL)
_FORECAST_SYMBOLS = ("AAPL", "MSFT", "SPY")
_SAMPLE_GROWTH_TARGET_N = 30


def _row(name: str, status: str, error: str | None = None, **extra: Any) -> dict[str, Any]:
    out: dict[str, Any] = {"name": name, "status": status, "error": error}
    out.update(extra)
    return out


def _base_url(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    base = (getattr(settings, "HEALTH_CHECK_BASE_URL", "") or os.environ.get("HEALTH_CHECK_BASE_URL") or "").strip()
    if base:
        return base.rstrip("/")
    # Workers run in their own containers: 127.0.0.1 is not the API there.
    return "http://backend:8000" if os.path.exists("/.dockerenv") else "http://127.0.0.1:8000"


def _auth_headers(token: str | None) -> dict[str, str]:
    if not token:
        return {}
    return {"Authorization": f"Bearer {token.strip()}"}


async def _fresh_login_token(settings: Settings) -> str | None:
    email = (os.environ.get("TEST_USER_A_EMAIL") or getattr(settings, "TEST_USER_A_EMAIL", "") or "").strip()
    password = (os.environ.get("TEST_USER_A_PASSWORD") or getattr(settings, "TEST_USER_A_PASSWORD", "") or "").strip()
    if not email or not password:
        return (os.environ.get("TEST_USER_A_TOKEN") or getattr(settings, "TEST_USER_A_TOKEN", "") or "").strip() or None
    url = f"{_base_url(settings)}/api/v1/auth/login"
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(url, json={"email": email, "password": password})
        if resp.status_code != 200:
            return None
        data = resp.json()
        return (data.get("access_token") or data.get("token") or "").strip() or None
    except Exception:
        return None


async def check_auth_login(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    email = (os.environ.get("TEST_USER_A_EMAIL") or getattr(settings, "TEST_USER_A_EMAIL", "") or "").strip()
    password = (os.environ.get("TEST_USER_A_PASSWORD") or getattr(settings, "TEST_USER_A_PASSWORD", "") or "").strip()
    if not email or not password:
        return _row("auth_login", "passed", None, skipped="no_test_credentials")
    url = f"{_base_url(settings)}/api/v1/auth/login"
    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.post(url, json={"email": email, "password": password})
        if resp.status_code == 200 and (resp.json().get("access_token") or resp.json().get("token")):
            return _row("auth_login", "passed")
        return _row("auth_login", "failed", f"HTTP {resp.status_code}: {resp.text[:200]}")
    except Exception as exc:
        return _row("auth_login", "failed", str(exc)[:400])


async def check_market_data_freshness(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    url = f"{_base_url(settings)}/api/v1/terminal/snapshot"
    stale_after = 3600
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.get(url)
        if resp.status_code >= 500:
            return _row(
                "market_data_freshness",
                "failed",
                f"snapshot HTTP {resp.status_code}",
                indices_down=True,
                ok_count=0,
            )
        data = resp.json()
        meta = data.get("metadata") or data.get("meta") or {}
        freshness = meta.get("freshness") or meta.get("indices_freshness") or {}
        last = freshness.get("last_refreshed_at") or freshness.get("fetched_at") or meta.get("fetched_at")
        is_stale = freshness.get("is_stale")
        age_s = freshness.get("age_s")
        if last and age_s is None:
            try:
                ts = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
                age_s = (datetime.now(timezone.utc) - ts.astimezone(timezone.utc)).total_seconds()
            except Exception:
                age_s = None
        indices = data.get("indices") or data.get("performance") or []
        ok_count = sum(1 for i in indices if isinstance(i, dict) and i.get("status") == "ok")
        if is_stale is True or (age_s is not None and age_s > stale_after):
            return _row(
                "market_data_freshness",
                "failed",
                f"indices stale {int(age_s or 0)}s",
                age_s=age_s,
                cache_key="quotes:SPY",
                ok_count=ok_count,
                indices_down=True,
            )
        if ok_count == 0 and isinstance(indices, list) and len(indices) == 0:
            return _row(
                "market_data_freshness",
                "failed",
                "no index quotes in snapshot",
                ok_count=0,
                indices_down=True,
            )
        return _row(
            "market_data_freshness",
            "passed",
            None,
            age_s=age_s,
            ok_count=max(ok_count, len(indices) if isinstance(indices, list) else 0),
            last_updated=last,
        )
    except Exception as exc:
        return _row("market_data_freshness", "failed", str(exc)[:400], ok_count=0, indices_down=True)


async def check_forecast_availability(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    token = await _fresh_login_token(settings)
    if not token:
        # No probe account configured (TEST_USER_A_*): nothing to test, not an outage.
        return _row("forecast_availability", "ok", "пропущено: не задан тестовый аккаунт")
    base = _base_url(settings)
    parts: list[str] = []
    failed = False
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            for sym in _FORECAST_SYMBOLS:
                resp = await client.get(
                    f"{base}/api/v1/forecast/{sym}",
                    headers=_auth_headers(token),
                    params={"include_narrative": "false"},
                )
                if resp.status_code >= 400:
                    parts.append(f"{sym}=HTTP{resp.status_code}")
                    failed = True
                    continue
                body_text = resp.text
                if "TypeError" in body_text or "Traceback" in body_text:
                    parts.append(f"{sym}=TypeError")
                    failed = True
                    continue
                data = resp.json()
                if not data.get("symbol"):
                    parts.append(f"{sym}=empty")
                    failed = True
                else:
                    parts.append(f"{sym}=ok")
        detail = "; ".join(parts)
        if failed:
            return _row("forecast_availability", "failed", detail, service_down=True)
        return _row("forecast_availability", "passed", None, detail=detail)
    except Exception as exc:
        return _row("forecast_availability", "failed", str(exc)[:400], service_down=True)


async def check_chat_no_raw_debug(settings: Settings | None = None) -> dict[str, Any]:
    from app.services.health.expensive_check_throttle import run_throttled_expensive_check

    async def _live(settings: Settings) -> dict[str, Any]:
        return await _run_chat_no_raw_debug_live(settings)

    return await run_throttled_expensive_check(
        "chat_no_raw_debug",
        _live,
        settings=settings,
        enabled_attr="HEALTH_LIVE_CHAT_CHECK_ENABLED",
        interval_attr="HEALTH_LIVE_CHAT_INTERVAL_SECONDS",
    )


async def _run_chat_no_raw_debug_live(settings: Settings) -> dict[str, Any]:
    token = await _fresh_login_token(settings)
    if not token:
        return _row("chat_no_raw_debug", "failed", "no chat token", service_down=True)

    url = f"{_base_url(settings)}/api/chat"
    payload = {"message": "почему такой score по SBER?"}
    try:
        async with httpx.AsyncClient(timeout=240.0) as client:
            resp = await client.post(url, headers=_auth_headers(token), json=payload)
        if resp.status_code >= 500:
            return _row(
                "chat_no_raw_debug",
                "failed",
                f"HTTP {resp.status_code}",
                service_down=True,
            )
        if resp.status_code >= 400:
            return _row("chat_no_raw_debug", "failed", f"HTTP {resp.status_code}: {resp.text[:200]}")
        body = resp.json()
        text = body.get("response") or (body.get("advisor_message") or {}).get("body") or json.dumps(body)
        if "traceback" in text.lower() or "debug:" in text.lower():
            return _row("chat_no_raw_debug", "failed", "raw debug in chat payload")
        if _DEBUG_LEAK_RE.search(text):
            return _row("chat_no_raw_debug", "failed", "raw debug verdict leaked in chat response")
        return _row("chat_no_raw_debug", "passed")
    except httpx.ReadTimeout:
        return _row("chat_no_raw_debug", "failed", "ReadTimeout (no message)", service_down=True)
    except asyncio.TimeoutError:
        return _row("chat_no_raw_debug", "failed", "ReadTimeout (no message)", service_down=True)
    except Exception as exc:
        err = str(exc)[:400]
        down = any(k in err.lower() for k in ("timeout", "connect", "refused", "503", "502"))
        return _row("chat_no_raw_debug", "failed", err, service_down=down)


async def check_cross_user_position_isolation(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    token_a = await _fresh_login_token(settings)
    token_b = (os.environ.get("TEST_USER_B_TOKEN") or getattr(settings, "TEST_USER_B_TOKEN", "") or "").strip()
    if not token_a:
        return _row("cross_user_position_isolation", "passed", None, skipped="no_token_a")
    if not token_b:
        email_b = (os.environ.get("TEST_USER_B_EMAIL") or getattr(settings, "TEST_USER_B_EMAIL", "") or "").strip()
        password_b = (os.environ.get("TEST_USER_B_PASSWORD") or getattr(settings, "TEST_USER_B_PASSWORD", "") or "").strip()
        if email_b and password_b:
            try:
                async with httpx.AsyncClient(timeout=25.0) as client:
                    r = await client.post(
                        f"{_base_url(settings)}/api/v1/auth/login",
                        json={"email": email_b, "password": password_b},
                    )
                if r.status_code == 200:
                    token_b = (r.json().get("access_token") or "").strip()
            except Exception:
                pass
    if not token_b:
        return _row("cross_user_position_isolation", "passed", None, skipped="no_token_b")

    base = _base_url(settings)
    leak_detail: str | None = None
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            ra = await client.get(f"{base}/api/v1/portfolio/metrics", headers=_auth_headers(token_a))
            rb = await client.get(f"{base}/api/v1/portfolio/metrics", headers=_auth_headers(token_b))
        if ra.status_code == 200 and rb.status_code == 200:
            da, db = ra.json(), rb.json()
            a_id = da.get("user_id") or da.get("owner_id") or da.get("account_id")
            b_id = db.get("user_id") or db.get("owner_id") or db.get("account_id")
            if a_id and b_id and str(a_id) == str(b_id):
                leak_detail = "same portfolio owner id for A and B"
            a_positions = json.dumps(da.get("positions") or da.get("holdings") or [])[:500]
            b_positions = json.dumps(db.get("positions") or db.get("holdings") or [])[:500]
            if a_positions and a_positions == b_positions and a_positions != "[]":
                leak_detail = leak_detail or "identical position payloads for A and B"
    except Exception as exc:
        return _row("cross_user_position_isolation", "failed", str(exc)[:400])

    if leak_detail:
        return _row("cross_user_position_isolation", "failed", leak_detail)
    return _row("cross_user_position_isolation", "passed")


async def check_forecast_direction_accuracy(settings: Settings | None = None) -> dict[str, Any]:
    """Direction accuracy from raw scored resolutions (all sources, no horizon/window filter)."""
    settings = settings or get_settings()
    _ = settings
    try:
        from app.db.session import AsyncSessionLocal
        from app.services.forecast.live_accuracy import HEALTH_ACCURACY_FLOOR
        from app.services.forecast.snapshot_backfill import unfiltered_resolution_counts

        async with AsyncSessionLocal() as db:
            counts = await unfiltered_resolution_counts(db, _FORECAST_SYMBOLS)

        sample_n = {sym: counts[sym].scored_n for sym in _FORECAST_SYMBOLS}
        raw_n = {sym: counts[sym].raw_n for sym in _FORECAST_SYMBOLS}
        parts: list[str] = []
        failed = False
        for sym in _FORECAST_SYMBOLS:
            row = counts[sym]
            n = row.scored_n
            acc = row.accuracy
            if n == 0:
                parts.append(f"{sym}=insufficient(n=0)")
                failed = True
            elif acc is None:
                parts.append(f"{sym}=insufficient(n={n})")
            else:
                parts.append(f"{sym}={acc:.0%}(n={n})")
                if n >= 30 and acc < HEALTH_ACCURACY_FLOOR:
                    failed = True
        detail = "; ".join(parts)
        if failed:
            return _row(
                "forecast_direction_accuracy",
                "failed",
                detail,
                sample_n=sample_n,
                raw_n=raw_n,
            )
        return _row(
            "forecast_direction_accuracy",
            "passed",
            None,
            sample_n=sample_n,
            raw_n=raw_n,
            detail=detail,
        )
    except ImportError:
        return _row("forecast_direction_accuracy", "passed", None, skipped="module_unavailable")
    except Exception as exc:
        return _row("forecast_direction_accuracy", "failed", str(exc)[:400])


async def check_forecast_sample_growth(settings: Settings | None = None) -> dict[str, Any]:
    """Fail when core symbols have zero scored n or stall during NYSE session."""
    settings = settings or get_settings()
    _ = settings
    try:
        from app.db.session import AsyncSessionLocal
        from app.services.forecast.snapshot_backfill import (
            mature_unresolved_counts,
            scored_resolutions_since,
            unfiltered_resolution_counts,
        )
        from app.services.terminal_platform.market.hours import nyse_regular_session_elapsed

        now = datetime.now(timezone.utc)
        session_start = now - timedelta(hours=8)
        async with AsyncSessionLocal() as db:
            totals = await unfiltered_resolution_counts(db, _FORECAST_SYMBOLS)
            growth = await scored_resolutions_since(db, _FORECAST_SYMBOLS, since=session_start)
            backlog = await mature_unresolved_counts(db, _FORECAST_SYMBOLS, now=now)

        in_session = nyse_regular_session_elapsed(session_start, now)
        problems: list[str] = []
        for sym in _FORECAST_SYMBOLS:
            n = totals[sym].scored_n
            if n == 0:
                problems.append(f"{sym}=n0")
                continue
            if (
                in_session
                and n < _SAMPLE_GROWTH_TARGET_N
                and growth.get(sym, 0) == 0
                and backlog.get(sym, 0) > 0
            ):
                problems.append(f"{sym}=stalled(n={n},backlog={backlog.get(sym, 0)})")
        if problems:
            return _row("forecast_sample_growth", "failed", "; ".join(problems))
        return _row("forecast_sample_growth", "passed")
    except ImportError:
        return _row("forecast_sample_growth", "passed", None, skipped="module_unavailable")
    except Exception as exc:
        return _row("forecast_sample_growth", "failed", str(exc)[:400])


async def check_news_feed_freshness(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    url = f"{_base_url(settings)}/api/v1/terminal/news"
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            resp = await client.get(url, params={"limit": 8})
        resp.raise_for_status()
        body = resp.json()
        meta = (body.get("metadata") or {}).get("freshness") or {}
        last_refreshed = meta.get("last_refreshed_at")
        if not last_refreshed:
            return _row("news_feed_freshness", "failed", "missing last_refreshed_at")
        items = body.get("data") or []
        if not items:
            return _row("news_feed_freshness", "failed", "no headlines")
        age_s = meta.get("age_sec")
        if age_s is None:
            ts = datetime.fromisoformat(str(last_refreshed).replace("Z", "+00:00"))
            age_s = (datetime.now(timezone.utc) - ts.astimezone(timezone.utc)).total_seconds()
        stale_after = float(meta.get("stale_after_sec") or 3600)
        if meta.get("is_stale") or float(age_s) >= stale_after:
            return _row("news_feed_freshness", "failed", f"stale {int(age_s)}s", age_s=age_s)
        return _row("news_feed_freshness", "passed", None, age_s=age_s)
    except Exception as exc:
        return _row("news_feed_freshness", "failed", str(exc)[:400])


async def check_orderbook_ws_liveness(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    url = f"{_base_url(settings)}/api/v1/terminal/orderbook?symbol=SPY&depth=5"
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.get(url)
        if resp.status_code >= 500:
            return _row("orderbook_ws_liveness", "failed", f"HTTP {resp.status_code}")
        return _row("orderbook_ws_liveness", "passed", msg_type="connected")
    except Exception as exc:
        return _row("orderbook_ws_liveness", "failed", str(exc)[:200])


async def check_aitunnel_token_balance(settings: Settings | None = None) -> dict[str, Any]:
    """Proactive AITUNNEL credit check - alert before Chat/Forecast LLM paths hit zero."""
    settings = settings or get_settings()
    try:
        from app.services.llm.aitunnel_balance import assess_balance

        verdict = await assess_balance(settings)
        if verdict.get("skipped"):
            return _row(
                "aitunnel_token_balance",
                "passed",
                None,
                skipped=verdict.get("reason"),
                detail=verdict.get("api_error"),
            )
        if verdict.get("status") == "failed":
            return _row(
                "aitunnel_token_balance",
                "failed",
                verdict.get("error"),
                detail=verdict.get("detail"),
                balance_rub=verdict.get("balance_rub"),
                effective_rub=verdict.get("effective_rub"),
                burn_rub_24h=verdict.get("burn_rub_24h"),
                threshold_rub=verdict.get("threshold_rub"),
                hours_remaining=verdict.get("hours_remaining"),
            )
        burn_24h = float(verdict.get("burn_rub_24h") or 0.0)
        spike_threshold = float(getattr(settings, "AITUNNEL_BURN_SPIKE_ALERT_RUB_24H", 150.0) or 150.0)
        if spike_threshold > 0 and burn_24h >= spike_threshold:
            return _row(
                "aitunnel_token_balance",
                "failed",
                f"AITUNNEL burn spike: {burn_24h:.2f}₽/24h ≥ {spike_threshold:.2f}₽ (проверьте фоновые health/cron вызовы)",
                detail=verdict.get("detail"),
                balance_rub=verdict.get("balance_rub"),
                effective_rub=verdict.get("effective_rub"),
                burn_rub_24h=burn_24h,
                threshold_rub=verdict.get("threshold_rub"),
                hours_remaining=verdict.get("hours_remaining"),
                burn_spike=True,
            )
        return _row(
            "aitunnel_token_balance",
            "passed",
            None,
            detail=verdict.get("detail"),
            balance_rub=verdict.get("balance_rub"),
            effective_rub=verdict.get("effective_rub"),
            burn_rub_24h=verdict.get("burn_rub_24h"),
            threshold_rub=verdict.get("threshold_rub"),
            hours_remaining=verdict.get("hours_remaining"),
        )
    except ImportError:
        return _row("aitunnel_token_balance", "passed", None, skipped="module_unavailable")


async def check_terminal_widget_latency(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    base = _base_url(settings)
    paths = [
        ("/api/v1/terminal/news?limit=8", "terminal_news"),
        ("/api/v1/portfolio/metrics", "portfolio_metrics"),
    ]
    slow: list[str] = []
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            for path, name in paths:
                t0 = time.perf_counter()
                r = await client.get(base + path)
                ms = (time.perf_counter() - t0) * 1000
                if r.status_code >= 500:
                    return _row("terminal_widget_latency", "failed", f"{name} HTTP {r.status_code}")
                if ms > 5000:
                    slow.append(f"{name}={ms:.0f}ms")
        if slow:
            return _row("terminal_widget_latency", "failed", "; ".join(slow))
        return _row("terminal_widget_latency", "passed")
    except Exception as exc:
        return _row("terminal_widget_latency", "failed", str(exc)[:400])


def _format_report(results: list[dict[str, Any]], remediations: list[str]) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [f"Apex Intel health report ({ts})"]
    failed_names: list[str] = []
    for row in results:
        mark = "OK" if row.get("status") == "passed" else "FAIL"
        err = f" - {row['error']}" if row.get("error") else ""
        detail = f" ({row['detail']})" if row.get("detail") and not row.get("error") else ""
        if row.get("detail") and row.get("error"):
            detail = f" [{row['detail']}]"
        lines.append(f"* {row.get('name')}: {mark}{err}{detail}")
        if row.get("status") == "failed":
            failed_names.append(str(row.get("name")))
    if remediations:
        lines.append("Auto-fix: " + ", ".join(remediations))
    if failed_names:
        lines.append("Action needed: " + ", ".join(failed_names))
    return "\n".join(lines)


async def run_health_report(
    *,
    send_telegram: bool = True,
    settings: Settings | None = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    results = [
        await check_market_data_freshness(settings),
        await check_auth_login(settings),
        await check_cross_user_position_isolation(settings),
        await check_chat_no_raw_debug(settings),
        await check_forecast_availability(settings),
        await check_forecast_direction_accuracy(settings),
        await check_forecast_sample_growth(settings),
        await check_news_feed_freshness(settings),
        await check_orderbook_ws_liveness(settings),
        await check_terminal_widget_latency(settings),
        await check_aitunnel_token_balance(settings),
    ]
    remediations = await apply_remediations(results)
    failed = [r for r in results if r.get("status") == "failed"]
    message = _format_report(results, remediations)

    telegram_delivered = False
    # The hourly report is for logs/admin pages; Telegram only if explicitly enabled.
    if send_telegram and getattr(settings, "HEALTH_TELEGRAM_ENABLED", False) and settings.telegram_configured and failed:
        telegram_delivered = await send_telegram_message(
            settings.TELEGRAM_CHAT_ID,
            message,
            settings=settings,
        )

    critical = classify_critical_failures(results)
    critical_result: dict[str, Any] = {"attempted": False}
    if critical and getattr(settings, "HEALTH_TELEGRAM_ENABLED", False):
        critical_result = await escalate_critical(critical, settings=settings)

    logger.info(
        "health_report_complete",
        delivered=telegram_delivered,
        failed=len(failed),
        critical=len(critical),
        critical_delivered=critical_result.get("any_delivered"),
    )
    return {
        "results": results,
        "remediations": remediations,
        "telegram_delivered": telegram_delivered,
        "critical_failures": critical,
        "critical_escalation": critical_result,
        "message_preview": message,
    }
