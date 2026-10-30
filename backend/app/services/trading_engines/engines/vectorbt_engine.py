"""VectorBT — fast vectorized backtest (Module 2: Backtesting)."""
from __future__ import annotations

from typing import Any

from app.services.trading_engines.base import engine_status_payload
from app.services.trading_engines.probes import clone_status, probe_import

NAME = "vectorbt"
OWNER = "polakowo"
REPO = "vectorbt"
DOCS = "https://vectorbt.dev/"


class VectorbtEngine:
    name = NAME

    def status(self) -> dict[str, Any]:
        pip = probe_import("vectorbt", "vectorbt")
        clone = clone_status("vectorbt")
        installed = pip.get("available", False)
        runnable = installed and pip.get("importable", False)
        license_note = None
        if runnable:
            try:
                import vectorbt as vbt  # type: ignore

                license_note = getattr(vbt, "__license__", "check package metadata")
            except Exception:  # noqa: BLE001
                pass
        return engine_status_payload(
            name=NAME,
            module="backtesting",
            integration_mode="pip_dependency",
            license_id="verify_in_package",
            installed=installed,
            runnable=runnable,
            github_owner=OWNER,
            github_repo=REPO,
            docs=DOCS,
            detail={
                "pip_version": pip.get("version"),
                "reference_clone": clone,
                "license_note": license_note,
                "primary_for": ["forecast", "investment_maneuvers"],
                "wired_to": [
                    "terminal/quant/backtest (metadata overlay)",
                    "forecast ensemble overlays",
                    "maneuver signal_meta.trading_engines",
                ],
            },
            error=pip.get("error"),
        )

    def capabilities(self) -> dict[str, Any]:
        return {
            "name": NAME,
            "module": "backtesting",
            "actions": ["sample_momentum_backtest", "probe_import"],
        }

    def action(self, **kwargs: Any) -> dict[str, Any]:
        kind = (kwargs.get("kind") or "sample_momentum_backtest").lower()
        if kind == "probe_import":
            pip = probe_import("vectorbt", "vectorbt")
            return {"ok": pip.get("importable", False), "probe": pip}

        try:
            from app.services.trading_engines.backtest.vectorbt_engine import run_vectorbt_momentum
            from app.services.trading_engines.runtime.prices import resolve_close_prices

            prices = resolve_close_prices(kwargs)
            lookback = int(kwargs.get("lookback") or 10)
            result = run_vectorbt_momentum(prices, lookback=lookback)
            return {"ok": True, "result": result}
        except ImportError as exc:
            return {"ok": False, "error": f"vectorbt_not_installed: {exc}"}
        except ValueError:
            return {"ok": False, "error": "нет данных"}
        except Exception:  # noqa: BLE001
            return {"ok": False, "error": "нет данных"}
