"""Engine adapter contract for GitHub-repo integrations."""
from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class EngineAdapter(Protocol):
    """Each trading-engine repo exposes status, capabilities, and a safe probe."""

    name: str

    def status(self) -> dict[str, Any]:
        ...

    def capabilities(self) -> dict[str, Any]:
        ...

    def action(self, **kwargs: Any) -> dict[str, Any]:
        ...


def engine_status_payload(
    *,
    name: str,
    module: str,
    integration_mode: str,
    license_id: str,
    installed: bool,
    runnable: bool,
    github_owner: str,
    github_repo: str,
    detail: dict[str, Any] | None = None,
    error: str | None = None,
    docs: str | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "module": module,
        "integration_mode": integration_mode,
        "license": license_id,
        "installed": installed,
        "runnable": runnable,
        "ok": installed and runnable and error is None,
        "error": error,
        "docs": docs,
        "github": f"https://github.com/{github_owner}/{github_repo}",
        "detail": detail or {},
    }
