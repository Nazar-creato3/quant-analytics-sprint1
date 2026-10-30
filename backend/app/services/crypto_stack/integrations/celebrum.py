"""celebrum-ai-go (NeuraTrade) — Go sidecar / binary status + optional health proxy."""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from app.services.crypto_stack.integrations.base import status_payload
from app.services.crypto_stack.integrations.http_util import probe_url, proxy_get
from app.services.crypto_stack.integrations.paths import path_status, third_party_path

NAME = "celebrum-ai-go"
DIRNAME = "celebrum-ai-go"
DOCS = "https://github.com/irfndi/celebrum-ai-go"
DEFAULT_BASE = "http://127.0.0.1:8080"


class CelebrumIntegration:
    name = NAME

    def _base_url(self) -> str:
        return os.environ.get("CELEBRUM_URL", DEFAULT_BASE).rstrip("/")

    def status(self) -> dict[str, Any]:
        base = path_status(DIRNAME)
        root = third_party_path(DIRNAME)
        go_bin = shutil.which("go")
        compose = (root / "docker-compose.yml").is_file() if base["installed"] else False
        backend_mod = root / "services" / "backend-api" / "go.mod"
        built = self._find_binary(root) if base["installed"] else None
        health = probe_url(f"{self._base_url()}/health") if base["installed"] else {
            "reachable": False,
            "ok": False,
            "error": "not_installed",
        }
        sidecar_up = bool(health.get("reachable") and health.get("ok"))
        toolchain_ready = bool(
            base["installed"] and (compose or (go_bin and backend_mod.is_file()))
        )
        runnable = sidecar_up or toolchain_ready
        return status_payload(
            name=NAME,
            installed=base["installed"],
            runnable=runnable,
            mode="go_sidecar",
            docs=DOCS,
            detail={
                **base,
                "compose": compose,
                "go_available": bool(go_bin),
                "go_path": go_bin,
                "backend_go_mod": backend_mod.is_file() if base["installed"] else False,
                "binary": built,
                "base_url": self._base_url(),
                "health": health,
                "sidecar_up": sidecar_up,
                "start_script": "scripts/start-celebrum.ps1",
                "activate": "scripts/start-celebrum.ps1 (or scripts/start-all-crypto-sidecars.ps1)",
                "notes": "Needs Go 1.26+ for native build, or Docker compose for backend-api :8080",
            },
            error=None if base["installed"] else "third_party/celebrum-ai-go not cloned",
        )

    def capabilities(self) -> dict[str, Any]:
        return {
            "name": NAME,
            "actions": ["health_probe", "proxy_get", "toolchain_check"],
            "notes": (
                "Prefer Docker sidecar (port 8080). Native: make build && ./bin/neuratrade gateway start."
            ),
            "env": ["CELEBRUM_URL", "POSTGRES_PASSWORD", "TELEGRAM_BOT_TOKEN"],
        }

    def action(self, **kwargs: Any) -> dict[str, Any]:
        st = self.status()
        if not st.get("installed"):
            return {"ok": False, "action": "health_probe", "error": st.get("error")}

        kind = (kwargs.get("kind") or "health_probe").lower()
        if kind == "toolchain_check":
            go_bin = shutil.which("go")
            version = None
            if go_bin:
                import subprocess

                try:
                    proc = subprocess.run(
                        [go_bin, "version"],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    version = (proc.stdout or proc.stderr or "").strip()
                except Exception as exc:  # noqa: BLE001
                    version = f"error: {exc}"
            return {
                "ok": bool(go_bin),
                "action": "toolchain_check",
                "go": go_bin,
                "version": version,
                "binary": st.get("detail", {}).get("binary"),
                "hint": (
                    None
                    if go_bin
                    else "Install Go 1.26+ or use Docker: scripts/start-celebrum.ps1"
                ),
            }

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
            "hint": (
                None
                if health.get("reachable")
                else "Run scripts/start-celebrum.ps1 or build with Go and start gateway"
            ),
        }

    def proxy(self, path: str) -> dict[str, Any]:
        return proxy_get(self._base_url(), path)

    @staticmethod
    def _find_binary(root: Path) -> str | None:
        candidates = [
            root / "bin" / "neuratrade",
            root / "bin" / "neuratrade.exe",
            root / "bin" / "celebrum-ai-go",
            root / "bin" / "celebrum-ai-go.exe",
        ]
        for c in candidates:
            if c.is_file():
                return str(c)
        return None
