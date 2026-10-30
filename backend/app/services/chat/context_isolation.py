"""Per-question instrument isolation for advisor chat (Prompt 80)."""
from __future__ import annotations

from app.services.chat.ticker_advisor import _SKIP_SYMBOLS, _TICKER_RE, extract_symbol_from_text


def resolve_advisor_symbol(question: str, conversation_symbol: str | None) -> str | None:
    """Prefer an explicit ticker in the current question over a stale thread symbol."""
    from_question = extract_symbol_from_text(question)
    conv = conversation_symbol.strip().upper() if conversation_symbol else None
    if from_question and conv and from_question != conv:
        return from_question
    return conv or from_question


def tickers_mentioned_in_text(text: str) -> set[str]:
    found: set[str] = set()
    for match in _TICKER_RE.finditer(text.upper()):
        sym = match.group(1)
        if len(sym) < 2 or sym in _SKIP_SYMBOLS:
            continue
        found.add(sym)
    return found


def prior_messages_for_symbol(
    prior_messages: tuple[str, ...],
    symbol: str,
) -> tuple[str, ...]:
    """Drop prior advisor replies that clearly belong to another instrument."""
    sym = symbol.strip().upper()
    if not sym:
        return prior_messages
    kept: list[str] = []
    for body in prior_messages:
        mentioned = tickers_mentioned_in_text(body)
        if mentioned and mentioned - {sym}:
            continue
        # Known regression: GAZP invest-program figures leaking into US names.
        if sym != "GAZP" and ("515" in body and "млрд" in body) and (
            "GAZP" in body.upper() or "ГАЗП" in body.upper() or "Газпром" in body
        ):
            continue
        kept.append(body)
    return tuple(kept)
