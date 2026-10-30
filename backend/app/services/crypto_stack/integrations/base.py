"""Integration adapter contract."""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class IntegrationAdapter(Protocol):
    """Each third_party stack exposes status, capabilities, and one safe action."""

    name: str

    def status(self) -> dict[str, Any]:
        """Installed path, runnable/importable flags, honest errors."""
        ...

    def capabilities(self) -> dict[str, Any]:
        """What this integration can do from apex-intel."""
        ...

    def action(self, **kwargs: Any) -> dict[str, Any]:
        """Probe / sample run; must fail gracefully if deps missing."""
        ...


def status_payload(
    *,
    name: str,
    installed: bool,
    runnable: bool,
    mode: str,
    detail: dict[str, Any] | None = None,
    error: str | None = None,
    docs: str | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "installed": installed,
        "runnable": runnable,
        "ok": installed and (error is None),
        "mode": mode,
        "error": error,
        "docs": docs,
        "detail": detail or {},
    }
