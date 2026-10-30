"""One policy for every money action (Prompt 10, founder R2).

Manual breach → warn + confirmation. Automatic breach → block.
Safer-size hints never say buy or sell.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Literal

from app.core.logging import get_logger
from app.services.catalog.resolve import resolve as catalog_resolve
from app.services.event_bus.bus import publish_event
from app.services.portfolio_book.store import get_book
from app.services.pretrade.journal import append as journal_append
from app.services.qa.feature_flags import is_enabled
from app.services.risk_engine.series import get_series
from app.services.quant_math.core import correlation

Actor = Literal["human", "auto"]
Kind = Literal["manual_order", "bot", "idea", "strategy"]
Mode = Literal["paper", "live"]
Verdict = Literal["ok", "warn", "block"]

MAX_NOTIONAL = 100_000.0
MAX_CONCENTRATION = 0.25
MAX_CORR = 0.90
MAX_DRAWDOWN = 0.20
_FAIL_CLOSED = frozenset({"no_price", "flag_off", "regime_unavailable", "profile_unavailable"})
logger = get_logger(__name__)


def _log_actor(user_id: str) -> str:
    return hashlib.sha256((user_id or "").encode("utf-8")).hexdigest()[:12]


@dataclass
class Reason:
    code: str
    detail: str
    number: float | None = None


@dataclass
class Decision:
    verdict: Verdict
    reasons: list[Reason] = field(default_factory=list)
    safer: str = ""
    requires_confirm: bool = False

    def as_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "reasons": [{"code": r.code, "detail": r.detail, "number": r.number} for r in self.reasons],
            "safer": self.safer,
            "requires_confirm": self.requires_confirm,
        }


def _listing(ticker: str) -> tuple[str, Reason | None]:
    try:
        hit = catalog_resolve(ticker)
    except (KeyError, ValueError):
        return ticker.upper(), Reason(
            "instrument_unavailable",
            "инструмент недоступен в справочнике",
            None,
        )
    asset = str(hit.asset_id or hit.symbol or ticker).upper()
    if hit.ambiguous or not hit.tradeable:
        return asset, Reason(
            "instrument_unavailable",
            hit.trade_block_reason or "инструмент недоступен для сделки",
            None,
        )
    return asset, None


def _book_nav(user_id: str, mode: Mode) -> float | None:
    from app.services.concentration.service import _trade_price

    positions = get_book().positions(user_id=user_id, mode=mode)  # type: ignore[arg-type]
    total = 0.0
    saw = False
    for pos in positions:
        if pos.ticker.upper() == "CASH":
            total += float(pos.qty)
            saw = True
            continue
        px = _trade_price(user_id, mode, pos.ticker)
        if px is None:
            return None
        total += float(abs(pos.qty) * px)
        saw = True
    return total if saw else None


def _asset_id(ticker: str) -> str:
    asset, _reason = _listing(ticker)
    return asset


def evaluate(
    *,
    kind: Kind,
    actor: Actor,
    user_id: str,
    ticker: str,
    qty: float,
    price: float,
    mode: Mode = "paper",
    nav: float | None = None,
    confirmed: bool = False,
    live_allowed: bool = False,
    max_dd: float | None = None,
) -> Decision:
    if not is_enabled("qa_risk_gate"):
        return Decision(
            verdict="block",
            reasons=[Reason("flag_off", "риск-гейт выключен: сделка не разрешена", None)],
        )
    reasons: list[Reason] = []
    try:
        px = float(price) if price is not None else 0.0
    except (TypeError, ValueError):
        px = 0.0
    if price is None or px <= 0:
        reasons.append(Reason("no_price", "нет данных", None))
        px = 0.0
    notional = abs(float(qty) * px)
    if notional > MAX_NOTIONAL:
        reasons.append(Reason("user_limit", "номинал выше лимита пользователя", notional))
    resolved_nav = nav if nav is not None else _book_nav(user_id, mode)
    if resolved_nav is not None and resolved_nav > 0 and notional / resolved_nav > MAX_CONCENTRATION:
        reasons.append(Reason("concentration", "доля после сделки выше 25% капитала", notional / resolved_nav))
    if mode == "live" and not live_allowed:
        reasons.append(Reason("live_rules", "live без разрешения на исполнение", None))
    positions = get_book().positions(user_id=user_id, mode=mode)  # type: ignore[arg-type]
    asset, listing_reason = _listing(ticker)
    if listing_reason:
        reasons.append(listing_reason)
    for pos in positions:
        if pos.ticker.upper() == ticker.upper() or _asset_id(pos.ticker) == asset:
            reasons.append(Reason("duplicate_asset", "уже есть позиция по тому же активу", float(pos.qty)))
            break
    series_new = get_series(ticker)
    if series_new:
        for pos in positions:
            other = get_series(pos.ticker)
            n = min(len(series_new), len(other))
            if n >= 20 and abs(correlation(series_new[-n:], other[-n:])) >= MAX_CORR:
                reasons.append(Reason("stat_corr", "высокая корреляция доходностей с открытой позицией", n))
                break
    if max_dd is not None and max_dd > MAX_DRAWDOWN:
        reasons.append(Reason("drawdown", "просадка портфеля выше порога", max_dd))
    try:
        from app.services.market_regime.service import classify_ticker

        if is_enabled("qa_market_regime"):
            reg = classify_ticker(ticker, scope="instrument")
            if reg["label"] == "crisis":
                reasons.append(Reason("regime_crisis", "режим кризиса: автоматика ограничена", None))
    except Exception as exc:
        logger.warning("regime classify failed; refuse ticket", ticker=ticker, error=str(exc)[:200])
        reasons.append(Reason("regime_unavailable", "нет данных", None))
    if qty > 1_000_000:
        reasons.append(Reason("liquidity", "размер заявки несоразмерен типичному обороту", qty))
    if is_enabled("qa_personal_limits"):
        from app.services.personal_limits.service import user_rule_reasons

        for detail in user_rule_reasons(user_id=user_id, mode=mode):
            reasons.append(Reason("personal_limit", detail, None))
    if is_enabled("qa_investment_profile"):
        from app.services.investment_profile.service import get_profile

        try:
            inv = get_profile(user_id)
        except Exception as exc:
            logger.warning("investment profile unavailable; refuse ticket", actor=_log_actor(user_id), error=str(exc)[:200])
            reasons.append(Reason("profile_unavailable", "нет данных", None))
            inv = None
        if inv:
            banned = {t.upper() for t in (inv.get("banned_tickers") or [])}
            if ticker.upper() in banned:
                reasons.append(Reason("profile_ban", "тикер в запретах профиля", None))
            max_w = inv.get("max_position_pct")
            if resolved_nav is not None and resolved_nav > 0:
                try:
                    limit = float(max_w)
                except (TypeError, ValueError):
                    reasons.append(Reason("profile_weight", "нет лимита доли", None))
                else:
                    share = notional / resolved_nav
                    if share > limit:
                        reasons.append(Reason("profile_weight", "доля выше лимита профиля", share))

    safer_nav = float(resolved_nav) if resolved_nav is not None else 0.0
    fail_closed = any(r.code in _FAIL_CLOSED for r in reasons)
    if not reasons:
        decision = Decision(verdict="ok")
    elif fail_closed:
        decision = Decision(verdict="block", reasons=reasons, safer=_safer(notional, safer_nav))
    elif actor == "human" and not (mode == "live" and not live_allowed):
        if confirmed:
            decision = Decision(verdict="ok", reasons=reasons, safer=_safer(notional, safer_nav))
        else:
            decision = Decision(
                verdict="warn",
                reasons=reasons,
                safer=_safer(notional, safer_nav),
                requires_confirm=True,
            )
    else:
        decision = Decision(verdict="block", reasons=reasons, safer=_safer(notional, safer_nav))

    journal_append(
        {
            "user_id": user_id,
            "kind": kind,
            "actor": actor,
            "ticker": ticker.upper(),
            "mode": mode,
            **decision.as_dict(),
        }
    )
    try:
        if decision.verdict == "block":
            publish_event("risk.limit_breached", {"user_id": user_id, "ticker": ticker, "kind": kind})
        elif decision.verdict == "warn":
            publish_event("risk.warning", {"user_id": user_id, "ticker": ticker, "kind": kind})
    except Exception as exc:
        logger.warning("pretrade event publish failed", actor=_log_actor(user_id), error=str(exc)[:200])
    return decision


def _safer(notional: float, nav: float) -> str:
    cap = min(MAX_NOTIONAL, MAX_CONCENTRATION * nav if nav > 0 else MAX_NOTIONAL)
    if notional <= 0:
        return "уменьшите номинал до лимита политики"
    return f"чтобы пройти лимиты, уменьшите номинал примерно до {cap:.0f} (без совета по направлению сделки)"


def assert_allowed(decision: Decision) -> None:
    if decision.verdict == "block":
        raise PermissionError(decision.reasons[0].detail if decision.reasons else "risk_gate_block")
    if decision.verdict == "warn" and decision.requires_confirm:
        raise PermissionError("risk_gate_confirm_required")
