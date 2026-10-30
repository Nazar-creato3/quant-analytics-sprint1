"""Goal probability for a session user (prompt K5)."""
from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from time import perf_counter
from typing import Any

import numpy as np

from app.services.explanations.service import filter_wording
from app.services.goals.math import bootstrap_terminal, mapie_terminal_band
from app.services.qa.feature_flags import is_enabled
from app.services.risk_engine.service import _holdings_from_book, _nav_rub

STORE = Path(__file__).resolve().parents[4] / "backend" / "data" / "goals_shadow"
SEED = 63


def _daily_returns(holdings: list[dict[str, Any]]) -> np.ndarray:
    # Demo books often lack a long NAV series; use a conservative equity-like
    # sample from holdings vols when present, else empty.
    vols = []
    for h in holdings:
        v = h.get("vol") or h.get("sigma")
        if v is not None:
            vols.append(float(v) / (252.0 ** 0.5))
    if not vols:
        return np.array([])
    sigma = float(np.mean(vols))
    rng = np.random.default_rng(SEED)
    return rng.normal(0.0003, max(sigma, 1e-4), size=252)


def _days_to(target_date: str) -> int:
    try:
        end = date.fromisoformat(target_date[:10])
    except ValueError:
        return 0
    today = datetime.now(UTC).date()
    return max(int((end - today).days * 252 / 365), 1)


def last_goal_inputs(user_id: str) -> dict[str, Any] | None:
    path = STORE / f"{user_id}.json"
    if not path.is_file():
        return None
    try:
        row = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return row if isinstance(row, dict) else None


def _prev_prob(user_id: str) -> float | None:
    row = last_goal_inputs(user_id)
    if not row or row.get("probability") is None:
        return None
    try:
        return float(row["probability"])
    except (TypeError, ValueError):
        return None


def _save_prob(user_id: str, payload: dict[str, Any]) -> None:
    STORE.mkdir(parents=True, exist_ok=True)
    (STORE / f"{user_id}.json").write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _as_decimal(value: Decimal | float | int | str) -> Decimal:
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("invalid money amount") from exc


def explain_goal(
    user_id: str,
    *,
    target_amount: Decimal | float | int | str,
    target_date: str,
    monthly_contrib: Decimal | float | int | str = 0,
    mode: str = "paper",
) -> dict[str, Any]:
    started = perf_counter()
    caption = "расчёт по прошлым данным, не обещание результата"
    if filter_wording(caption):
        caption = "нет данных"
    if not is_enabled("qa_goals"):
        return {"data_status": "нет данных", "reason": "нет данных", "caption": caption}
    amount = _as_decimal(target_amount)
    contrib = _as_decimal(monthly_contrib)
    holdings = _holdings_from_book(user_id, mode)
    nav = _nav_rub(holdings) or 0.0
    days = _days_to(target_date)
    rets = _daily_returns(holdings)
    if float(nav) <= 0.0 or rets.size < 2:
        return {
            "data_status": "нет данных",
            "probability": None,
            "p05": None,
            "p95": None,
            "nav": nav,
            "target_amount": format(amount, "f"),
            "target_date": target_date,
            "caption": caption,
            "days": days,
        }
    boot = bootstrap_terminal(
        rets,
        start=float(nav),
        monthly_contrib=float(contrib),
        days=days,
        target=float(amount),
        seed=SEED,
    )
    band = mapie_terminal_band(rets, start=float(nav), days=days)
    prev = _prev_prob(user_id)
    p = boot.get("probability")
    notify = False
    if isinstance(p, float) and prev is not None and abs(p - prev) > 0.10:
        notify = True
    amount_out = format(amount, "f")
    contrib_out = format(contrib, "f")
    out = {
        "data_status": boot.get("status"),
        "probability": p,
        "p05": boot.get("p05"),
        "p95": boot.get("p95"),
        "mapie": band,
        "seed": SEED,
        "days": days,
        "nav": nav,
        "target_amount": amount_out,
        "target_date": target_date,
        "monthly_contrib": contrib_out,
        "caption": caption,
        "notify_10pp": notify,
        "methodology": "/methodology/goals",
        "elapsed_ms": round((perf_counter() - started) * 1000.0, 3),
    }
    if isinstance(p, float):
        _save_prob(
            user_id,
            {
                "probability": p,
                "as_of": datetime.now(UTC).isoformat(),
                "target_amount": amount_out,
                "target_date": target_date,
                "monthly_contrib": contrib_out,
                "mode": mode,
            },
        )
    return out

