"""LLMProvider ABC and shared response types."""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel, Field


class ToolDefinition(BaseModel):
    """Function-calling tool schema passed to an LLM."""

    name: str
    description: str = ""
    parameters: dict[str, Any] = Field(default_factory=dict)


class LLMConfig(BaseModel):
    """Per-call generation knobs."""

    temperature: float = 0.35
    max_tokens: int = 2048
    timeout_seconds: float = 75.0
    response_format: str | None = None  # e.g. "json_object"


class LLMResponse(BaseModel):
    """Normalized completion payload."""

    content: str
    provider: str
    model: str
    usage: dict[str, int] = Field(default_factory=dict)
    raw: dict[str, Any] = Field(default_factory=dict)
    finish_reason: str | None = None


class LLMChunk(BaseModel):
    """Streaming token/chunk."""

    content: str
    provider: str
    model: str
    done: bool = False


class LLMProviderError(RuntimeError):
    """Raised when a provider fails (auth, rate limit, timeout, etc.)."""

    def __init__(self, provider: str, message: str, *, retryable: bool = True) -> None:
        self.provider = provider
        self.retryable = retryable
        super().__init__(f"[{provider}] {message}")


class LLMProvider(ABC):
    """Abstract multi-provider LLM client."""

    name: str = "base"
    model: str = ""
    rate_limit: int | None = None
    supports_tools: bool = False

    @abstractmethod
    def is_available(self) -> bool:
        """True when credentials/endpoint allow real API calls."""

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        *,
        context: dict[str, Any] | str | None = None,
        tools: list[ToolDefinition] | None = None,
        config: LLMConfig | None = None,
        system: str | None = None,
    ) -> LLMResponse:
        """Produce a full completion."""

    async def stream_generate(
        self,
        prompt: str,
        *,
        context: dict[str, Any] | str | None = None,
        tools: list[ToolDefinition] | None = None,
        config: LLMConfig | None = None,
        system: str | None = None,
    ) -> AsyncIterator[LLMChunk]:
        """Default streaming: yield the full generate() result as one chunk."""
        resp = await self.generate(
            prompt, context=context, tools=tools, config=config, system=system
        )
        yield LLMChunk(content=resp.content, provider=resp.provider, model=resp.model, done=True)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name!r}, model={self.model!r})"
