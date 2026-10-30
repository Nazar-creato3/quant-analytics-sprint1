"""Third-party crypto stack integrations (adapters + registry)."""
from __future__ import annotations

from typing import Any

from app.services.crypto_stack.integrations.base import IntegrationAdapter
from app.services.crypto_stack.integrations.ccxt_pip import CcxtPipIntegration
from app.services.crypto_stack.integrations.celebrum import CelebrumIntegration
from app.services.crypto_stack.integrations.crypto_analytics import CryptoAnalyticsIntegration
from app.services.crypto_stack.integrations.crypto_pulse import CryptoPulseIntegration
from app.services.crypto_stack.integrations.cryptodevtools import CryptoDevToolsIntegration
from app.services.crypto_stack.integrations.opentao import OpenTaoIntegration
from app.services.crypto_stack.integrations.tradingagents import TradingAgentsIntegration

_REGISTRY: dict[str, IntegrationAdapter] = {
    TradingAgentsIntegration.name: TradingAgentsIntegration(),
    CryptoDevToolsIntegration.name: CryptoDevToolsIntegration(),
    CryptoAnalyticsIntegration.name: CryptoAnalyticsIntegration(),
    CryptoPulseIntegration.name: CryptoPulseIntegration(),
    OpenTaoIntegration.name: OpenTaoIntegration(),
    CelebrumIntegration.name: CelebrumIntegration(),
    CcxtPipIntegration.name: CcxtPipIntegration(),
}

INTEGRATION_NAMES: tuple[str, ...] = tuple(_REGISTRY.keys())


def get_integration(name: str) -> IntegrationAdapter | None:
    return _REGISTRY.get(name)


def list_integrations() -> list[dict[str, Any]]:
    """Return status payloads for every registered integration."""
    out: list[dict[str, Any]] = []
    for name in INTEGRATION_NAMES:
        adapter = _REGISTRY[name]
        try:
            payload = adapter.status()
        except Exception as exc:  # noqa: BLE001 — listing must never raise
            payload = {
                "name": name,
                "installed": False,
                "runnable": False,
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
        out.append(payload)
    return out


__all__ = [
    "INTEGRATION_NAMES",
    "get_integration",
    "list_integrations",
    "IntegrationAdapter",
]
