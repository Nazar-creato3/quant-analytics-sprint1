"""Ticker-scoped AI advisor replies built from hierarchy forecast (no external LLM)."""
from __future__ import annotations

import re

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.services.chat.deep_advisor import build_deep_advisor_reply

logger = get_logger(__name__)

_ADVISOR_SENDER_ID = "platform-advisor"
_TICKER_RE = re.compile(r"\b([A-Z]{1,5})\b")
_SKIP_SYMBOLS = frozenset({
    "I", "A", "AI", "USD", "ETF", "IPO", "USA", "RU", "EU",
    "HELLO", "WORLD", "THE", "AND", "FOR", "YOU", "ARE", "NOT",
})


def advisor_sender_id() -> str:
    return _ADVISOR_SENDER_ID


def extract_symbol_from_text(text: str) -> str | None:
    for match in _TICKER_RE.finditer(text.upper()):
        sym = match.group(1)
        if sym in _SKIP_SYMBOLS:
            continue
        return sym
    return None


def default_ticker_title(symbol: str) -> str:
    return f"{symbol.strip().upper()} · прогноз и анализ"


async def build_ticker_advisor_reply(
    db: AsyncSession,
    *,
    symbol: str,
    user_question: str,
    prior_messages: tuple[str, ...] = (),
    conversation_history: list[tuple[str, str]] | None = None,
    session_tickers: list[str] | None = None,
    owner_user_id: str | None = None,
    owner_email: str | None = None,
) -> str:
    from app.services.chat.agentic_advisor import build_agentic_advisor_reply
    from app.services.instrument.resolver import resolve_or_create_instrument

    normalized = symbol.strip().upper()
    try:
        return await build_agentic_advisor_reply(
            db,
            user_question=user_question,
            symbol=normalized,
            conversation_history=conversation_history,
            session_tickers=session_tickers,
            owner_user_id=owner_user_id,
            owner_email=owner_email,
        )
    except Exception as exc:
        logger.warning("Agentic advisor failed, falling back to deep", error=str(exc))
        instrument = await resolve_or_create_instrument(db, normalized)
        return await build_deep_advisor_reply(
            db,
            instrument_id=instrument.id,
            symbol=instrument.symbol,
            user_question=user_question,
            prior_messages=prior_messages,
        )


async def build_open_chat_reply(
    db: AsyncSession,
    *,
    user_question: str,
    conversation_history: list[tuple[str, str]] | None = None,
    session_tickers: list[str] | None = None,
    owner_user_id: str | None = None,
    owner_email: str | None = None,
) -> str:
    """Open-ended in-app chat without required ticker scope."""
    from app.services.chat.agentic_advisor import build_agentic_advisor_reply

    return await build_agentic_advisor_reply(
        db,
        user_question=user_question,
        symbol=None,
        conversation_history=conversation_history,
        session_tickers=session_tickers,
        owner_user_id=owner_user_id,
        owner_email=owner_email,
    )
