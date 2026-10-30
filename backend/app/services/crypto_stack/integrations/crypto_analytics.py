"""crypto-analytics-platform — Docker sidecar + HTTP health/proxy (not merged into prod compose)."""
from __future__ import annotations

import os
from typing import Any

from app.services.crypto_stack.integrations.base import status_payload
from app.services.crypto_stack.integrations.http_util import probe_url, proxy_get
from app.services.crypto_stack.integrations.paths import path_status, third_party_path

NAME = "crypto-analytics-platform"
DIRNAME = "crypto-analytics-platform"
DOCS = "https://github.com/Sarfraspc/crypto-analytics-platform"
DEFAULT_BASE = "http://127.0.0.1:18000"


class CryptoAnalyticsIntegration:
    name = NAME

    def _base_url(self) -> str:
        return os.environ.get("CAP_BACKEND_URL", DEFAULT_BASE).rstrip("/")

    def status(self) -> dict[str, Any]:
        base = path_status(DIRNAME)
        root = third_party_path(DIRNAME)
        compose = (root / "docker-compose.yml").is_file() if base["installed"] else False
        health = probe_url(f"{self._base_url()}/health") if base["installed"] else {
            "reachable": False,
            "ok": False,
            "error": "not_installed",
        }
        runnable = bool(health.get("reachable") and health.get("ok"))
        return status_payload(
            name=NAME,
            installed=base["installed"],
            runnable=runnable,
            mode="docker_sidecar",
            docs=DOCS,
            detail={
                **base,
                "compose": compose,
                "base_url": self._base_url(),
                "health": health,
                "overlay": "docker-compose.crypto-analytics.yml",
                "start_script": "scripts/start-crypto-analytics.ps1",
                "docs_ui": f"{self._base_url()}/docs",
            },
            error=None if base["installed"] else "third_party/crypto-analytics-platform not cloned",
        )

    def capabilities(self) -> dict[str, Any]:
        return {
            "name": NAME,
            "actions": ["health_probe", "proxy_get"],
            "notes": (
                "Separate Docker stack. Use overlay docker-compose.crypto-analytics.yml "
                "(host port 18000 by default) — do not merge into docker-compose.prod.yml."
            ),
            "env": ["CAP_BACKEND_URL", "CAP_HOST_PORT"],
        }

    def action(self, **kwargs: Any) -> dict[str, Any]:
        st = self.status()
        if not st.get("installed"):
            return {"ok": False, "action": "health_probe", "error": st.get("error")}

        kind = (kwargs.get("kind") or "health_probe").lower()
        if kind == "proxy_get":
            path = str(kwargs.get("path") or "health")
            result = proxy_get(self._base_url(), path)
            result["action"] = "proxy_get"
            return result

        health = probe_url(f"{self._base_url()}/health")
        return {
            "ok": bool(health.get("ok")),
            "action": "health_probe",
            "health": health,
            "docs": f"{self._base_url()}/docs",
            "hint": (
                None
                if health.get("reachable")
                else "Run scripts/start-crypto-analytics.ps1 (needs Docker + local .env.docker)"
            ),
        }

    def proxy(self, path: str) -> dict[str, Any]:
        return proxy_get(self._base_url(), path)
