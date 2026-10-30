"""Freqtrade — GPL sidecar for grid-bot execution (Module 3)."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from app.services.trading_engines.base import engine_status_payload
from app.services.trading_engines.grid.freqtrade_bridge import (
    default_signal_path,
    read_signal_state,
    write_signal_state,
)
from app.services.trading_engines.probes import clone_status, sidecar_status

NAME = "freqtrade"
OWNER = "freqtrade"
REPO = "freqtrade"
DOCS = "https://www.freqtrade.io/"


class FreqtradeEngine:
    name = NAME

    def status(self) -> dict[str, Any]:
        clone = clone_status("freqtrade")
        sidecar = sidecar_status("FREQTRADE_URL", "http://127.0.0.1:8081", health_path="api/v1/ping")
        signal_path = default_signal_path()
        signal_exists = signal_path.is_file()
        # Sidecar OR clone OR signal bridge counts as "installed"
        installed = clone.get("installed") or sidecar.get("reachable") or signal_exists
        runnable = sidecar.get("ok") or signal_exists
        err = None
        if not installed:
            err = "freqtrade sidecar not running; clone missing; no signal file"
        return engine_status_payload(
            name=NAME,
            module="grid_bots",
            integration_mode="sidecar_gpl",
            license_id="GPL-3.0",
            installed=installed,
            runnable=runnable,
            github_owner=OWNER,
            github_repo=REPO,
            docs=DOCS,
            detail={
                "reference_clone": clone,
                "sidecar": sidecar,
                "signal_path": str(signal_path),
                "signal_file_exists": signal_exists,
                "integration": "JSON signal bridge — codebases stay separate",
            },
            error=err if not runnable else None,
        )

    def capabilities(self) -> dict[str, Any]:
        return {
            "name": NAME,
            "module": "grid_bots",
            "actions": ["write_signal", "read_signal", "sidecar_ping"],
            "env": ["FREQTRADE_URL", "FREQTRADE_SIGNAL_PATH"],
        }

    def action(self, **kwargs: Any) -> dict[str, Any]:
        kind = (kwargs.get("kind") or "read_signal").lower()
        if kind == "sidecar_ping":
            sidecar = sidecar_status("FREQTRADE_URL", "http://127.0.0.1:8081", health_path="api/v1/ping")
            return {"ok": sidecar.get("ok", False), "sidecar": sidecar}
        if kind == "write_signal":
            payload = kwargs.get("payload") or {
                "symbol": kwargs.get("symbol", "BTC/USDT"),
                "direction": kwargs.get("direction", "long"),
                "target_weight": float(kwargs.get("target_weight", 0.1)),
                "source": "apex-intel",
            }
            path = write_signal_state(payload)
            return {"ok": True, "path": str(path), "payload": payload}
        state = read_signal_state()
        return {"ok": state is not None, "state": state}
