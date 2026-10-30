"""Portfolio key-rate scenarios."""
from __future__ import annotations

from pathlib import Path
from time import perf_counter
from typing import Any

from app.services.explanations.service import filter_wording
from app.services.key_rate.math import (
    bond_price_change_pct,
    deposit_income,
    equity_return_from_rate_beta,
    floater_income,
    floater_price_change_pct,
)
from app.services.qa.feature_flags import is_enabled
from app.services.risk_engine.service import _holdings_from_book, _nav_rub, _value_rub

REPO = Path(__file__).resolve().parents[4]


def _meetings_path() -> Path:
    # Repo checkout (dev/tests) or the bind-mounted ./data inside the container.
    for cand in (REPO / "data" / "cbr" / "meetings.yaml", Path("/app/data/cbr/meetings.yaml")):
        if cand.is_file():
            return cand
    return REPO / "data" / "cbr" / "meetings.yaml"


MEETINGS = _meetings_path()

# Money-market funds: price grows with the overnight rate, so they behave like cash.
MONEY_MARKET = {"LQDT", "TMON", "SBMM", "AKMM", "AMNR", "TPAY", "SCLI", "GOLD@", "BCSD"}
# A rate move this large came with a market shock (28.02.2022) — it would swamp the estimate.
_SHOCK_BP = 500
_MIN_EPISODES = 4


def _parse_meetings() -> dict[str, Any]:
    if not MEETINGS.is_file():
        return {"source": None, "episodes": [], "upcoming": []}
    text = MEETINGS.read_text(encoding="utf-8")
    episodes: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    source = None
    current_rate: float | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("source:"):
            source = line.split(":", 1)[1].strip().strip('"')
        elif line.startswith("- date:"):
            if current:
                episodes.append(current)
            current = {"date": line.split(":", 1)[1].strip().strip('"')}
        elif line.startswith("shift_bp:") and current:
            current["shift_bp"] = int(line.split(":", 1)[1].strip())
        elif line.startswith("note:") and current:
            current["note"] = line.split(":", 1)[1].strip().strip('"')
        elif line.startswith("current_rate_pct:"):
            try:
                current_rate = float(line.split(":", 1)[1].strip())
            except ValueError:
                pass
    if current:
        episodes.append(current)
    return {"source": source, "episodes": episodes, "upcoming": [], "current_rate_pct": current_rate}


def current_key_rate(max_age_days: int = 60) -> float | None:
    """Key rate from data/cbr/meetings.yaml (decimal), only while that file is fresh.

    A stale file means nobody has checked the latest decision — better no income
    line than a wrong one.
    """
    from datetime import date as _date

    text = MEETINGS.read_text(encoding="utf-8") if MEETINGS.is_file() else ""
    pct = as_of = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("current_rate_pct:"):
            pct = line.split(":", 1)[1].strip()
        elif line.startswith("current_rate_as_of:"):
            as_of = line.split(":", 1)[1].strip().strip('"')
    try:
        if pct is None or as_of is None or (_date.today() - _date.fromisoformat(as_of)).days > max_age_days:
            return None
        return float(pct) / 100.0
    except ValueError:
        return None


def rate_beta(ticker: str) -> tuple[float | None, int]:
    """Past reaction of the stock to Bank of Russia decisions: return per unit of rate change.

    OLS through the origin over decision days (close-to-close return of that day
    against the rate change in decimal), shocks above 500 bp left out.
    Returns (beta, number of decisions used).
    """
    from datetime import date as _date

    from app.services.price_history import service as history

    rets = history.dated_returns(ticker)
    if not rets:
        return None, 0
    num = den = 0.0
    used = 0
    for ep in _parse_meetings().get("episodes") or []:
        shift = int(ep.get("shift_bp") or 0)
        if not shift or abs(shift) > _SHOCK_BP:
            continue
        try:
            day = _date.fromisoformat(str(ep["date"]))
        except (KeyError, ValueError):
            continue
        r = rets.get(day)
        if r is None:
            continue
        dy = shift / 10_000.0
        num += r * dy
        den += dy * dy
        used += 1
    if used < _MIN_EPISODES or den <= 0:
        return None, used
    return num / den, used


