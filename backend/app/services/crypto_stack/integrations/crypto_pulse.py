"""Crypto_pulse_AI — Vite/React research UI (status + optional npm script invoke)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from typing import Any

from app.services.crypto_stack.integrations.base import status_payload
from app.services.crypto_stack.integrations.http_util import probe_url
from app.services.crypto_stack.integrations.paths import path_status, third_party_path

NAME = "crypto-pulse-ai"
DIRNAME = "Crypto_pulse_AI"
DOCS = "https://github.com/Gmpho/Crypto_pulse_AI"
DEFAULT_DEV_URL = "http://127.0.0.1:5173"


class CryptoPulseIntegration:
    name = NAME

    def _dev_url(self) -> str:
        return os.environ.get("CRYPTO_PULSE_URL", DEFAULT_DEV_URL).rstrip("/")

    def status(self) -> dict[str, Any]:
        base = path_status(DIRNAME)
        root = third_party_path(DIRNAME)
        pkg_json = root / "package.json"
        has_pkg = pkg_json.is_file() if base["installed"] else False
        npm = shutil.which("npm")
        node_modules = (root / "node_modules").is_dir() if base["installed"] else False
        live = probe_url(self._dev_url()) if base["installed"] else {"reachable": False, "ok": False}
        # Runnable when clone is ready to start (npm + package.json) or Vite is already up.
        runnable = bool(
            base["installed"]
            and has_pkg
            and (node_modules or bool(npm) or bool(live.get("reachable")))
        )
        return status_payload(
            name=NAME,
            installed=base["installed"],
            runnable=runnable,
            mode="vite_sidecar",
            docs=DOCS,
            detail={
                **base,
                "package_json": has_pkg,
                "node_modules": node_modules,
                "npm": npm,
                "dev_url": self._dev_url(),
                "live": live,
                "start_script": "scripts/start-crypto-pulse.ps1",
                "activate": "scripts/start-crypto-pulse.ps1 (or scripts/start-all-crypto-sidecars.ps1)",
            },
            error=None if base["installed"] else "third_party/Crypto_pulse_AI not cloned",
        )

    def capabilities(self) -> dict[str, Any]:
        return {
            "name": NAME,
            "actions": ["probe", "npm_script"],
            "notes": (
                "Frontend-first Vite app. Start via scripts/start-crypto-pulse.ps1 "
                "(npm install && npm run dev). Gemini keys via env — never hardcode."
            ),
            "env": ["CRYPTO_PULSE_URL", "GEMINI_API_KEY"],
        }

    def action(self, **kwargs: Any) -> dict[str, Any]:
        st = self.status()
        if not st.get("installed"):
            return {"ok": False, "action": "probe", "error": st.get("error")}

        kind = (kwargs.get("kind") or "probe").lower()
        root = third_party_path(DIRNAME)

        if kind == "npm_script":
            script = str(kwargs.get("script") or "build")
            if script not in {"build", "preview"}:
                return {
                    "ok": False,
                    "action": "npm_script",
                    "error": "only_build_or_preview_allowed",
                }
            npm = shutil.which("npm")
            if not npm:
                return {"ok": False, "action": "npm_script", "error": "npm_not_found"}
            timeout = float(kwargs.get("timeout") or 120)
            try:
                proc = subprocess.run(
                    [npm, "run", script],
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=str(root),
                )
                return {
                    "ok": proc.returncode == 0,
                    "action": "npm_script",
                    "script": script,
                    "exit_code": proc.returncode,
                    "stdout_tail": (proc.stdout or "")[-600:],
                    "stderr_tail": (proc.stderr or "")[-600:],
                }
            except subprocess.TimeoutExpired:
                return {"ok": False, "action": "npm_script", "error": f"timeout_after_{timeout}s"}
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "action": "npm_script", "error": f"{type(exc).__name__}: {exc}"}

        # Default probe: package.json + optional live URL
        scripts: dict[str, Any] = {}
        pkg = root / "package.json"
        if pkg.is_file():
            try:
                scripts = json.loads(pkg.read_text(encoding="utf-8")).get("scripts") or {}
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "action": "probe", "error": f"package_json: {exc}"}

        live = probe_url(self._dev_url())
        return {
            "ok": True,
            "action": "probe",
            "scripts": list(scripts.keys()),
            "dev_url": self._dev_url(),
            "live": live,
            "hint": (
                None
                if live.get("reachable")
                else "Run scripts/start-crypto-pulse.ps1 to start Vite on :5173"
            ),
        }
