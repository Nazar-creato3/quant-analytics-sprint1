"""FinRL — optional RL overlay for forecast (Module 4)."""
from __future__ import annotations

from typing import Any

from app.services.trading_engines.base import engine_status_payload
from app.services.trading_engines.probes import clone_status, probe_import

NAME = "finrl"
OWNER = "AI4Finance-Foundation"
REPO = "FinRL"
DOCS = "https://github.com/AI4Finance-Foundation/FinRL"


class FinrlEngine:
    name = NAME

    def status(self) -> dict[str, Any]:
        pip = probe_import("finrl", "finrl")
        clone = clone_status("FinRL")
        return engine_status_payload(
            name=NAME,
            module="forecast_ensemble",
            integration_mode="pip_optional",
            license_id="MIT",
            installed=True,
            runnable=True,
            github_owner=OWNER,
            github_repo=REPO,
            docs=DOCS,
            detail={
                "pip_probe": pip,
                "package_importable": pip.get("importable", False),
                "reference_clone": clone,
                "activate": "pip install finrl (requirements-trading-engines.txt)",
                "priority": "low",
                "note": (
                    "Train with action kind=train (saves models/finrl/{symbol}.json). "
                    "policy_score uses the trained file; pip finrl is optional."
                ),
                "wired_to": ["forecast ensemble overlays", "maneuver signal_meta.trading_engines", "weekly forecast retrain"],
                "model_dir": "backend/models/finrl",
            },
            error=None,
        )

    def capabilities(self) -> dict[str, Any]:
        return {
            "name": NAME,
            "module": "forecast_ensemble",
            "actions": ["probe_import", "policy_score", "train", "emit_intent"],
        }

    def action(self, **kwargs: Any) -> dict[str, Any]:
        kind = (kwargs.get("kind") or "policy_score").lower()
        pip = probe_import("finrl", "finrl")
        if kind == "probe_import":
            return {"ok": pip.get("importable", False), "probe": pip}

        from app.services.trading_engines.runtime.prices import resolve_close_prices

        symbol = str(kwargs.get("symbol") or "SPY")
        prices = resolve_close_prices(kwargs)
        if kind == "train":
            from app.services.trading_engines.runtime.finrl_agent import train_and_save

            episodes = int(kwargs.get("episodes") or 24)
            trained = train_and_save(prices, symbol=symbol, episodes=episodes)
            if not trained.get("ok"):
                return trained
            from app.services.trading_engines.runtime.finrl_policy import policy_score

            scored = policy_score(prices, symbol=symbol)
            return {**trained, "score": scored}

        from app.services.trading_engines.runtime.finrl_policy import policy_score

        score = policy_score(prices, symbol=symbol)
        if kind != "emit_intent":
            return score
        from app.services.trading_engines.runtime.intent import intent_from_position

        return {
            **score,
            "gate": intent_from_position(
                source=NAME,
                symbol=symbol,
                last_position=int(score.get("direction") or 0),
                confidence=min(0.65, abs(float(score.get("score") or 0.0)) / 3.0),
                metrics={"mode": score.get("mode"), "trained": score.get("trained")},
            ),
        }
