"""User risk settings: the limits a person sets for their own book.

This is not an investment profile in the sense of 39-FZ art. 6.1 / Bank of
Russia 5014-U: the platform does not ask for age, income, expenses, savings
or education and does not assess suitability. Those fields are neither
accepted nor stored, and legacy values are never returned (see
LEGACY_PERSONAL_FIELDS and scripts/scrub_profile_personal_fields.py).
"""
from __future__ import annotations

import hashlib
import json

from app.services.qa import durable_store
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from threading import Lock
from typing import Any
from uuid import uuid4

from app.services.qa.feature_flags import is_enabled

MODEL_VERSION = "investment_profile.v1"
REVIEW_DAYS = 365
LARGE_FLOW_NAV_FRAC = Decimal("0.20")

# Conservative / moderate / aggressive → ES, VaR, max drawdown (fractions).
# Methodology: docs/methodology/profile-limits.md
BAND_LIMITS: dict[str, dict[str, str]] = {
    "conservative": {"var_95": "0.020", "es_975": "0.030", "max_drawdown": "0.100"},
    "moderate": {"var_95": "0.050", "es_975": "0.070", "max_drawdown": "0.150"},
    "aggressive": {"var_95": "0.100", "es_975": "0.140", "max_drawdown": "0.250"},
}

_CORE = ("horizon", "risk_tolerance", "expected_return", "max_position_pct", "max_crisis_loss_pct")
# Fields of a regulated investment profile. Never collected (see module docstring).
LEGACY_PERSONAL_FIELDS = ("age", "income_12m", "expenses_12m", "savings", "education", "complete_5014u", "source_5014u")

_lock = Lock()
# Durable: profiles survive restarts and are shared by all workers (one questionnaire per user).
_STORE_PROFILES = "investment_profiles"
_STORE_HISTORY = "investment_profile_history"


def reset() -> None:
    with _lock:
        durable_store.clear(_STORE_PROFILES)
        durable_store.clear(_STORE_HISTORY)


