"""Concrete LLM provider adapters (env-keyed)."""
from __future__ import annotations

import json
import os
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.services.privacy.service import prepare_llm_outbound

from app.services.terminal_platform.llm.base import (
    LLMChunk,
    LLMConfig,
    LLMProvider,
    LLMProviderError,
    LLMResponse,
    ToolDefinition,
)
from app.services.terminal_platform.llm.openai_compat import (
    build_messages,
    openai_chat_completion,
    openai_stream_completion,
)


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


class OpenAICompatibleProvider(LLMProvider):
    """Base for providers that speak OpenAI chat/completions."""

    def __init__(
        self,
        *,
        name: str,
        model: str,
        api_key: str,
        base_url: str,
        rate_limit: int | None = None,
        supports_tools: bool = True,
        extra_headers: dict[str, str] | None = None,
    ) -> None:
        self.name = name
        self.model = model
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self.rate_limit = rate_limit
        self.supports_tools = supports_tools
        self._extra_headers = extra_headers

    def is_available(self) -> bool:
        return bool(self._api_key and self._base_url)

    async def generate(
        self,
        prompt: str,
        *,
        context: dict[str, Any] | str | None = None,
        tools: list[ToolDefinition] | None = None,
        config: LLMConfig | None = None,
        system: str | None = None,
    ) -> LLMResponse:
        if not self.is_available():
            raise LLMProviderError(self.name, "missing API key or base URL", retryable=False)
        cfg = config or LLMConfig()
        messages = build_messages(prompt, system=system, context=context)
        return await openai_chat_completion(
            provider_name=self.name,
            base_url=self._base_url,
            api_key=self._api_key,
            model=self.model,
            messages=messages,
            config=cfg,
            tools=tools if self.supports_tools else None,
            extra_headers=self._extra_headers,
        )

    async def stream_generate(
        self,
        prompt: str,
        *,
        context: dict[str, Any] | str | None = None,
        tools: list[ToolDefinition] | None = None,
        config: LLMConfig | None = None,
        system: str | None = None,
    ) -> AsyncIterator[LLMChunk]:
        if not self.is_available():
            raise LLMProviderError(self.name, "missing API key or base URL", retryable=False)
        cfg = config or LLMConfig()
        messages = build_messages(prompt, system=system, context=context)
        async for chunk in openai_stream_completion(
            provider_name=self.name,
            base_url=self._base_url,
            api_key=self._api_key,
            model=self.model,
            messages=messages,
            config=cfg,
        ):
            yield chunk


class OpenAIProvider(OpenAICompatibleProvider):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ) -> None:
        super().__init__(
            name="openai",
            model=model or _env("OPENAI_MODEL", "gpt-4.1"),
            api_key=api_key if api_key is not None else _env("OPENAI_API_KEY"),
            base_url=base_url or _env("OPENAI_BASE_URL", "https://api.openai.com/v1"),
            rate_limit=60,
        )


class GroqProvider(OpenAICompatibleProvider):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        super().__init__(
            name="groq",
            model=model or _env("GROQ_MODEL", "llama-3.3-70b-versatile"),
            api_key=api_key if api_key is not None else _env("GROQ_API_KEY"),
            base_url=_env("GROQ_BASE_URL", "https://api.groq.com/openai/v1"),
            rate_limit=30,
        )


class DeepSeekProvider(OpenAICompatibleProvider):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        super().__init__(
            name="deepseek",
            model=model or _env("DEEPSEEK_MODEL", "deepseek-chat"),
            api_key=api_key if api_key is not None else _env("DEEPSEEK_API_KEY"),
            base_url=_env("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"),
            rate_limit=60,
        )


