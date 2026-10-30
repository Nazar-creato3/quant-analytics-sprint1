"""Wake-up escalation for genuinely critical outages (Twilio voice/SMS)."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from app.core.config import Settings, get_settings

try:
    from app.core.logging import get_logger

    logger = get_logger(__name__)
except Exception:  # pragma: no cover
    import logging

    logger = logging.getLogger(__name__)

from app.services.alerts.sms import place_voice_call, send_sms

# Short list of conditions that deserve a 3am phone call.
CRITICAL_CONDITIONS: dict[str, str] = {
    "market_data_down": "Core market data feed down (indices/quotes unavailable)",
    "auth_login_broken": "Auth/login broken — users cannot sign in",
    "chat_forecast_down": "AI Chat or Forecast API fully unavailable",
    "cross_user_data_leak": "Suspected cross-user data isolation breach",
}

# Health reporter row names that are NEVER wake-up tier (Telegram only).
_TELEGRAM_ONLY_CHECKS = frozenset(
    {
        "forecast_direction_accuracy",
        "terminal_widget_latency",
        "orderbook_ws_liveness",
        "news_feed_freshness",
        "expired_open_positions",
        "forecast_sample_growth",
        "aitunnel_token_balance",
    }
)

_cooldown_memory: dict[str, float] = {}


def _row_is_market_data_critical(row: dict[str, Any]) -> bool:
    if row.get("status") != "failed":
        return False
    err = (row.get("error") or "").lower()
    if "indices stale" in err or "indices down" in err:
        return True
    if row.get("indices_down"):
        return True
    # Entire feed down, not a single stale symbol.
    if row.get("ok_count", 1) == 0:
        return True
    return False


def _row_is_chat_forecast_critical(row: dict[str, Any]) -> bool:
    if row.get("status") != "failed":
        return False
    name = row.get("name", "")
    err = (row.get("error") or "").lower()
    if name in {"chat_availability", "forecast_availability", "chat_forecast_availability"}:
        return True
    if name == "chat_no_raw_debug":
        # Timeout / connectivity = service down; debug leak string stays Telegram-only.
        if any(k in err for k in ("timeout", "connect", "refused", "no message", "503", "502", "504")):
            return True
        if row.get("service_down"):
            return True
    return False


def classify_critical_failures(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Map health check rows to critical condition keys (may be empty)."""
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    for row in results:
        if row.get("status") != "failed":
            continue
        name = row.get("name", "")
        if name in _TELEGRAM_ONLY_CHECKS:
            continue

        key: str | None = None
        if name == "auth_login":
            key = "auth_login_broken"
        elif name == "cross_user_position_isolation":
            key = "cross_user_data_leak"
        elif name == "market_data_freshness" and _row_is_market_data_critical(row):
            key = "market_data_down"
        elif _row_is_chat_forecast_critical(row):
            key = "chat_forecast_down"

        if key and key not in seen:
            seen.add(key)
            out.append(
                {
                    "key": key,
                    "title": CRITICAL_CONDITIONS[key],
                    "check": name,
                    "error": (row.get("error") or "")[:500],
                }
            )
    return out


async def _in_cooldown(condition_key: str, cooldown_s: int) -> bool:
    if cooldown_s <= 0:
        return False
    cache_key = f"critical_escalation:{condition_key}"
    try:
        from app.utils.cache import cache_get

        raw = await cache_get(cache_key)
        if raw:
            return True
    except Exception:
        last = _cooldown_memory.get(condition_key)
        if last and (time.time() - last) < cooldown_s:
            return True
    return False


async def _set_cooldown(condition_key: str, cooldown_s: int) -> None:
    cache_key = f"critical_escalation:{condition_key}"
    try:
        from app.utils.cache import cache_set

        await cache_set(cache_key, "1", ttl=cooldown_s)
    except Exception:
        _cooldown_memory[condition_key] = time.time()


async def escalate_critical(
    failures: list[dict[str, Any]],
    *,
    settings: Settings | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """
    Send voice/SMS for critical failures. Returns delivery summary (no secret values).
    """
    settings = settings or get_settings()
    phones = settings.critical_escalation_phones
    mode = (settings.CRITICAL_ESCALATION_MODE or "voice").strip().lower()
    cooldown = int(settings.CRITICAL_ESCALATION_COOLDOWN_SECONDS or 900)

    if not failures:
        return {"attempted": False, "reason": "no_critical_failures", "deliveries": []}

    if not phones:
        logger.warning("critical_escalation_no_phones", conditions=[f["key"] for f in failures])
        return {"attempted": False, "reason": "no_phones_configured", "failures": failures}

    if not settings.twilio_configured and (settings.SMS_PROVIDER or "stub") != "stub":
        logger.warning("critical_escalation_twilio_missing")
        return {"attempted": False, "reason": "twilio_not_configured", "failures": failures}

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    deliveries: list[dict[str, Any]] = []

    for item in failures:
        key = item["key"]
        if not force and await _in_cooldown(key, cooldown):
            deliveries.append({"condition": key, "skipped": "cooldown"})
            continue

        summary = "; ".join(f"{item['check']}: {item['error'][:120]}" for item in [item])
        sms_body = f"CRITICAL Apex Intel [{key}] {ts}. {summary}"[:300]
        voice_body = f"Critical alert. Apex Intel. {item['title']}. {item['error'][:200]}"

        for phone in phones:
            entry: dict[str, Any] = {"condition": key, "phone_tail": phone[-4:]}
            if mode in {"sms", "both"}:
                sms_res = await send_sms(phone, sms_body, settings=settings)
                entry["sms"] = {"ok": sms_res.get("ok"), "sid": sms_res.get("sid")}
            if mode in {"voice", "both"}:
                voice_res = await place_voice_call(phone, voice_body, settings=settings)
                entry["voice"] = {"ok": voice_res.get("ok"), "sid": voice_res.get("sid")}
            deliveries.append(entry)

        await _set_cooldown(key, cooldown)
        logger.warning("critical_escalation_sent", condition=key, phones=len(phones), mode=mode)

    any_ok = any(
        (d.get("sms") or {}).get("ok") or (d.get("voice") or {}).get("ok")
        for d in deliveries
        if not d.get("skipped")
    )
    return {
        "attempted": True,
        "mode": mode,
        "deliveries": deliveries,
        "any_delivered": any_ok,
        "failures": failures,
    }


async def simulate_critical(condition_key: str, *, settings: Settings | None = None) -> dict[str, Any]:
    """Proof helper: fire wake-up tier for one condition without running full health suite."""
    if condition_key not in CRITICAL_CONDITIONS:
        raise ValueError(f"unknown condition: {condition_key}; choose from {list(CRITICAL_CONDITIONS)}")
    fake = [
        {
            "key": condition_key,
            "title": CRITICAL_CONDITIONS[condition_key],
            "check": "simulated",
            "error": f"Simulated critical test at {datetime.now(timezone.utc).isoformat()}",
        }
    ]
    return await escalate_critical(fake, settings=settings, force=True)
