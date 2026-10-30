"""OpenTaoAPI — Bittensor data API (Docker/uvicorn sidecar + proxy)."""
from __future__ import annotations

import os
from typing import Any

from app.services.crypto_stack.integrations.base import status_payload
from app.services.crypto_stack.integrations.http_util import probe_url, proxy_get
from app.services.crypto_stack.integrations.paths import path_status, third_party_path

NAME = "opentao-api"
DIRNAME = "OpenTaoAPI"
DOCS = "https://github.com/ryanmercier/OpenTaoAPI"
DEFAULT_BASE = "http://127.0.0.1:3000"


class OpenTaoIntegration:
    name = NAME

    def _base_url(self) -> str:
        return os.environ.get("OPENTAO_URL", DEFAULT_BASE).rstrip("/")

    def status(self) -> dict[str, Any]:
        base = path_status(DIRNAME)
        root = third_party_path(DIRNAME)
        compose = (root / "docker-compose.yml").is_file() if base["installed"] else False
        api_main = (root / "api" / "main.py").is_file() if base["installed"] else False
        # Prefer /docs (FastAPI) — /health may or may not exist
        health = probe_url(f"{self._base_url()}/docs") if base["installed"] else {
            "reachable": False,
            "ok": False,
            "error": "not_installed",
        }
        if base["installed"] and not health.get("reachable"):
            health = probe_url(f"{self._base_url()}/")
        runnable = bool(health.get("reachable"))
        return status_payload(
            name=NAME,
            installed=base["installed"],
            runnable=runnable,
            mode="docker_sidecar",
            docs=DOCS,
            detail={
                **base,
                "compose": compose,
                "api_main": api_main,
                "base_url": self._base_url(),
                "probe": health,
                "start_script": "scripts/start-opentao.ps1",
                "docs_ui": f"{self._base_url()}/docs",
            },
            error=None if base["installed"] else "third_party/OpenTaoAPI not cloned",
        )

    def capabilities(self) -> dict[str, Any]:
        return {
            "name": NAME,
            "actions": ["health_probe", "proxy_get"],
            "notes": (
                "docker-compose maps host 3000→8000. Admin writes need OPENTAO_ADMIN_KEY in env."
            ),
            "env": ["OPENTAO_URL", "OPENTAO_ADMIN_KEY"],
        }

    def action(self, **kwargs: Any) -> dict[str, Any]:
        st = self.status()
        if not st.get("installed"):
            return {"ok": False, "action": "health_probe", "error": st.get("error")}

        kind = (kwargs.get("kind") or "health_probe").lower()
        if kind == "proxy_get":
            path = str(kwargs.get("path") or "docs")
            result = proxy_get(self._base_url(), path)
            result["action"] = "proxy_get"
            return result

        probe = probe_url(f"{self._base_url()}/docs")
        if not probe.get("reachable"):
            probe = probe_url(f"{self._base_url()}/")
        return {
            "ok": bool(probe.get("reachable")),
            "action": "health_probe",
            "probe": probe,
            "docs": f"{self._base_url()}/docs",
            "hint": (
                None
                if probe.get("reachable")
                else "Run scripts/start-opentao.ps1 (Docker) or uvicorn api.main:app --port 8000"
            ),
        }

    def proxy(self, path: str) -> dict[str, Any]:
        return proxy_get(self._base_url(), path)
