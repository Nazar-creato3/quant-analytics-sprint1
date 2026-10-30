"""ccxt — production path is pip; third_party/ccxt is reference-only (never on sys.path)."""
from __future__ import annotations

from typing import Any

from app.services.crypto_stack.integrations.base import status_payload
from app.services.crypto_stack.integrations.paths import path_status

NAME = "ccxt"
DIRNAME = "ccxt"
DOCS = "https://github.com/ccxt/ccxt"
PIP_DOCS = "https://pypi.org/project/ccxt/"


class CcxtPipIntegration:
    name = NAME

    def status(self) -> dict[str, Any]:
        clone = path_status(DIRNAME)
        pip_ok = False
        version = None
        exchange_count = None
        import_error = None
        try:
            import ccxt  # type: ignore

            pip_ok = True
            version = getattr(ccxt, "__version__", "unknown")
            exchanges = getattr(ccxt, "exchanges", None)
            if exchanges is not None:
                exchange_count = len(list(exchanges))
        except Exception as exc:  # noqa: BLE001
            import_error = f"{type(exc).__name__}: {exc}"

        return status_payload(
            name=NAME,
            installed=pip_ok,  # production install = pip, not the clone
            runnable=pip_ok,
            mode="pip_production",
            docs=PIP_DOCS,
            detail={
                "production": "pip",
                "pip_version": version,
                "exchange_count": exchange_count,
                "reference_clone": clone,
                "reference_note": (
                    "third_party/ccxt is reference-only; do NOT add it to PYTHONPATH. "
                    "Market endpoints use pip ccxt."
                ),
                "clone_docs": DOCS,
            },
            error=import_error,
        )

    def capabilities(self) -> dict[str, Any]:
        return {
            "name": NAME,
            "actions": ["exchange_count", "list_exchanges_sample"],
            "notes": (
                "Clone under third_party/ccxt is documentation/reference. "
                "Runtime uses site-packages ccxt (see crypto_stack.market)."
            ),
        }

    def action(self, **kwargs: Any) -> dict[str, Any]:
        kind = (kwargs.get("kind") or "exchange_count").lower()
        try:
            import ccxt  # type: ignore
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "action": kind,
                "error": f"pip_ccxt_missing: {type(exc).__name__}: {exc}",
                "hint": "pip install ccxt into backend/.venv",
            }

        exchanges = list(getattr(ccxt, "exchanges", []) or [])
        if kind == "list_exchanges_sample":
            return {
                "ok": True,
                "action": "list_exchanges_sample",
                "count": len(exchanges),
                "sample": exchanges[:25],
                "version": getattr(ccxt, "__version__", "unknown"),
                "source": "pip",
            }

        return {
            "ok": True,
            "action": "exchange_count",
            "count": len(exchanges),
            "version": getattr(ccxt, "__version__", "unknown"),
            "source": "pip",
            "reference_clone_installed": path_status(DIRNAME)["installed"],
        }
