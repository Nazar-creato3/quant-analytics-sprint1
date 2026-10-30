"""Multi-role LLM debate before finalizing maneuver list (TradingAgents pattern)."""
from __future__ import annotations

import json
import os
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

ANALYST_SYSTEM = (
    "You are a senior equity analyst. Propose the top trade ideas from the candidate list. "
    "Be concise — bullet points with ticker, direction, and one-line thesis."
)
RISK_SYSTEM = (
    "You are a risk manager. Critique each proposed trade: concentration, macro, liquidity, "
    "and correlation risks. Flag trades that should be downgraded or rejected."
)
ARBITER_SYSTEM = (
    "You are the chief investment officer. Read the analyst proposals and risk critique. "
    "Output a JSON array of objects with keys: ticker, direction, approved (bool), "
    "confidence_adjustment (-0.2..0.2), note. Keep at most 10 entries."
)


def debate_enabled() -> bool:
    return (os.getenv("MANEUVER_DEBATE_ENABLED") or "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _format_candidates(candidates: list[Any]) -> str:
    lines: list[str] = []
    for c in candidates[:15]:
        if hasattr(c, "ticker"):
            lines.append(
                f"- {c.ticker}: dir={getattr(getattr(c, 'prediction', None), 'direction', '?')} "
                f"conf={getattr(getattr(c, 'prediction', None), 'confidence', 0):.2f} "
                f"score={getattr(c, 'composite_score', 0):.3f}"
            )
        elif isinstance(c, dict):
            lines.append(
                f"- {c.get('ticker')}: dir={c.get('direction')} conf={c.get('confidence')} "
                f"rationale={c.get('rationale', '')[:80]}"
            )
    return "\n".join(lines) or "(no candidates)"


async def run_maneuver_debate(candidates: list[Any]) -> dict[str, Any] | None:
    """Run analyst → risk → arbiter debate via configured LLM. Returns None if disabled/unavailable."""
    if not debate_enabled():
        return None
    if not candidates:
        return None

    try:
        from app.services.terminal_platform.llm.factory import get_default_llm_provider

        provider = get_default_llm_provider()
        if provider is None or not provider.is_available():
            logger.info("maneuver_debate skipped — LLM provider unavailable")
            return None
    except Exception as exc:  # noqa: BLE001
        logger.info("maneuver_debate skipped", error=str(exc))
        return None

    brief = _format_candidates(candidates)
    try:
        analyst = await provider.generate(
            f"Candidates:\n{brief}\n\nPropose ranked trades.",
            system=ANALYST_SYSTEM,
        )
        risk = await provider.generate(
            f"Analyst proposals:\n{analyst.content}\n\nOriginal candidates:\n{brief}",
            system=RISK_SYSTEM,
        )
        arbiter = await provider.generate(
            f"Analyst:\n{analyst.content}\n\nRisk:\n{risk.content}\n\nDecide final approvals as JSON.",
            system=ARBITER_SYSTEM,
        )
        decisions: list[dict[str, Any]] = []
        try:
            parsed = json.loads(arbiter.content)
            if isinstance(parsed, list):
                decisions = parsed
        except json.JSONDecodeError:
            decisions = [{"raw": arbiter.content[:500]}]

        return {
            "ok": True,
            "pattern": "multi_role_debate",
            "analyst_excerpt": analyst.content[:400],
            "risk_excerpt": risk.content[:400],
            "decisions": decisions,
            "provider": provider.name,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("maneuver_debate failed", error=str(exc))
        return {"ok": False, "error": str(exc)}


def structural_debate(candidates: list[Any]) -> dict[str, Any]:
    """Always-on arbiter: no LLM, no 0.65 dry-run cut. Cuts AVOID and stacks."""
    decisions: list[dict[str, Any]] = []
    seen_dir: dict[str, int] = {}
    for c in candidates:
        ticker = str(getattr(c, "ticker", "") or "").upper()
        if not ticker:
            continue
        hint = getattr(c, "hierarchy_hint", None)
        direction = str(getattr(getattr(c, "prediction", None), "direction", "") or "")
        approved = True
        adj = 0.0
        note = ""
        if hint is not None and getattr(hint, "is_avoid", False):
            approved = False
            note = "hierarchy_avoid"
        else:
            key = direction or "na"
            seen_dir[key] = seen_dir.get(key, 0) + 1
            if seen_dir[key] > 6:
                adj = -0.04
                note = "direction_stack"
            if hint is not None and getattr(hint, "is_wait", False):
                adj -= 0.02
                note = (note + "+wait").strip("+")
        decisions.append(
            {
                "ticker": ticker,
                "approved": approved,
                "confidence_adjustment": adj,
                "note": note,
            }
        )
    return {
        "ok": True,
        "pattern": "structural_debate",
        "approved_count": sum(1 for d in decisions if d.get("approved")),
        "decisions": decisions,
    }


def apply_debate_adjustments(
    candidates: list[Any],
    debate_result: dict[str, Any] | None,
) -> list[Any]:
    """Reorder/downgrade candidates based on arbiter decisions (best-effort)."""
    if not debate_result or not debate_result.get("ok"):
        return candidates
    decisions = debate_result.get("decisions") or []
    if not decisions or not isinstance(decisions, list):
        return candidates

    rejected: set[str] = set()
    boosts: dict[str, float] = {}
    for d in decisions:
        if not isinstance(d, dict):
            continue
        ticker = str(d.get("ticker", "")).upper()
        if not ticker:
            continue
        if d.get("approved") is False:
            rejected.add(ticker)
        adj = d.get("confidence_adjustment")
        if isinstance(adj, (int, float)):
            boosts[ticker] = float(adj)

    filtered = [c for c in candidates if getattr(c, "ticker", "").upper() not in rejected]
    for c in filtered:
        ticker = getattr(c, "ticker", "").upper()
        if ticker in boosts and hasattr(c, "prediction"):
            try:
                c.prediction.confidence = max(
                    0.0,
                    min(1.0, c.prediction.confidence + boosts[ticker]),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "debate confidence adjust failed; leave prior confidence",
                    ticker=ticker,
                    error=str(exc)[:200],
                )
    filtered.sort(key=lambda c: getattr(c, "composite_score", 0), reverse=True)
    return filtered


def debate_maneuvers_dry_run(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Offline dry-run for tests — no LLM call."""
    approved = [c for c in candidates if float(c.get("confidence", 0)) >= 0.65]
    rejected = [c["ticker"] for c in candidates if c not in approved]
    return {
        "ok": True,
        "pattern": "multi_role_debate_dry_run",
        "approved_count": len(approved),
        "rejected_tickers": rejected,
        "decisions": [
            {"ticker": c["ticker"], "approved": True, "confidence_adjustment": 0.0}
            for c in approved
        ],
    }
