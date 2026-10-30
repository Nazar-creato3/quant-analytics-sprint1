"""Unified OpenAI-compatible LLM client (AITUNNEL gateway)."""
from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.services.llm.aitunnel_balance import record_llm_usage
from app.services.llm.destination import (
    OnpremPublicBlocked,
    ensure_model_url,
    host_is_non_public,
    llm_onprem_active,
)
from app.services.llm.errors import AITUNNEL_UNAVAILABLE_RU, AITunnelUnavailableError
from app.services.llm import gigachat
from app.services.privacy.service import prepare_llm_outbound

logger = get_logger(__name__)

_TASKS_DISABLE_REASONING: frozenset[str] = frozenset({"forecast_narrative"})

_VERDICT_LAYER_PREFIXES: tuple[str, ...] = (
    "вердикт -",
    "почему -",
    "что изменит",
    "действие -",
)


def _raise_unavailable(reason: str, *, from_exc: Exception | None = None) -> None:
    msg = AITUNNEL_UNAVAILABLE_RU if not reason else f"{AITUNNEL_UNAVAILABLE_RU}: {reason}"
    if from_exc is not None:
        raise AITunnelUnavailableError(msg, reason=reason) from from_exc
    raise AITunnelUnavailableError(msg, reason=reason)


def _extract_message_text(message: dict[str, Any] | None) -> str:
    if not isinstance(message, dict):
        return ""
    content = (message.get("content") or "").strip()
    if content:
        return content
    reasoning = (message.get("reasoning") or message.get("reasoning_content") or "").strip()
    if not reasoning:
        return ""
    lines = [ln.strip() for ln in reasoning.replace("\r\n", "\n").split("\n") if ln.strip()]
    matched = [ln for ln in lines if any(ln.lower().startswith(p) for p in _VERDICT_LAYER_PREFIXES)]
    if len(matched) >= 3:
        return "\n".join(matched[:4])
    tail = "\n".join(lines[-4:])
    if any(p in tail.lower() for p in _VERDICT_LAYER_PREFIXES):
        return tail
    logger.warning("LLM returned empty content; reasoning fallback unusable", reasoning_chars=len(reasoning))
    return ""


def _parse_completion_response(data: Any) -> str:
    if not isinstance(data, dict):
        _raise_unavailable("некорректный ответ API")
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        _raise_unavailable("пустой ответ API")
    first = choices[0]
    if not isinstance(first, dict):
        _raise_unavailable("некорректный формат choices")
    message = first.get("message")
    if message is not None and not isinstance(message, dict):
        _raise_unavailable("некорректный формат message")
    return _extract_message_text(message if isinstance(message, dict) else None)


async def _track_usage(task_name: str, data: dict[str, Any], *, model: str | None) -> None:
    try:
        await record_llm_usage(task_name, data.get("usage"), model=model)
    except Exception as exc:
        logger.debug("aitunnel_usage_track_skipped", error=str(exc)[:120])


_TASK_TO_SETTING: dict[str, str] = {
    "inapp_chat": "LLM_MODEL_CLIENT_CHAT",
    "client_chat": "LLM_MODEL_CLIENT_CHAT",
    "senior_analyst_chat": "LLM_MODEL_CLIENT_CHAT",
    "forecast_narrative": "LLM_MODEL_CLIENT_CHAT",
    "compliance_pdf": "LLM_MODEL_CLIENT_CHAT",
    "weekly_report": "LLM_MODEL_BATCH",
    "news_sentiment_batch": "LLM_MODEL_BATCH",
    "news_event_extraction": "LLM_MODEL_BATCH",
    "news_translate": "LLM_MODEL_BATCH",
}


def llm_api_key() -> str:
    if llm_onprem_active():
        return (settings.LLM_ONPREM_API_KEY or "").strip()
    return (settings.AITUNNEL_API_KEY or settings.OPENAI_API_KEY or "").strip()


def llm_base_url() -> str:
    if llm_onprem_active():
        url = (settings.LLM_ONPREM_BASE_URL or "").strip().rstrip("/")
        if host_is_non_public(url):
            return url
        return ""
    return (settings.AITUNNEL_BASE_URL or "https://api.aitunnel.ru/v1").rstrip("/")


def model_for_task(task_name: str) -> str:
    if gigachat.gigachat_active():
        return str(settings.GIGACHAT_MODEL)
    attr = _TASK_TO_SETTING.get(task_name, "LLM_MODEL_BATCH")
    model = getattr(settings, attr, None) or settings.OPENAI_MODEL
    return str(model)