def auto_meta(holdings: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Inputs the scenario needs, derived from the price history (no manual meta)."""
    from app.services.price_history import service as history

    out: dict[str, dict[str, Any]] = {}
    for h in holdings:
        ticker = str(h.get("ticker") or "").upper()
        info = history.info(ticker)
        row: dict[str, Any] = {}
        if ticker in MONEY_MARKET:
            row["asset_class"] = "deposit"
        elif info.get("market") == "bonds":
            dur_days = info.get("duration_days")
            ytm = info.get("yield")
            try:
                mac = float(dur_days) / 365.0
                y = float(ytm) / 100.0 if ytm not in (None, "") else 0.0
                mod = mac / (1.0 + y)
                row.update(asset_class="bond_fixed", mod_duration=mod, convexity=mod * mod + mod / (1.0 + y))
            except (TypeError, ValueError):
                row["asset_class"] = "bond_fixed"
        else:
            beta, n = rate_beta(ticker)
            if beta is not None:
                row.update(beta_rates=beta, rate_episodes=n)
        out[ticker] = row
    return out


def classify(ticker: str, meta: dict[str, Any] | None = None) -> str:
    hint = (meta or {}).get("asset_class") or ""
    name = f"{ticker} {hint}".upper()
    if "FLOAT" in name or "ФЛОАТ" in name:
        return "floater"
    if "OFZ" in name or "SU262" in name or "BOND" in name or hint == "bond_fixed":
        return "bond_fixed"
    if ticker.upper() == "CASH" or hint == "deposit":
        return "cash"
    return "equity"


def _income_note(parts: dict[str, float], has_fixed_bonds: bool) -> str:
    """What the 12-month cash income consists of, in words (the old caption said "coupons"
    while the number was mostly money-market fund yield)."""
    names = []
    if parts.get("money_market"):
        names.append("фонды денежного рынка и остаток под ключевую ставку")
    if parts.get("floater"):
        names.append("флоатеры")
    text = ", ".join(names) if names else "нет позиций с доходом от ставки"
    if has_fixed_bonds:
        text += "; купоны облигаций с фиксированным купоном не входят"
    return text


def explain_shift(
    user_id: str,
    *,
    mode: str = "paper",
    shift_bp: int = 100,
    path: list[int] | None = None,
    meta: dict[str, dict[str, Any]] | None = None,
    key_rate: float | None = None,
) -> dict[str, Any]:
    started = perf_counter()
    if not is_enabled("qa_key_rate"):
        return {"data_status": "нет данных", "reason": "нет данных"}
    dy = shift_bp / 10_000.0
    holdings = _holdings_from_book(user_id, mode)
    if meta is None:
        meta = auto_meta(holdings)
    if key_rate is None:
        key_rate = current_key_rate()
    nav = _nav_rub(holdings) or 0.0
    if nav <= 0 and not holdings:
        return {
            "data_status": "нет данных",
            "reason": "нет позиций",
            "methodology": "/methodology/key-rate",
        }
    by_class = {"bond_fixed": 0.0, "floater": 0.0, "equity": 0.0, "cash": 0.0}
    income = 0.0
    income_parts = {"floater": 0.0, "money_market": 0.0}
    has_fixed_bonds = False
    rate_known = key_rate is not None
    missing: list[str] = []
    rows: list[dict[str, Any]] = []
    for h in holdings:
        ticker = str(h.get("ticker") or "").upper()
        info = (meta or {}).get(ticker, {})
        klass = classify(ticker, info)
        value = _value_rub(h) or 0.0
        if klass == "bond_fixed":
            has_fixed_bonds = True
            dur = info.get("mod_duration")
            conv = info.get("convexity")
            if dur is None or conv is None:
                missing.append(ticker)
                chg = None
            else:
                chg = value * bond_price_change_pct(
                    mod_duration=float(dur), convexity=float(conv), dy=dy
                )
                by_class["bond_fixed"] += chg
        elif klass == "floater":
            chg = value * floater_price_change_pct()
            by_class["floater"] += chg
            if info.get("spread") is None:
                missing.append(ticker)
            elif rate_known:
                spread = float(info["spread"])
                part = floater_income(notional=value, new_rate=float(key_rate) + dy, spread=spread)
                income += part
                income_parts["floater"] += part
        elif klass == "cash":
            chg = 0.0
            by_class["cash"] += chg
            if rate_known:
                part = deposit_income(balance=value, new_rate=float(key_rate) + dy)
                income += part
                income_parts["money_market"] += part
        else:
            beta = info.get("beta_rates")
            if beta is None:
                missing.append(ticker)
                chg = None
            else:
                point = equity_return_from_rate_beta(beta=float(beta), dy=dy)
                chg = value * point
                by_class["equity"] += chg
        rows.append({"ticker": ticker, "class": klass, "value_change": chg})
    total = sum(v for v in by_class.values())
    meetings = _parse_meetings()
    replay = []
    for ep in meetings.get("episodes") or []:
        replay.append({**ep, "approx_value_change": total * (int(ep["shift_bp"]) / shift_bp) if shift_bp else None})
    if rate_known:
        sentence = (
            f"По прошлой реакции рынка, не прогноз. Сдвиг {shift_bp} б.п.: "
            f"стоимость {total:.0f} ₽, доход за 12 месяцев {income:.0f} ₽."
        )
    else:
        sentence = (
            f"По прошлой реакции рынка, не прогноз. Сдвиг {shift_bp} б.п.: "
            f"стоимость {total:.0f} ₽."
        )
    if filter_wording(sentence):
        sentence = "нет данных"
    status = "частично" if missing else "ok"
    return {
        "data_status": status,
        "reason": None if not missing else "пропущено: " + ", ".join(missing),
        "shift_bp": shift_bp,
        "path": path,
        "nav": nav or None,
        "value_change": total,
        "value_change_pct": (total / nav) if nav else None,
        "income_12m": income if rate_known else None,
        "income_parts": income_parts if rate_known else None,
        "income_note_ru": _income_note(income_parts, has_fixed_bonds) if rate_known else None,
        "by_class": by_class,
        "interval": None,
        "rows": rows,
        "episodes": replay,
        "sentence": sentence,
        "methodology": "/methodology/key-rate",
        "elapsed_ms": round((perf_counter() - started) * 1000.0, 3),
    }
