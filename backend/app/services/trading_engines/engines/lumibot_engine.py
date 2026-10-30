"""Lumibot — multi-asset paper backtest adapter (Module 5)."""
from __future__ import annotations

from typing import Any

from app.services.trading_engines.base import engine_status_payload
from app.services.trading_engines.probes import clone_status, probe_import

NAME = "lumibot"
OWNER = "Lumiwealth"
REPO = "lumibot"
DOCS = "https://lumibot.lumiwealth.com/"


class LumibotEngine:
    name = NAME

    def status(self) -> dict[str, Any]:
        pip = probe_import("lumibot", "lumibot")
        clone = clone_status("lumibot")
        return engine_status_payload(
            name=NAME,
            module="manual_order",
            integration_mode="library_verify_license",
            license_id="verify_before_use",
            installed=True,
            runnable=True,
            github_owner=OWNER,
            github_repo=REPO,
            docs=DOCS,
            detail={
                "pip_probe": pip,
                "package_importable": pip.get("importable", False),
                "reference_clone": clone,
                "activate": "pip install lumibot (requirements-trading-engines.txt)",
                "moex_support": False,
                "note": (
                    "Same-code-path momentum backtest via terminal quant. "
                    "Lumibot live broker is not the Apex order router."
                ),
                "wired_to": "terminal_platform.quant.backtest.run_backtest",
            },
            error=None,
        )

    def capabilities(self) -> dict[str, Any]:
        return {
            "name": NAME,
            "module": "manual_order",
            "actions": ["probe_import", "sample_backtest", "emit_intent"],
        }

    def action(self, **kwargs: Any) -> dict[str, Any]:
        kind = (kwargs.get("kind") or "sample_backtest").lower()
        pip = probe_import("lumibot", "lumibot")
        if kind == "probe_import":
            return {"ok": pip.get("importable", False), "probe": pip}

        from app.services.terminal_platform.quant.backtest import run_backtest
        from app.services.terminal_platform.quant.models import BacktestConfig, PriceSeries
        from app.services.trading_engines.runtime.prices import resolve_close_prices

        try:
            prices = resolve_close_prices(kwargs)
            result = run_backtest(
                PriceSeries(values=prices, symbol="LUMIBOT"),
                BacktestConfig(signal_lookback=10),
            )
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        payload = {
            "ok": True,
            "lumibot_importable": bool(pip.get("importable")),
            "lumibot_version": pip.get("version"),
            "result": {
                "total_return": result.total_return,
                "sharpe": result.sharpe,
                "max_drawdown": result.max_drawdown,
                "n_trades": result.n_trades,
                "metadata": result.metadata,
            },
        }
        if kind == "emit_intent":
            from app.services.trading_engines.runtime.intent import intent_from_position

            last = int(result.signals[-1]) if result.signals else 0
            payload["gate"] = intent_from_position(
                source=NAME,
                symbol=str(kwargs.get("symbol") or "SPY"),
                last_position=last,
                confidence=0.5,
                metrics=payload["result"],
            )
        return payload
