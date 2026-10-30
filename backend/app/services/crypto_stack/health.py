"""Import / availability probes for the crypto stack."""
from __future__ import annotations

from typing import Any


def _probe(name: str, import_path: str) -> dict[str, Any]:
    """Prefer find_spec (install presence); fall back to import for runtime errors."""
    import importlib.util

    try:
        spec = importlib.util.find_spec(import_path)
        if spec is None:
            return {"name": name, "available": False, "error": "not_installed"}
        # Light import attempt — some packages (cryptodatapy) may fail on heavy deps
        try:
            __import__(import_path)
            return {"name": name, "available": True, "importable": True, "error": None}
        except Exception as exc:  # noqa: BLE001
            return {
                "name": name,
                "available": True,
                "importable": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
    except Exception as exc:  # noqa: BLE001 — health must never raise
        return {"name": name, "available": False, "error": f"{type(exc).__name__}: {exc}"}


def stack_health() -> dict[str, Any]:
    """Return availability of optional crypto-stack packages."""
    probes = [
        _probe("ccxt", "ccxt"),
        _probe("cryptodatapy", "cryptodatapy"),
        _probe("supabase", "supabase"),
        _probe("streamlit", "streamlit"),
        _probe("binance_context_server", "binance_context_server"),
        # crypto-powerdata-mcp installs as top-level package name "src" (upstream quirk)
        _probe("crypto_powerdata_mcp", "src"),
    ]
    available = sum(1 for p in probes if p["available"])
    return {
        "ok": available >= 1,
        "available_count": available,
        "total": len(probes),
        "packages": probes,
    }