class OpenRouterProvider(OpenAICompatibleProvider):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        super().__init__(
            name="openrouter",
            model=model or _env("OPENROUTER_MODEL", "openrouter/auto"),
            api_key=api_key if api_key is not None else _env("OPENROUTER_API_KEY"),
            base_url=_env("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
            rate_limit=60,
            extra_headers={
                "HTTP-Referer": _env("OPENROUTER_HTTP_REFERER", "https://apex-intel.local"),
                "X-Title": _env("OPENROUTER_APP_TITLE", "Apex Intel Terminal"),
            },
        )


class OllamaProvider(OpenAICompatibleProvider):
    """Local Ollama — no API key required; availability = base URL reachable intent."""

    def __init__(
        self,
        *,
        model: str | None = None,
        base_url: str | None = None,
        enabled: bool | None = None,
    ) -> None:
        flag = _env("OLLAMA_ENABLED", "false").lower() in {"1", "true", "yes"}
        self._enabled = flag if enabled is None else enabled
        # Ollama OpenAI-compat often ignores Authorization; use a placeholder key.
        super().__init__(
            name="ollama",
            model=model or _env("OLLAMA_MODEL", "qwen2.5:latest"),
            api_key=_env("OLLAMA_API_KEY", "ollama"),
            base_url=base_url or _env("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
            rate_limit=None,
            supports_tools=False,
        )

    def is_available(self) -> bool:
        return self._enabled and bool(self._base_url)


class AITunnelProvider(OpenAICompatibleProvider):
    """Adapter over existing LLMService / AITUNNEL gateway."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
    ) -> None:
        key = api_key
        url = base_url
        mdl = model
        try:
            from app.core.config import settings
            from app.services.llm.llm_service import llm_api_key, llm_base_url, model_for_task

            if key is None:
                key = llm_api_key()
            if url is None:
                url = llm_base_url()
            if mdl is None:
                mdl = model_for_task("client_chat") or settings.LLM_MODEL_CLIENT_CHAT
        except Exception:  # noqa: BLE001
            key = key if key is not None else _env("AITUNNEL_API_KEY") or _env("OPENAI_API_KEY")
            url = url or _env("AITUNNEL_BASE_URL", "https://api.aitunnel.ru/v1")
            mdl = mdl or _env("LLM_MODEL_CLIENT_CHAT", "")

        super().__init__(
            name="aitunnel",
            model=mdl,
            api_key=key or "",
            base_url=url or "https://api.aitunnel.ru/v1",
            rate_limit=60,
        )

    def is_available(self) -> bool:
        try:
            from app.core.config import settings
            from app.services.llm.llm_service import llm_enabled

            return bool(settings.LLM_ENABLED and llm_enabled() and self._api_key)
        except Exception:  # noqa: BLE001
            return bool(self._api_key)


class AnthropicProvider(LLMProvider):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self.name = "anthropic"
        self.model = model or _env("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
        self._api_key = api_key if api_key is not None else _env("ANTHROPIC_API_KEY")
        self._base_url = _env("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
        self.rate_limit = 60
        self.supports_tools = True

    def is_available(self) -> bool:
        return bool(self._api_key)

    async def generate(
        self,
        prompt: str,
        *,
        context: dict[str, Any] | str | None = None,
        tools: list[ToolDefinition] | None = None,
        config: LLMConfig | None = None,
        system: str | None = None,
    ) -> LLMResponse:
        if not self.is_available():
            raise LLMProviderError(self.name, "missing ANTHROPIC_API_KEY", retryable=False)
        cfg = config or LLMConfig()
        messages = build_messages(prompt, context=context)
        # Anthropic: system is top-level, messages are user/assistant only
        user_messages = [m for m in messages if m["role"] != "system"]
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": cfg.max_tokens,
            "temperature": cfg.temperature,
            "messages": user_messages,
        }
        if system:
            payload["system"] = system
        elif any(m["role"] == "system" for m in messages):
            payload["system"] = next(m["content"] for m in messages if m["role"] == "system")
        if tools:
            payload["tools"] = [
                {
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.parameters or {"type": "object", "properties": {}},
                }
                for t in tools
            ]

        url = f"{self._base_url.rstrip('/')}/v1/messages"
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(cfg.timeout_seconds)) as client:
                resp = await client.post(url, headers=headers, json=prepare_llm_outbound(payload))
                if resp.status_code in (401, 403):
                    raise LLMProviderError(self.name, f"auth failed ({resp.status_code})", retryable=False)
                if resp.status_code == 429:
                    raise LLMProviderError(self.name, "rate limited", retryable=True)
                resp.raise_for_status()
                data = resp.json()
        except LLMProviderError:
            raise
        except httpx.TimeoutException as exc:
            raise LLMProviderError(self.name, f"timeout: {exc}", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise LLMProviderError(self.name, f"http error: {exc}", retryable=True) from exc

        parts = data.get("content") or []
        text = "".join(p.get("text", "") for p in parts if isinstance(p, dict) and p.get("type") == "text")
        usage_raw = data.get("usage") or {}
        return LLMResponse(
            content=text.strip(),
            provider=self.name,
            model=self.model,
            usage={
                "prompt_tokens": int(usage_raw.get("input_tokens") or 0),
                "completion_tokens": int(usage_raw.get("output_tokens") or 0),
                "total_tokens": int(usage_raw.get("input_tokens") or 0)
                + int(usage_raw.get("output_tokens") or 0),
            },
            raw=data if isinstance(data, dict) else {},
            finish_reason=data.get("stop_reason"),
        )


class GeminiProvider(LLMProvider):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
    ) -> None:
        self.name = "gemini"
        self.model = model or _env("GEMINI_MODEL", "gemini-2.5-pro")
        self._api_key = api_key if api_key is not None else (
            _env("GEMINI_API_KEY") or _env("GOOGLE_API_KEY")
        )
        self._base_url = _env(
            "GEMINI_BASE_URL",
            "https://generativelanguage.googleapis.com/v1beta",
        )
        self.rate_limit = 60
        self.supports_tools = True

    def is_available(self) -> bool:
        return bool(self._api_key)

    async def generate(
        self,
        prompt: str,
        *,
        context: dict[str, Any] | str | None = None,
        tools: list[ToolDefinition] | None = None,
        config: LLMConfig | None = None,
        system: str | None = None,
    ) -> LLMResponse:
        if not self.is_available():
            raise LLMProviderError(self.name, "missing GEMINI_API_KEY", retryable=False)
        cfg = config or LLMConfig()
        ctx = ""
        if isinstance(context, str):
            ctx = context.strip()
        elif context is not None:
            ctx = json.dumps(context, ensure_ascii=False, default=str)
        user_text = prompt if not ctx else f"{ctx}\n\n{prompt.strip()}"

        body: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": user_text}]}],
            "generationConfig": {
                "temperature": cfg.temperature,
                "maxOutputTokens": cfg.max_tokens,
            },
        }
        if system:
            body["systemInstruction"] = {"parts": [{"text": system}]}
        if cfg.response_format == "json_object":
            body["generationConfig"]["responseMimeType"] = "application/json"
        if tools:
            body["tools"] = [
                {
                    "functionDeclarations": [
                        {
                            "name": t.name,
                            "description": t.description,
                            "parameters": t.parameters or {"type": "object", "properties": {}},
                        }
                        for t in tools
                    ]
                }
            ]

        url = (
            f"{self._base_url.rstrip('/')}/models/{self.model}:generateContent"
            f"?key={self._api_key}"
        )
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(cfg.timeout_seconds)) as client:
                resp = await client.post(url, json=prepare_llm_outbound(body))
                if resp.status_code in (401, 403):
                    raise LLMProviderError(self.name, f"auth failed ({resp.status_code})", retryable=False)
                if resp.status_code == 429:
                    raise LLMProviderError(self.name, "rate limited", retryable=True)
                resp.raise_for_status()
                data = resp.json()
        except LLMProviderError:
            raise
        except httpx.TimeoutException as exc:
            raise LLMProviderError(self.name, f"timeout: {exc}", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise LLMProviderError(self.name, f"http error: {exc}", retryable=True) from exc

        try:
            candidates = data.get("candidates") or []
            parts = ((candidates[0].get("content") or {}).get("parts")) or []
            text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
            meta = data.get("usageMetadata") or {}
        except (IndexError, AttributeError, TypeError) as exc:
            raise LLMProviderError(self.name, f"unexpected response: {exc}") from exc

        return LLMResponse(
            content=text.strip(),
            provider=self.name,
            model=self.model,
            usage={
                "prompt_tokens": int(meta.get("promptTokenCount") or 0),
                "completion_tokens": int(meta.get("candidatesTokenCount") or 0),
                "total_tokens": int(meta.get("totalTokenCount") or 0),
            },
            raw=data if isinstance(data, dict) else {},
            finish_reason=(candidates[0].get("finishReason") if candidates else None),
        )