def save_profile(user_id: str, answers: dict[str, Any], *, actor: str = "user") -> dict[str, Any]:
    if not is_enabled("qa_investment_profile"):
        raise RuntimeError("qa_investment_profile off")
    if not user_id:
        raise ValueError("user_id required")
    missing_core = [k for k in ("horizon", "risk_tolerance", "max_position_pct", "max_crisis_loss_pct") if not answers.get(k)]
    if missing_core:
        raise ValueError(f"profile incomplete: {missing_core}")
    band = str(answers["risk_tolerance"]).strip().lower()
    if band not in BAND_LIMITS:
        raise ValueError("risk_tolerance must be conservative, moderate or aggressive")
    qualified = _truthy(answers.get("qualified_investor"))
    docs_ok = False
    if qualified and is_enabled("qa_qualified_docs"):
        docs_ok = _truthy(answers.get("qualified_docs_verified"))
    elif qualified:
        docs_ok = False
    row = {
        "id": str(uuid4()),
        "user_id": user_id,
        "schema_version": 1,
        "model_version": MODEL_VERSION,
        "horizon": str(answers["horizon"]),
        "risk_tolerance": band,
        "expected_return": str(answers.get("expected_return") or ""),
        "max_position_pct": str(answers["max_position_pct"]),
        "max_crisis_loss_pct": str(answers["max_crisis_loss_pct"]),
        "banned_tickers": _list(answers.get("banned_tickers")),
        "allowed_hedge_tickers": _list(answers.get("allowed_hedge_tickers")),
        "banned_sectors": _list(answers.get("banned_sectors")),
        "banned_issuers": _list(answers.get("banned_issuers")),
        "max_sector_pct": str(answers.get("max_sector_pct") or ""),
        "currencies": _list(answers.get("currencies")),
        "account_type": str(answers.get("account_type") or "regular"),
        "iis_type": str(answers.get("iis_type") or ""),
        "liquidity_days": str(answers.get("liquidity_days") or ""),
        "tax_pref": str(answers.get("tax_pref") or ""),
        "qualified_investor": qualified,
        "qualified_docs_verified": docs_ok,
        "purpose": str(answers.get("purpose") or "учёт капитала"),
        "as_of": _now(),
        "actor": actor,
        "source": "investment_profile",
    }
    row["limits"] = limits_from_profile(row)
    row["answers_hash"] = hashlib.sha256(
        json.dumps({k: row[k] for k in _CORE}, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    with _lock:
        prev = durable_store.load(_STORE_PROFILES).get(user_id)
        version = 1 if prev is None else int(prev.get("version") or 1) + 1
        row["version"] = version
        hist_item = {
            "version": version,
            "at": row["as_of"],
            "actor": actor,
            "answers_hash": row["answers_hash"],
            "model_version": MODEL_VERSION,
            "id": row["id"],
            "prev_id": (prev or {}).get("id"),
        }
        hist = list(durable_store.load(_STORE_HISTORY).get(user_id) or [])
        hist.append(hist_item)
        durable_store.update(_STORE_HISTORY, user_id, hist[-50:])
        durable_store.update(_STORE_PROFILES, user_id, row)
    if is_enabled("qa_personal_limits"):
        _push_personal_limits(user_id, row["limits"], row)
    return dict(row)


def get_profile(user_id: str) -> dict[str, Any] | None:
    if not is_enabled("qa_investment_profile"):
        raise RuntimeError("qa_investment_profile off")
    with _lock:
        found = durable_store.load(_STORE_PROFILES).get(user_id)
        return strip_legacy(found) if found else None


def get_raw_profile(user_id: str) -> dict[str, Any] | None:
    """Everything stored for the user, legacy fields included (152-FZ art. 14 access requests)."""
    with _lock:
        found = durable_store.load(_STORE_PROFILES).get(user_id)
        return dict(found) if found else None


def scrub_personal_fields() -> int:
    """Remove legacy regulated-profile fields from every stored row. Returns rows changed."""
    changed = 0
    with _lock:
        rows = durable_store.load(_STORE_PROFILES)
        for uid, row in list(rows.items()):
            if any(k in row for k in LEGACY_PERSONAL_FIELDS):
                durable_store.update(_STORE_PROFILES, uid, strip_legacy(row))
                changed += 1
    return changed


def strip_legacy(row: dict[str, Any]) -> dict[str, Any]:
    """Copy without regulated-profile fields that older versions stored."""
    return {k: v for k, v in row.items() if k not in LEGACY_PERSONAL_FIELDS}


def history_for(user_id: str) -> list[dict[str, Any]]:
    if not is_enabled("qa_investment_profile"):
        raise RuntimeError("qa_investment_profile off")
    with _lock:
        return [dict(x) for x in durable_store.load(_STORE_HISTORY).get(user_id) or []]


def erase_user(user_id: str) -> None:
    with _lock:
        durable_store.update(_STORE_PROFILES, user_id, None)
        durable_store.update(_STORE_HISTORY, user_id, None)


def limits_from_profile(profile: dict[str, Any]) -> dict[str, str]:
    band = str(profile.get("risk_tolerance") or "moderate")
    base = dict(BAND_LIMITS.get(band) or BAND_LIMITS["moderate"])
    crisis = str(profile.get("max_crisis_loss_pct") or "")
    pos = str(profile.get("max_position_pct") or "")
    if crisis:
        base["crisis_loss"] = crisis
    if pos:
        base["max_position_pct"] = pos
        base["concentration"] = pos
    return base


def warnings_vs_portfolio(user_id: str, *, mode: str = "paper") -> list[dict[str, str]]:
    profile = get_profile(user_id)
    if profile is None:
        return [{"code": "no_profile", "text": "лимиты риска не заданы"}]
    from app.services.risk_engine.service import compute_risk_for_user

    risk = compute_risk_for_user(user_id, mode)
    limits = profile.get("limits") or limits_from_profile(profile)
    out: list[dict[str, str]] = []
    var_lim = _dec(limits.get("var_95"))
    var_now = risk.get("var_95")
    if var_lim is not None and var_now is not None:
        try:
            if Decimal(str(var_now)) > var_lim:
                out.append(
                    {
                        "code": "var_above_profile",
                        "text": "допустимый риск профиля ниже фактического VaR 95% текущего портфеля",
                    }
                )
        except (InvalidOperation, TypeError, ValueError):
            pass
    dd_lim = _dec(limits.get("max_drawdown"))
    dd_now = risk.get("max_drawdown")
    if dd_lim is not None and dd_now is not None:
        try:
            if Decimal(str(dd_now)) > dd_lim:
                out.append(
                    {
                        "code": "drawdown_above_profile",
                        "text": "допустимая просадка профиля ниже фактической просадки портфеля",
                    }
                )
        except (InvalidOperation, TypeError, ValueError):
            pass
    if str(profile.get("account_type") or "").startswith("iis"):
        if _horizon_years(profile.get("horizon")) is not None and _horizon_years(profile.get("horizon")) < 3:
            out.append(
                {
                    "code": "iis_horizon",
                    "text": "горизонт короче трёх лет при типе счёта ИИС — льготы ИИС рассчитаны на более длинный срок",
                }
            )
    return out


def due_for_review(user_id: str, *, mode: str = "paper", now: datetime | None = None) -> dict[str, Any]:
    profile = get_profile(user_id)
    if profile is None:
        return {"due": True, "reason": "нет профиля"}
    clock = now or datetime.now(timezone.utc)
    as_of = datetime.fromisoformat(str(profile["as_of"]).replace("Z", "+00:00"))
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=timezone.utc)
    if clock - as_of >= timedelta(days=REVIEW_DAYS):
        return {"due": True, "reason": f"истёк срок {REVIEW_DAYS} дней"}
    if _large_flow(user_id, mode, profile):
        return {"due": True, "reason": "крупное пополнение или вывод"}
    return {"due": False, "reason": ""}


def _large_flow(user_id: str, mode: str, profile: dict[str, Any]) -> bool:
    from app.services.portfolio_book.store import get_book

    as_of = str(profile.get("as_of") or "")
    nav_hint = Decimal("0")
    try:
        from app.services.concentration.service import analyze_portfolio

        conc = analyze_portfolio(user_id=user_id, mode=mode)
        nav_hint = _dec(conc.get("nav_rub")) or Decimal("0")
    except Exception:
        nav_hint = Decimal("0")
    if nav_hint <= 0:
        return False
    thresh = nav_hint * LARGE_FLOW_NAV_FRAC
    book = get_book()
    try:
        rows = book.transactions(user_id=user_id, mode=mode)  # type: ignore[attr-defined]
    except Exception:
        return False
    for tx in rows:
        when = str(getattr(tx, "event_time", "") or "")
        if when and as_of and when < as_of:
            continue
        kind = str(getattr(tx, "kind", "") or "")
        if kind not in {"deposit", "withdraw", "cash"}:
            continue
        amt = abs(_dec(getattr(tx, "amount", None)) or Decimal("0"))
        if amt >= thresh:
            return True
    return False


def _push_personal_limits(user_id: str, limits: dict[str, str], profile: dict[str, Any]) -> None:
    from app.services.personal_limits.service import set_limits

    try:
        set_limits(
            user_id=user_id,
            crisis_loss=_float(limits.get("crisis_loss") or profile.get("max_crisis_loss_pct")),
            concentration=_float(limits.get("concentration") or profile.get("max_position_pct")),
            leverage=None,
            drawdown=_float(limits.get("max_drawdown")),
        )
    except Exception:
        pass


def _list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    return [p.strip() for p in str(value).split(",") if p.strip()]


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "да"}


def _dec(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _float(value: Any) -> float | None:
    d = _dec(value)
    return float(d) if d is not None else None


def _horizon_years(raw: Any) -> float | None:
    text = str(raw or "").strip().lower()
    if text.endswith("y"):
        return _float(text[:-1])
    if text.endswith("year") or text.endswith("лет") or text.endswith("года"):
        return _float("".join(ch for ch in text if ch.isdigit() or ch == "."))
    return _float(text)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
