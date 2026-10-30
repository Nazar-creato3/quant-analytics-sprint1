"""Mode routing — Instant vs Thinking for in-app chat."""
from __future__ import annotations

import re
from enum import StrEnum

_COMPLEX_PATTERNS = re.compile(
    r"стоит\s+ли|пересматрив|портфел|сравни|сравнение|с\s+учётом|санкц|"
    r"portfolio|compare|should\s+i|reassess|weigh|tradeoff|риск.*концентрац|"
    r"корреляц|диверсиф|стратег",
    re.IGNORECASE,
)

_SIMPLE_PATTERNS = re.compile(
    r"^(какая\s+цена|цена\s+у|сколько\s+стоит|what.*price|current\s+price|"
    r"какой\s+курс|курс\s+у)\b",
    re.IGNORECASE,
)


class ChatMode(StrEnum):
    INSTANT = "instant"
    THINKING = "thinking"


def classify_chat_mode(question: str) -> ChatMode:
    """Heuristic router: simple lookups → Instant; analytical → Thinking."""
    q = question.strip()
    if len(q) < 40 and _SIMPLE_PATTERNS.search(q):
        return ChatMode.INSTANT
    if _COMPLEX_PATTERNS.search(q):
        return ChatMode.THINKING
    if len(q) > 120 or q.count("?") > 1:
        return ChatMode.THINKING
    if "," in q and any(w in q.lower() for w in ("и", "vs", "versus", "против")):
        return ChatMode.THINKING
    return ChatMode.INSTANT


def mode_temperature(mode: ChatMode) -> float:
    return 0.35 if mode == ChatMode.INSTANT else 0.55


def mode_max_tokens(mode: ChatMode) -> int:
    return 1200 if mode == ChatMode.INSTANT else 6144


def mode_model_setting(mode: ChatMode) -> str:
    """Config attr for model selection."""
    return "LLM_MODEL_CLIENT_CHAT" if mode == ChatMode.INSTANT else "LLM_MODEL_CLIENT_CHAT"
