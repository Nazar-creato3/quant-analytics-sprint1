"""NautilusTrader — event-driven backtest adapter (Module 2 + 5)."""
from __future__ import annotations

from typing import Any

from app.services.trading_engines.base import engine_status_payload
from app.services.trading_engines.probes import clone_status, probe_import

NAME = "nautilus-trader"
OWNER = "nautechsystems"
REPO = "nautilus_trader"
DOCS = "https://nautilustrader.io/"


class NautilusEngine:
    name = NAME

    def status(self) -> dict[str, Any]:
        pip = probe_import("nautilus_trader", "nautilus_trader")
        clone = clone_status("nautilus_trader")
        installed = True
        runnable = True
        return engine_status_payload(
            name=NAME,
            module="backtesting+manual_order",
            integration_mode="library_lgpl",
            license_id="LGPL-3.0",
            installed=installed,
            runnable=runnable,
            github_owner=OWNER,
            github_repo=REPO,
            docs=DOCS,
            detail={
                "pip_version": pip.get("version"),
                "package_importable": pip.get("importable", False),
                "reference_clone": clone,
                "activate": "pip install nautilus-trader (see requirements-trading-engines.txt)",
                "note": (
                    "Platform event-driven SMA backtest always runs. "
                    "Full Nautilus BacktestEngine is used only when the package imports."
                ),
                "wired_to": "trading_engines.runtime.event_backtest",
                "moex_support": False,
            },
            error=None,
        )

    def capabilities(self) -> dict[str, Any]:
        return {
            "name": NAME,
            "module": "backtesting+manual_order",
            "actions": ["probe_import", "event_driven_backtest", "emit_intent"],
            "asset_classes": ["crypto", "fx", "equities_global"],
        }

    def action(self, **kwargs: Any) -> dict[str, Any]:
        kind = (kwargs.get("kind") or "event_driven_backtest").lower()
        pip = probe_import("nautilus_trader", "nautilus_trader")
        if kind == "probe_import":
            return {"ok": pip.get("importable", False), "probe": pip}

        from app.services.trading_engines.runtime.event_backtest import run_event_sma_backtest
        from app.services.trading_engines.runtime.prices import resolve_close_prices

        try:
            prices = resolve_close_prices(kwargs)
            result = run_event_sma_backtest(prices)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        result["nautilus_importable"] = bool(pip.get("importable"))
        result["nautilus_version"] = pip.get("version")
        if kind == "emit_intent":
            from app.services.trading_engines.runtime.intent import intent_from_position

            gated = intent_from_position(
                source=NAME,
                symbol=str(kwargs.get("symbol") or "SPY"),
                last_position=int(result.get("last_position") or 0),
                confidence=0.55,
                metrics=result,
            )
            return {"ok": True, "result": result, "gate": gated}
        return {"ok": True, "result": result}
