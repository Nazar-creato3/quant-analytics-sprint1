"""LLMRouter — ordered fallback across providers."""
from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from app.core.logging import get_logger
from app.services.terminal_platform.llm.base import (
    LLMChunk,
    LLMConfig,
    LLMProvider,
    LLMProviderError,
    LLMResponse,
    ToolDefinition,
)

logger = get_logger(__name__)


class LLMRouter:
    """Try providers in priority order until one succeeds."""

    def __init__(
        self,
        providers: list[LLMProvider],
        *,
        skip_unavailable: bool = True,
    ) -> None:
        if not providers:
            raise ValueError("LLMRouter requires at least one provider")
        self.providers = list(providers)
        self.skip_unavailable = skip_unavailable
        self.last_provider: str | None = None
        self.last_error: str | None = None

    def available_providers(self) -> list[LLMProvider]:
        if not self.skip_unavailable:
            return list(self.providers)
        return [p for p in self.providers if p.is_available()]

    async def generate_with_fallback(
        self,
        prompt: str,
        *,
        context: dict[str, Any] | str | None = None,
        tools: list[ToolDefinition] | None = None,
        config: LLMConfig | None = None,
        system: str | None = None,
    ) -> LLMResponse:
        errors: list[str] = []
        chain = self.available_providers()
        if not chain:
            raise LLMProviderError("router", "no available LLM providers", retryable=False)

        for provider in chain:
            try:
                resp = await provider.generate(
                    prompt,
                    context=context,
                    tools=tools,
                    config=config,
                    system=system,
                )
                self.last_provider = provider.name
                self.last_error = None
                logger.info("llm_router_success", provider=provider.name, model=provider.model)
                return resp
            except LLMProviderError as exc:
                errors.append(str(exc))
                self.last_error = str(exc)
                logger.warning(
                    "llm_router_fallback",
                    provider=provider.name,
                    error=str(exc),
                    retryable=exc.retryable,
                )
                if not exc.retryable and provider is chain[-1]:
                    break
                continue
            except Exception as exc:  # noqa: BLE001
                errors.append(f"[{provider.name}] {exc}")
                self.last_error = str(exc)
                logger.warning("llm_router_fallback", provider=provider.name, error=str(exc))
                continue

        raise LLMProviderError(
            "router",
            "all providers failed: " + " | ".join(errors),
            retryable=True,
        )

    async def stream_with_fallback(
        self,
        prompt: str,
        *,
        context: dict[str, Any] | str | None = None,
        tools: list[ToolDefinition] | None = None,
        config: LLMConfig | None = None,
        system: str | None = None,
    ) -> AsyncIterator[LLMChunk]:
        errors: list[str] = []
        chain = self.available_providers()
        if not chain:
            raise LLMProviderError("router", "no available LLM providers", retryable=False)

        for provider in chain:
            try:
                async for chunk in provider.stream_generate(
                    prompt,
                    context=context,
                    tools=tools,
                    config=config,
                    system=system,
                ):
                    self.last_provider = provider.name
                    yield chunk
                self.last_error = None
                return
            except LLMProviderError as exc:
                errors.append(str(exc))
                self.last_error = str(exc)
                continue
            except Exception as exc:  # noqa: BLE001
                errors.append(f"[{provider.name}] {exc}")
                self.last_error = str(exc)
                continue

        raise LLMProviderError(
            "router",
            "all providers failed (stream): " + " | ".join(errors),
            retryable=True,
        )

    # Alias used by agents
    async def generate(self, *args: Any, **kwargs: Any) -> LLMResponse:
        return await self.generate_with_fallback(*args, **kwargs)