def llm_enabled() -> bool:
    if gigachat.gigachat_active():
        return bool(settings.LLM_ENABLED and gigachat.gigachat_configured())
    if llm_onprem_active():
        return bool(settings.LLM_ENABLED and llm_base_url())
    return bool(settings.LLM_ENABLED and llm_api_key())


async def _post_completion(payload: dict[str, Any]) -> dict[str, Any]:
    if gigachat.gigachat_active():
        body = prepare_llm_outbound(payload)
        try:
            return await gigachat.post_completion(body)
        except gigachat.GigaChatError as exc:
            _raise_unavailable(exc.reason, from_exc=exc)
        except httpx.TimeoutException as exc:
            _raise_unavailable("таймаут", from_exc=exc)
        except httpx.HTTPError as exc:
            _raise_unavailable("сеть", from_exc=exc)
    try:
        url = ensure_model_url(llm_base_url())
    except OnpremPublicBlocked as exc:
        _raise_unavailable("on-prem: публичный адрес запрещён", from_exc=exc)
    if not url:
        _raise_unavailable("on-prem: публичный адрес запрещён" if llm_onprem_active() else "LLM отключён или не настроен адрес")
    body = prepare_llm_outbound(payload)
    headers = {"Content-Type": "application/json"}
    key = llm_api_key()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(settings.LLM_TIMEOUT_SECONDS)) as client:
            resp = await client.post(
                f"{url}/chat/completions",
                headers=headers,
                json=body,
            )
    except httpx.TimeoutException as exc:
        _raise_unavailable("таймаут", from_exc=exc)
    except httpx.HTTPError as exc:
        _raise_unavailable("сеть", from_exc=exc)

    if resp.status_code in {402, 403, 429}:
        _raise_unavailable(f"HTTP {resp.status_code}")
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        _raise_unavailable(f"HTTP {resp.status_code}", from_exc=exc)

    try:
        return resp.json()
    except ValueError as exc:
        _raise_unavailable("некорректный JSON", from_exc=exc)


class LLMService:
    @staticmethod
    async def complete(
        task_name: str,
        prompt: str,
        *,
        system: str | None = None,
        context: str | None = None,
        temperature: float = 0.35,
        max_tokens: int = 1800,
    ) -> str:
        if not llm_enabled():
            _raise_unavailable("LLM отключён или не настроен ключ")
        model = model_for_task(task_name)
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        user_body = prompt if not context else f"{context.strip()}\n\n{prompt.strip()}"
        messages.append({"role": "user", "content": user_body})
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if task_name in _TASKS_DISABLE_REASONING and not gigachat.gigachat_active():
            payload["reasoning_effort"] = "none"

        data = await _post_completion(payload)
        try:
            result = _parse_completion_response(data)
        except AITunnelUnavailableError:
            raise
        except (TypeError, KeyError, IndexError, AttributeError) as exc:
            _raise_unavailable("ошибка разбора ответа", from_exc=exc)

        usage = data.get("usage") or {}
        await _track_usage(task_name, data, model=model)
        logger.info(
            "LLM complete",
            task=task_name,
            model=model,
            prompt_chars=len(user_body) + (len(system) if system else 0),
            response_chars=len(result),
            finish_reason=(data.get("choices") or [{}])[0].get("finish_reason"),
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            cost_rub=usage.get("cost_rub"),
            balance_rub=usage.get("balance"),
        )
        return result

    @staticmethod
    async def complete_with_tools(
        task_name: str,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.35,
        max_tokens: int = 1800,
    ) -> dict[str, Any]:
        if not llm_enabled():
            _raise_unavailable("LLM отключён или не настроен ключ")
        model = model_for_task(task_name)
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        data = await _post_completion(payload)
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            _raise_unavailable("пустой ответ API")
        first = choices[0]
        if not isinstance(first, dict):
            _raise_unavailable("некорректный формат choices")
        message = first.get("message")
        if message is not None and not isinstance(message, dict):
            _raise_unavailable("некорректный формат message")

        usage = data.get("usage") or {}
        await _track_usage(task_name, data, model=model)
        logger.info(
            "LLM complete_with_tools",
            task=task_name,
            model=model,
            message_chars=len(str((message or {}).get("content") or "")),
            tool_calls=len((message or {}).get("tool_calls") or []),
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            cost_rub=usage.get("cost_rub"),
            balance_rub=usage.get("balance"),
        )
        return message if isinstance(message, dict) else {}
