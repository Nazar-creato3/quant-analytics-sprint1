"""TradingAgents — multi-agent debate pattern (Module 4)."""
from __future__ import annotations

from typing import Any

from app.services.trading_engines.base import engine_status_payload
from app.services.trading_engines.probes import clone_status, probe_import

NAME = "tradingagents"
OWNER = "TauricResearch"
REPO = "TradingAgents"
DOCS = "https://github.com/TauricResearch/TradingAgents"


class TradingAgentsEngine:
    name = NAME

    def status(self) -> dict[str, Any]:
        clone = clone_status("tradingagents")
        # Pattern implemented in maneuver_debate — clone optional for debate dry-run
        pip = probe_import("tradingagents", "tradingagents")
        debate_ok = True
        try:
            from app.services.risk.maneuver_debate import debate_maneuvers_dry_run

            debate_ok = bool(debate_maneuvers_dry_run([{"ticker": "PROBE", "confidence": 0.7}]).get("ok"))
        except Exception:  # noqa: BLE001
            debate_ok = False
        installed = clone.get("installed") or pip.get("available", False) or debate_ok
        runnable = clone.get("installed") or debate_ok
        err = None
        if not clone.get("installed"):
            err = None if debate_ok else "clone missing; debate pattern unavailable"
        return engine_status_payload(
            name=NAME,
            module="investment_maneuvers+chat",
            integration_mode="architectural_pattern",
            license_id="verify_before_code_use",
            installed=installed,
            runnable=runnable,
            github_owner=OWNER,
            github_repo=REPO,
            docs=DOCS,
            detail={
                "reference_clone": clone,
                "pattern_impl": "app.services.risk.maneuver_debate",
                "pip_probe": pip,
                "debate_dry_run_ok": debate_ok,
                "note": "Разбор манёвра по ролям доступен, когда подключена языковая модель.",
            },
            error=err,
        )

    def capabilities(self) -> dict[str, Any]:
        return {
            "name": NAME,
            "module": "investment_maneuvers+chat",
            "actions": ["clone_status", "debate_dry_run"],
        }

    def action(self, **kwargs: Any) -> dict[str, Any]:
        kind = (kwargs.get("kind") or "clone_status").lower()
        if kind == "debate_dry_run":
            from app.services.risk.maneuver_debate import debate_maneuvers_dry_run

            candidates = kwargs.get("candidates") or [
                {"ticker": "AAPL", "direction": "long", "confidence": 0.72, "rationale": "momentum"},
                {"ticker": "MSFT", "direction": "long", "confidence": 0.68, "rationale": "earnings"},
            ]
            return debate_maneuvers_dry_run(candidates)
        clone = clone_status("tradingagents")
        return {"ok": clone.get("installed", False), "clone": clone}
