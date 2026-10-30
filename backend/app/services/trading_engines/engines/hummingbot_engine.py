"""Hummingbot — grid-bot pattern via Apex grid math (Module 3)."""
from __future__ import annotations

from typing import Any

from app.services.trading_engines.base import engine_status_payload
from app.services.trading_engines.probes import clone_status

NAME = "hummingbot"
OWNER = "hummingbot"
REPO = "hummingbot"
DOCS = "https://hummingbot.org/"


class HummingbotEngine:
    name = NAME

    def status(self) -> dict[str, Any]:
        clone = clone_status("hummingbot")
        return engine_status_payload(
            name=NAME,
            module="grid_bots",
            integration_mode="reference_apache",
            license_id="Apache-2.0",
            installed=True,
            runnable=True,
            github_owner=OWNER,
            github_repo=REPO,
            docs=DOCS,
            detail={
                "reference_clone": clone,
                "clone_present": clone.get("installed", False),
                "note": (
                    "Hummingbot is not embedded. Grid plans use Apex auto-calibrate "
                    "(same arithmetic/geometric levels as live grid bots)."
                ),
                "wired_to": "app.services.grid (auto_calibrate + levels)",
            },
            error=None,
        )

    def capabilities(self) -> dict[str, Any]:
        return {
            "name": NAME,
            "module": "grid_bots",
            "actions": ["clone_status", "propose_grid", "emit_intent"],
        }

    def action(self, **kwargs: Any) -> dict[str, Any]:
        kind = (kwargs.get("kind") or "propose_grid").lower()
        if kind == "clone_status":
            clone = clone_status("hummingbot")
            return {"ok": True, "clone": clone, "embedded": False}

        from app.services.trading_engines.runtime.grid_plan import propose_grid
        from app.services.trading_engines.runtime.prices import resolve_close_prices

        payload = kwargs.get("payload") if isinstance(kwargs.get("payload"), dict) else {}
        mid = kwargs.get("mid") if kwargs.get("mid") is not None else payload.get("mid")
        try:
            mid_f = float(mid) if mid is not None else None
        except (TypeError, ValueError):
            mid_f = None
        # GA16-311: do not invent capital=10000 when the caller omitted it.
        cap_raw = kwargs.get("capital") if "capital" in kwargs else payload.get("capital")
        if cap_raw is None:
            return {"ok": False, "error": "Не указан капитал для сетки."}
        try:
            capital = float(cap_raw)
        except (TypeError, ValueError):
            return {"ok": False, "error": "Некорректный капитал для сетки."}
        if capital <= 0:
            return {"ok": False, "error": "Капитал для сетки должен быть больше нуля."}
        try:
            plan = propose_grid(
                symbol=str(kwargs.get("symbol") or payload.get("symbol") or "BTC-USD"),
                mid=mid_f,
                capital=capital,
                closes=resolve_close_prices(kwargs),
                risk_level=str(kwargs.get("risk_level") or payload.get("risk_level") or "medium"),
            )
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": "Не удалось построить сетку."}
        if kind != "emit_intent":
            return plan

        from app.services.trading_engines.grid.freqtrade_bridge import write_signal_state
        from app.services.trading_engines.runtime.intent import EngineIntent, gate_engine_intent

        gated = gate_engine_intent(
            EngineIntent(
                source=NAME,
                symbol=str(plan.get("symbol") or "BTC-USD"),
                side="grid",
                confidence=0.5,
                suggested_weight=0.05,
                rationale="hummingbot-style grid plan via Apex levels",
                metrics={"num_levels": plan.get("num_levels"), "grid_type": plan.get("grid_type")},
            )
        )
        if gated.get("approved"):
            write_signal_state(
                {
                    "symbol": plan.get("symbol"),
                    "direction": "grid",
                    "target_weight": gated.get("capped_weight"),
                    "source": "hummingbot_pattern",
                    "lower": plan.get("lower"),
                    "upper": plan.get("upper"),
                }
            )
        return {**plan, "gate": gated, "execution": "none"}
