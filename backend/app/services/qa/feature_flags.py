"""In-memory + JSON feature flags. Override in tests; admin can flip globals."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

_DEFAULTS: dict[str, bool] = {
    "qa_shadow_mode": False,
    "qa_new_risk_path": False,
    "qa_new_forecast_path": False,
    "qa_catalog": True,
    "qa_forecast_log": True,
    "qa_portfolio_book": True,
    "qa_venue_adapters": True,
    "qa_event_bus": True,
    "qa_returns": True,
    "qa_risk_engine": True,
    "qa_risk_gate": True,
    "qa_forecast_core": True,
    "qa_model_risk": True,
    "qa_market_regime": True,
    "qa_stress_library": True,
    "qa_concentration": True,
    "qa_behavior": True,
    "qa_explanations": True,
    "qa_explanations_llm": False,
    "qa_explanations_trace_bodies": False,
    "qa_report": True,
    "qa_ui_shell": True,
    "qa_act_desk": True,
    "qa_act_live": False,
    "qa_maneuvers_user_rules": False,
    "qa_act_model_profile": False,
    "qa_display_unlicensed": False,
    "qa_investment_profile": True,
    "qa_target_portfolio": True,
    "qa_maneuver_generator": True,
    "qa_maneuver_history": True,
    "qa_maneuver_cycle": True,
    "qa_maneuver_control": True,
    "qa_order_machine": True,
    "qa_moex_crypto": False,
    "qa_partners": False,
    "qa_partner_ads": False,
    "qa_subscription": True,
    "qa_subscription_notice": False,
    "qa_payment": False,
    "qa_bot_core": True,
    "qa_ops_observe": True,
    "qa_perf_budget": True,
    "qa_waitlist": True,
    "qa_preorder": False,
    "qa_public_accuracy": True,
    "qa_product_analytics": True,
    "qa_founder_metrics": True,
    "qa_experiments": False,
    "qa_beta_admin": True,
    "qa_subject_rights": True,
    "qa_support": True,
    "qa_qualified_docs": False,
    "qa_privacy": True,
    "qa_onboarding": True,
    "qa_sandbox": False,
    "qa_personal_limits": False,
    "qa_calendar": False,
    "qa_digest": False,
    "qa_ops_observe": True,
    "qa_perf_budget": True,
    "qa_k4_risk_attribution": True,
    "qa_k1_benchmark": True,
    "qa_position_liquidity": True,
    "qa_bonds": True,
    "qa_payouts": True,
    "qa_factor_lens": True,
    "qa_k6_fund_report": True,
    "qa_fund_lookthrough": True,
    "qa_59_decisions": True,
    "qa_62_costs": True,
    "qa_60_pretrade": True,
    "qa_futures_risk": True,
    "qa_key_rate": True,
    "qa_goals": True,
    "qa_futures_market": True,
    # K3 RF tax demo — [ЮРИСТ]; off until lawyer confirms methodology UI.
    "qa_tax_rf": False,
    "qa_k3_tax": True,  # [ЮРИСТ] demo/paper only until methodology confirmed
    "qa_decision_core": False,
    "qa_brain_weight_shadow": True,
    "qa_brain_weights_live": False,
}

_lock = threading.Lock()
_store: dict[str, bool] = dict(_DEFAULTS)
_user_store: dict[str, dict[str, bool]] = {}
_path: Path | None = None


def configure(path: Path | None = None) -> None:
    global _path
    _path = path
    if path and path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        with _lock:
            _store.update({k: bool(v) for k, v in (data.get("global") or {}).items()})
            _user_store.clear()
            for uid, flags in (data.get("users") or {}).items():
                _user_store[str(uid)] = {k: bool(v) for k, v in flags.items()}


def reset_for_tests() -> None:
    with _lock:
        _store.clear()
        _store.update(_DEFAULTS)
        _user_store.clear()
    for key in _DEFAULTS:
        os.environ.pop(f"FF_{key.upper()}", None)


def _persist() -> None:
    if _path is None:
        return
    _path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"global": dict(_store), "users": {k: dict(v) for k, v in _user_store.items()}}
    _path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def is_enabled(name: str, *, user_id: str | None = None) -> bool:
    env = os.environ.get(f"FF_{name.upper()}")
    if env is not None:
        return env.strip().lower() in {"1", "true", "yes", "on"}
    with _lock:
        if user_id and user_id in _user_store and name in _user_store[user_id]:
            return _user_store[user_id][name]
        return bool(_store.get(name, False))


def set_global(name: str, enabled: bool) -> None:
    with _lock:
        _store[name] = bool(enabled)
        _persist()


def set_user(name: str, enabled: bool, user_id: str) -> None:
    with _lock:
        _user_store.setdefault(user_id, {})[name] = bool(enabled)
        _persist()


def snapshot() -> dict[str, Any]:
    with _lock:
        return {
            "global": dict(_store),
            "users": {k: dict(v) for k, v in _user_store.items()},
            "known": sorted(_DEFAULTS),
        }
