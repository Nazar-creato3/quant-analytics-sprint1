"""Shared OpenAI-compatible chat/completions HTTP helper."""
from __future__ import annotations

import json
from typing import Any

import httpx

from app.services.llm.destination import OnpremPublicBlocked, ensure_model_url
from app.services.privacy.service import prepare_llm_outbound
from app.services.terminal_platform.llm.base import (
    LLMChunk,
    LLMConfig,
    LLMProviderError,
    LLMResponse,
    ToolDefinition,
)


def _context_to_text(context: dict[str, Any] | str | None) -> str:
    if context is None:
        return ""
    if isinstance(context, str):
        return context.strip()
    return json.dumps(context, ensure_ascii=False, default=str)


def build_messages(
    prompt: str,
    *,
    system: str | None = None,
    context: dict[str, Any] | str | None = None,
) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    ctx = _context_to_text(context)
    user_body = prompt if not ctx else f"{ctx}\n\n{prompt.strip()}"
    messages.append({"role": "user", "content": user_body})
    return messages


def tools_to_openai(tools: list[ToolDefinition] | None) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters or {"type": "object", "properties": {}},
            },
        }
        for t in tools
    ]


async def openai_chat_completion(
    *,
    provider_name: str,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    config: LLMConfig,
    tools: list[ToolDefinition] | None = None,
    extra_headers: dict[str, str] | None = None,
) -> LLMResponse:
    try:
        root = ensure_model_url(base_url)
    except OnpremPublicBlocked as exc:
        raise LLMProviderError(provider_name, "on-prem refuses a public model URL", retryable=False) from exc
    url = f"{root.rstrip('/')}/chat/completions"
    headers = {"Content-Type": "application/json", **(extra_headers or {})}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
    }
    oai_tools = tools_to_openai(tools)
    if oai_tools:
        payload["tools"] = oai_tools
    if config.response_format == "json_object":
        payload["response_format"] = {"type": "json_object"}
    payload = prepare_llm_outbound(payload)

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(config.timeout_seconds)) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code in (401, 403):
                raise LLMProviderError(provider_name, f"auth failed ({resp.status_code})", retryable=False)
            if resp.status_code == 429:
                raise LLMProviderError(provider_name, "rate limited", retryable=True)
            resp.raise_for_status()
            data = resp.json()
    except LLMProviderError:
        raise
    except httpx.TimeoutException as exc:
        raise LLMProviderError(provider_name, f"timeout: {exc}", retryable=True) from exc
    except httpx.HTTPError as exc:
        raise LLMProviderError(provider_name, f"http error: {exc}", retryable=True) from exc
    except Exception as exc:  # noqa: BLE001
        raise LLMProviderError(provider_name, str(exc), retryable=True) from exc

    try:
        choice = data["choices"][0]
        content = (choice.get("message") or {}).get("content") or ""
        finish = choice.get("finish_reason")
        usage_raw = data.get("usage") or {}
        usage = {
            "prompt_tokens": int(usage_raw.get("prompt_tokens") or 0),
            "completion_tokens": int(usage_raw.get("completion_tokens") or 0),
            "total_tokens": int(usage_raw.get("total_tokens") or 0),
        }
    except (KeyError, IndexError, TypeError) as exc:
        raise LLMProviderError(provider_name, f"unexpected response shape: {exc}") from exc

    return LLMResponse(
        content=content.strip(),
        provider=provider_name,
        model=model,
        usage=usage,
        raw=data if isinstance(data, dict) else {},
        finish_reason=finish,
    )


async def openai_stream_completion(
    *,
    provider_name: str,
    base_url: str,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    config: LLMConfig,
) -> Any:
    """Async generator of LLMChunk from SSE stream."""
    try:
        root = ensure_model_url(base_url)
    except OnpremPublicBlocked as exc:
        raise LLMProviderError(provider_name, "on-prem refuses a public model URL", retryable=False) from exc
    url = f"{root.rstrip('/')}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload: dict[str, Any] = prepare_llm_outbound(
        {
            "model": model,
            "messages": messages,
            "temperature": config.temperature,
            "max_tokens": config.max_tokens,
            "stream": True,
        }
    )
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(config.timeout_seconds)) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as resp:
                if resp.status_code >= 400:
                    body = await resp.aread()
                    raise LLMProviderError(
                        provider_name,
                        f"stream http {resp.status_code}: {body[:200]!r}",
                        retryable=resp.status_code == 429,
                    )
                async for line in resp.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue
                    data_str = line[5:].strip()
                    if data_str == "[DONE]":
                        yield LLMChunk(content="", provider=provider_name, model=model, done=True)
                        return
                    try:
                        data = json.loads(data_str)
                        delta = (data["choices"][0].get("delta") or {}).get("content") or ""
                        if delta:
                            yield LLMChunk(content=delta, provider=provider_name, model=model)
                    except (json.JSONDecodeError, KeyError, IndexError, TypeError):
                        continue
    except LLMProviderError:
        raise
    except httpx.TimeoutException as exc:
        raise LLMProviderError(provider_name, f"timeout: {exc}", retryable=True) from exc
    except httpx.HTTPError as exc:
        raise LLMProviderError(provider_name, f"http error: {exc}", retryable=True) from exc
