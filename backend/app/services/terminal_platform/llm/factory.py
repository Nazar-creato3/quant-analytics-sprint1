"""Factory: build LLM providers / router from env."""
from __future__ import annotations

import os

from app.services.terminal_platform.llm.base import LLMProvider
from app.services.terminal_platform.llm.providers import (
    AITunnelProvider,
    AnthropicProvider,
    DeepSeekProvider,
    GeminiProvider,
    GroqProvider,
    OllamaProvider,
    OpenAIProvider,
    OpenRouterProvider,
)
from app.services.terminal_platform.llm.router import LLMRouter

_PROVIDER_BUILDERS: dict[str, type] = {
    "aitunnel": AITunnelProvider,
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "gemini": GeminiProvider,
    "groq": GroqProvider,
    "deepseek": DeepSeekProvider,
    "ollama": OllamaProvider,
    "openrouter": OpenRouterProvider,
}

# Default fallback order: reuse AITUNNEL first, then majors, then local.
_DEFAULT_ORDER = (
    "aitunnel",
    "openai",
    "anthropic",
    "gemini",
    "groq",
    "deepseek",
    "openrouter",
    "ollama",
)


def create_provider(name: str, **kwargs) -> LLMProvider:
    key = name.strip().lower()
    cls = _PROVIDER_BUILDERS.get(key)
    if cls is None:
        raise ValueError(f"Unknown LLM provider: {name!r}. Known: {sorted(_PROVIDER_BUILDERS)}")
    return cls(**kwargs)


def provider_order_from_env() -> list[str]:
    raw = (os.environ.get("TERMINAL_LLM_FALLBACK_ORDER") or "").strip()
    if not raw:
        return list(_DEFAULT_ORDER)
    return [p.strip().lower() for p in raw.split(",") if p.strip()]


def build_providers(
    order: list[str] | None = None,
    *,
    only_available: bool = False,
) -> list[LLMProvider]:
    names = order or provider_order_from_env()
    providers: list[LLMProvider] = []
    for name in names:
        if name not in _PROVIDER_BUILDERS:
            continue
        provider = create_provider(name)
        if only_available and not provider.is_available():
            continue
        providers.append(provider)
    return providers


def build_default_router(*, only_available: bool = False) -> LLMRouter:
    providers = build_providers(only_available=only_available)
    if not providers:
        # Always include aitunnel stub so router construction succeeds;
        # generate() will fail clearly if no keys.
        providers = [AITunnelProvider()]
    return LLMRouter(providers)


def get_default_llm_provider(*, only_available: bool = True) -> LLMProvider | None:
    """First configured provider from TERMINAL_LLM_FALLBACK_ORDER (or default order)."""
    providers = build_providers(only_available=only_available)
    return providers[0] if providers else None
