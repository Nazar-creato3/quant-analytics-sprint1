"""Shared Telegram Bot API helper for internal ops alerts only."""
from __future__ import annotations

import os

import httpx
import structlog

from app.core.config import Settings, get_settings
from app.core.http_proxy import httpx_client_kwargs

logger = structlog.get_logger(__name__)
TIMEOUT = httpx.Timeout(25.0, connect=10.0)
OFFICIAL_API_BASE = "https://api.telegram.org"


def _telegram_api_base(cfg: Settings) -> str:
    base = (
        getattr(cfg, "TELEGRAM_API_BASE_URL", None)
        or os.environ.get("TELEGRAM_API_BASE_URL")
        or ""
    ).strip()
    if not base:
        return OFFICIAL_API_BASE
    return base.rstrip("/")


def _is_blocked_bridge_response(status_code: int, body: str) -> bool:
    text = (body or "").lower()
    return status_code in (401, 403, 451) or "access to this resource is blocked" in text


async def _post_send_message(url: str, payload: dict[str, object], *, foreign: bool) -> httpx.Response:
    kwargs = httpx_client_kwargs(foreign=foreign, timeout=TIMEOUT)
    async with httpx.AsyncClient(**kwargs) as client:
        return await client.post(url, json=payload)


async def send_telegram_message(
    chat_id: str,
    text: str,
    *,
    settings: Settings | None = None,
    parse_mode: str | None = None,
    disable_notification: bool = False,
) -> bool:
    """Send a Telegram message. Returns True on success, False otherwise.

    Prefer configured TELEGRAM_API_BASE_URL (local bridge). If the bridge blocks
    the request, fall back to api.telegram.org via FOREIGN_HTTPS_PROXY.
    """
    cfg = settings or get_settings()
    token = (cfg.TELEGRAM_BOT_TOKEN or "").strip()
    if not token or not chat_id.strip():
        logger.warning("telegram_send_skipped", reason="missing_token_or_chat_id")
        return False

    payload: dict[str, object] = {
        "chat_id": chat_id.strip(),
        "text": text[:4096],
        "disable_notification": disable_notification,
    }
    if parse_mode:
        payload["parse_mode"] = parse_mode

    api_base = _telegram_api_base(cfg)
    primary_url = f"{api_base}/bot{token}/sendMessage"
    # Local/RU bridges are direct; official Telegram needs the foreign proxy on RU VPS.
    primary_foreign = "api.telegram.org" in api_base

    try:
        response = await _post_send_message(primary_url, payload, foreign=primary_foreign)
        response.raise_for_status()
        logger.info("telegram_message_sent", chat_id=chat_id[:8] + "…", api_base=api_base)
        return True
    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:500]
        logger.warning(
            "telegram_message_failed",
            chat_id=chat_id[:8] + "…",
            status=exc.response.status_code,
            body=body,
            api_base=api_base,
        )
        if api_base.rstrip("/") == OFFICIAL_API_BASE.rstrip("/"):
            return False
        if not _is_blocked_bridge_response(exc.response.status_code, body):
            return False
    except Exception as exc:
        logger.warning(
            "telegram_message_failed",
            chat_id=chat_id[:8] + "…",
            error=str(exc),
            api_base=api_base,
        )
        if api_base.rstrip("/") == OFFICIAL_API_BASE.rstrip("/"):
            return False

    # Fallback: official Bot API through FOREIGN_HTTPS_PROXY.
    fallback_url = f"{OFFICIAL_API_BASE}/bot{token}/sendMessage"
    try:
        response = await _post_send_message(fallback_url, payload, foreign=True)
        response.raise_for_status()
        logger.info(
            "telegram_message_sent",
            chat_id=chat_id[:8] + "…",
            api_base=OFFICIAL_API_BASE,
            via="foreign_proxy_fallback",
        )
        return True
    except httpx.HTTPStatusError as exc:
        logger.warning(
            "telegram_message_failed",
            chat_id=chat_id[:8] + "…",
            status=exc.response.status_code,
            body=exc.response.text[:500],
            api_base=OFFICIAL_API_BASE,
            via="foreign_proxy_fallback",
        )
        return False
    except Exception as exc:
        logger.warning(
            "telegram_message_failed",
            chat_id=chat_id[:8] + "…",
            error=str(exc),
            api_base=OFFICIAL_API_BASE,
            via="foreign_proxy_fallback",
        )
        return False
