"""Shared import / sidecar probe helpers."""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from typing import Any

from app.services.crypto_stack.integrations.http_util import probe_url
from app.services.crypto_stack.integrations.paths import path_status


def _patch_plotly_templates_for_vectorbt() -> None:
    """Plotly 6 removed scattermapbox; vectorbt templates still reference it."""
    try:
        import plotly.io as pio

        for template_name in list(pio.templates):
            tmpl = pio.templates[template_name]
            data = getattr(tmpl, "data", None)
            if data is not None and hasattr(data, "scattermapbox"):
                try:
                    delattr(data, "scattermapbox")
                except Exception:
                    pass
    except Exception:
        pass


def probe_import(name: str, import_path: str) -> dict[str, Any]:
    # vectorbt/numba needs a writable cache dir in read-only-ish containers
    if import_path == "vectorbt" or name == "vectorbt":
        cache = os.environ.get("NUMBA_CACHE_DIR") or "/tmp/numba_cache"
        os.environ.setdefault("NUMBA_CACHE_DIR", cache)
        try:
            Path(cache).mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        _patch_plotly_templates_for_vectorbt()
    try:
        spec = importlib.util.find_spec(import_path)
        if spec is None:
            return {"available": False, "error": "not_installed"}
        try:
            mod = __import__(import_path)
            version = getattr(mod, "__version__", None)
            return {"available": True, "importable": True, "version": version, "error": None}
        except Exception as exc:  # noqa: BLE001
            return {
                "available": True,
                "importable": False,
                "version": None,
                "error": f"{type(exc).__name__}: {exc}",
            }
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": f"{type(exc).__name__}: {exc}"}


def sidecar_status(env_var: str, default_url: str, *, health_path: str = "health") -> dict[str, Any]:
    base = (os.getenv(env_var) or default_url).rstrip("/")
    probe = probe_url(f"{base}/{health_path.lstrip('/')}")
    return {
        "base_url": base,
        "env_var": env_var,
        "probe": probe,
        "reachable": probe.get("reachable", False),
        "ok": probe.get("ok", False),
    }


def clone_status(dirname: str) -> dict[str, Any]:
    return path_status(dirname)
