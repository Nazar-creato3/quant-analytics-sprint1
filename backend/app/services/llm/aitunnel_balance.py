"""AITUNNEL balance API + Redis-backed spend tracking for proactive alerts."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_USAGE_ZSET = "aitunnel:usage:events"
_LAST_BALANCE_KEY = "aitunnel:last_balance"
_RETENTION_SECONDS = 7 * 86400


@dataclass(frozen=True)
class BalanceSnapshot:
    balance_rub: float
    budget_rub: float | None
    source: str  # api | usage_fallback

    @property
    def effective_rub(self) -> float:
        if self.budget_rub is not None:
            return min(self.balance_rub, self.budget_rub)
        return self.balance_rub


def _api_key(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    return (settings.AITUNNEL_API_KEY or settings.OPENAI_API_KEY or "").strip()


def _base_url(settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    return (settings.AITUNNEL_BASE_URL or "https://api.aitunnel.ru/v1").rstrip("/")


async def fetch_balance_snapshot(settings: Settings | None = None) -> BalanceSnapshot:
    """Query GET /v1/aitunnel/balance; fall back to last usage.balance in Redis."""
    from app.services.llm.destination import llm_onprem_active

    settings = settings or get_settings()
    if llm_onprem_active():
        raise RuntimeError("on-prem: public balance endpoint is not called")
    key = _api_key(settings)
    if not key:
        raise RuntimeError("AITUNNEL_API_KEY not configured")

    url = f"{_base_url(settings)}/aitunnel/balance"
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(url, headers={"Authorization": f"Bearer {key}"})
    resp.raise_for_status()
    data = resp.json()
    balance = float(data.get("balance") or 0)
    budget_raw = data.get("budget")
    budget = float(budget_raw) if budget_raw is not None else None
    snap = BalanceSnapshot(balance_rub=balance, budget_rub=budget, source="api")
    await _cache_last_balance(snap)
    return snap


async def _cache_last_balance(snap: BalanceSnapshot) -> None:
    try:
        from app.utils.cache import cache_set

        await cache_set(
            _LAST_BALANCE_KEY,
            {
                "balance_rub": snap.balance_rub,
                "budget_rub": snap.budget_rub,
                "source": snap.source,
                "ts": time.time(),
            },
            ttl=86400 * 14,
        )
    except Exception as exc:
        logger.debug("aitunnel_balance_cache_failed", error=str(exc)[:120])


async def _load_cached_balance() -> BalanceSnapshot | None:
    try:
        from app.utils.cache import cache_get

        raw = await cache_get(_LAST_BALANCE_KEY)
        if not isinstance(raw, dict):
            return None
        return BalanceSnapshot(
            balance_rub=float(raw.get("balance_rub") or 0),
            budget_rub=float(raw["budget_rub"]) if raw.get("budget_rub") is not None else None,
            source=str(raw.get("source") or "usage_fallback"),
        )
    except Exception:
        return None


async def record_llm_usage(
    task_name: str,
    usage: dict[str, Any] | None,
    *,
    model: str | None = None,
) -> None:
    """Persist token/cost from an AITUNNEL chat completion (best-effort)."""
    if not usage:
        return

    cost_rub = float(usage.get("cost_rub") or 0)
    prompt_tokens = int(usage.get("prompt_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or 0)
    balance_after = usage.get("balance")

    logger.info(
        "aitunnel_usage",
        task=task_name,
        model=model,
        cost_rub=cost_rub,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        balance_rub=balance_after,
    )

    if balance_after is not None:
        try:
            await _cache_last_balance(
                BalanceSnapshot(
                    balance_rub=float(balance_after),
                    budget_rub=None,
                    source="usage_fallback",
                )
            )
        except Exception:
            pass

    if cost_rub <= 0 and prompt_tokens <= 0 and completion_tokens <= 0:
        return

    now = time.time()
    member = json.dumps(
        {
            "task": task_name,
            "model": model,
            "cost_rub": cost_rub,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "ts": now,
        },
        separators=(",", ":"),
    )
    try:
        from app.utils.cache import _get_redis  # noqa: SLF001 — shared pool

        r = _get_redis()
        pipe = r.pipeline()
        pipe.zadd(_USAGE_ZSET, {member: now})
        pipe.zremrangebyscore(_USAGE_ZSET, "-inf", now - _RETENTION_SECONDS)
        await pipe.execute()
    except Exception as exc:
        logger.warning("aitunnel_usage_persist_failed", error=str(exc)[:200])


async def spend_rub_last_hours(hours: float = 24.0) -> float:
    """Sum recorded cost_rub over the rolling window."""
    cutoff = time.time() - hours * 3600
    try:
        from app.utils.cache import _get_redis  # noqa: SLF001

        r = _get_redis()
        rows = await r.zrangebyscore(_USAGE_ZSET, cutoff, "+inf")
    except Exception as exc:
        logger.warning("aitunnel_spend_query_failed", error=str(exc)[:200])
        return 0.0

    total = 0.0
    for raw in rows:
        try:
            row = json.loads(raw)
            total += float(row.get("cost_rub") or 0)
        except Exception:
            continue
    return total


def _alert_hours(settings: Settings) -> float:
    return max(1.0, float(getattr(settings, "AITUNNEL_BALANCE_ALERT_HOURS", 24) or 24))


def _fallback_threshold_rub(settings: Settings) -> float:
    return max(0.0, float(getattr(settings, "AITUNNEL_BALANCE_ALERT_RUB", 100) or 100))


async def assess_balance(settings: Settings | None = None) -> dict[str, Any]:
    """
    Evaluate whether AITUNNEL balance covers ~N hours of typical usage.
    Returns a dict suitable for health reporter rows.
    """
    from app.services.llm.destination import llm_onprem_active

    settings = settings or get_settings()
    if llm_onprem_active():
        return {"skipped": True, "reason": "onprem"}
    if not settings.LLM_ENABLED:
        return {"skipped": True, "reason": "llm_disabled"}
    if not _api_key(settings):
        return {"skipped": True, "reason": "missing_api_key"}

    alert_hours = _alert_hours(settings)
    spend_24h = await spend_rub_last_hours(24.0)
    spend_7d = await spend_rub_last_hours(24.0 * 7)
    daily_avg = spend_7d / 7.0 if spend_7d > 0 else 0.0
    # spend_rub_last_hours returns totals for the window — convert to ₽/hour runway math.
    burn_rate_per_hour = (
        spend_24h / 24.0
        if spend_24h > 0
        else (daily_avg / 24.0 if daily_avg > 0 else 0.0)
    )
    threshold = (
        burn_rate_per_hour * alert_hours
        if burn_rate_per_hour > 0
        else _fallback_threshold_rub(settings)
    )

    snap: BalanceSnapshot | None = None
    api_error: str | None = None
    try:
        snap = await fetch_balance_snapshot(settings)
    except Exception as exc:
        api_error = str(exc)[:300]
        snap = await _load_cached_balance()

    if snap is None:
        if burn_rate_per_hour > 0:
            return {
                "skipped": False,
                "status": "failed",
                "error": f"balance API unavailable ({api_error}); no cached balance",
                "burn_rub_24h": round(spend_24h, 2),
                "threshold_rub": round(threshold, 2),
            }
        return {
            "skipped": True,
            "reason": "balance_api_unavailable",
            "api_error": api_error,
        }

    effective = snap.effective_rub
    hours_left = (effective / burn_rate_per_hour) if burn_rate_per_hour > 0 else None

    detail_parts = [
        f"balance={snap.balance_rub:.2f}₽",
        f"effective={effective:.2f}₽",
        f"source={snap.source}",
    ]
    if snap.budget_rub is not None:
        detail_parts.append(f"budget={snap.budget_rub:.2f}₽")
    if burn_rate_per_hour > 0:
        detail_parts.append(f"burn_24h={spend_24h:.2f}₽")
        detail_parts.append(f"threshold={threshold:.2f}₽ ({alert_hours:.0f}h)")
        if hours_left is not None:
            detail_parts.append(f"~{hours_left:.1f}h left")
    else:
        detail_parts.append(f"threshold={threshold:.2f}₽ (fallback, no spend history)")

    low = effective < threshold
    if low:
        msg = f"AITUNNEL balance low: {effective:.2f}₽ < {threshold:.2f}₽ (~{alert_hours:.0f}h runway)"
        if hours_left is not None and hours_left < alert_hours:
            msg = f"AITUNNEL exhaustion ~{hours_left:.1f}h — {msg}"
        return {
            "skipped": False,
            "status": "failed",
            "error": msg,
            "detail": "; ".join(detail_parts),
            "balance_rub": snap.balance_rub,
            "effective_rub": effective,
            "budget_rub": snap.budget_rub,
            "burn_rub_24h": round(spend_24h, 2),
            "threshold_rub": round(threshold, 2),
            "hours_remaining": round(hours_left, 2) if hours_left is not None else None,
        }

    return {
        "skipped": False,
        "status": "passed",
        "detail": "; ".join(detail_parts),
        "balance_rub": snap.balance_rub,
        "effective_rub": effective,
        "budget_rub": snap.budget_rub,
        "burn_rub_24h": round(spend_24h, 2),
        "threshold_rub": round(threshold, 2),
        "hours_remaining": round(hours_left, 2) if hours_left is not None else None,
    }
