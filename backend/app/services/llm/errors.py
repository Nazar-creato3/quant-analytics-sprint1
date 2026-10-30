"""AITunnel / LLM availability errors with user-facing Russian messages."""
from __future__ import annotations

# User-facing: no provider or service names in the interface.
AITUNNEL_UNAVAILABLE_RU = "Пояснение ИИ временно недоступно"
LLM_UNAVAILABLE_USER_RU = "Пояснение ИИ временно недоступно — повторите через минуту."


class AITunnelUnavailableError(RuntimeError):
    """Raised when AITunnel cannot serve LLM requests (balance, outage, bad response)."""

    def __init__(self, message: str = AITUNNEL_UNAVAILABLE_RU, *, reason: str | None = None) -> None:
        detail = message.strip() or AITUNNEL_UNAVAILABLE_RU
        if reason and reason not in detail:
            detail = f"{detail}: {reason}"
        super().__init__(detail)
        self.reason = reason
