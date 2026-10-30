"""Agentic in-app chat advisor with native tool-calling and conversation memory."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.services.chat.advisor_prompt import (
    ANTI_TEMPLATE_INSTRUCTIONS_RU,
    build_agentic_chat_system,
)
from app.services.chat.mode_router import (
    ChatMode,
    classify_chat_mode,
    mode_max_tokens,
    mode_temperature,
)
from app.services.chat.swarm import needs_swarm, run_swarm_subtasks
from app.services.chat.tools import TOOL_SCHEMAS, execute_tool
from app.services.chat.ticker_advisor import extract_symbol_from_text

logger = get_logger(__name__)

MAX_TOOL_ROUNDS = 5
MAX_HISTORY_TURNS = 20


def _extract_tickers(question: str, primary: str | None) -> list[str]:
    import re

    found = set()
    if primary:
        found.add(primary.upper())
    for m in re.finditer(r"\b([A-Z]{1,5}(?:-[A-Z]+)?)\b", question.upper()):
        sym = m.group(1)
        if sym not in {"I", "A", "AI", "USD", "ETF", "IPO", "THE", "AND", "FOR"}:
            found.add(sym)
    if not found and primary:
        found.add(primary.upper())
    return list(found)


def _build_history_messages(
    history: list[tuple[str, str]],
) -> list[dict[str, Any]]:
    """Convert (role, body) pairs to OpenAI message format."""
    messages: list[dict[str, Any]] = []
    for role, body in history[-MAX_HISTORY_TURNS:]:
        if role == "user":
            messages.append({"role": "user", "content": body})
        else:
            messages.append({"role": "assistant", "content": body})
    return messages


async def build_agentic_advisor_reply(
    db: AsyncSession,
    *,
    user_question: str,
    symbol: str | None = None,
    conversation_history: list[tuple[str, str]] | None = None,
    session_tickers: list[str] | None = None,
    owner_user_id: str | None = None,
    owner_email: str | None = None,
) -> str:
    """Tool-calling agent loop with mode routing and optional swarm."""
    from app.services.chat.deep_advisor import build_deep_advisor_reply
    from app.services.instrument.resolver import resolve_or_create_instrument
    from app.services.llm.llm_service import LLMService, llm_enabled

    if not llm_enabled():
        if symbol:
            instrument = await resolve_or_create_instrument(db, symbol)
            return await build_deep_advisor_reply(
                db,
                instrument_id=instrument.id,
                symbol=instrument.symbol,
                user_question=user_question,
            )
        return (
            "LLM недоступен. Укажите тикер — построю rule-based анализ из снимка Quant Analytics."
        )

    mode = classify_chat_mode(user_question)
    primary = symbol or extract_symbol_from_text(user_question)
    tickers = _extract_tickers(user_question, primary)
    if session_tickers:
        for t in session_tickers:
            if t.upper() not in tickers:
                tickers.append(t.upper())

    session_ctx = ""
    if session_tickers:
        session_ctx = f"Тикеры в этой сессии: {', '.join(session_tickers)}. "
    if primary:
        session_ctx += f"Основной контекст: {primary}. "

    swarm_data: dict[str, Any] = {}
    if needs_swarm(user_question) and tickers:
        try:
            swarm_data = await run_swarm_subtasks(db, question=user_question, tickers=tickers)
        except Exception as exc:
            logger.warning("Swarm subtasks failed", error=str(exc))

    system = build_agentic_chat_system(mode=mode.value)
    messages: list[dict[str, Any]] = [{"role": "system", "content": system}]

    if conversation_history:
        messages.extend(_build_history_messages(conversation_history))

    user_content = user_question.strip()
    if session_ctx:
        user_content = f"{session_ctx}\n\n{user_content}"
    if swarm_data:
        user_content += f"\n\n[Swarm sub-results]\n{json.dumps(swarm_data, ensure_ascii=False)[:4000]}"

    messages.append({"role": "user", "content": user_content})

    timeout = max(5.0, float(__import__("app.core.config", fromlist=["settings"]).settings.LLM_TIMEOUT_SECONDS))

    llm_called = False
    last_llm_raw_len = 0
    tool_rounds = 0
    prompt_summary_len = len(system) + sum(len(str(m.get("content") or "")) for m in messages)

    for _round in range(MAX_TOOL_ROUNDS):
        tool_rounds = _round + 1
        try:
            response = await asyncio.wait_for(
                LLMService.complete_with_tools(
                    "inapp_chat",
                    messages,
                    tools=TOOL_SCHEMAS,
                    temperature=mode_temperature(mode),
                    max_tokens=mode_max_tokens(mode),
                ),
                timeout=timeout,
            )
            llm_called = True
            last_llm_raw_len = len((response.get("content") or "").strip())
        except asyncio.TimeoutError:
            logger.warning(
                "Agentic chat timed out",
                mode=mode.value,
                prompt_summary_len=prompt_summary_len,
                tool_rounds=tool_rounds,
                llm_called=llm_called,
            )
            break
        except Exception as exc:
            logger.warning(
                "Agentic chat LLM failed",
                error=str(exc),
                mode=mode.value,
                prompt_summary_len=prompt_summary_len,
                tool_rounds=tool_rounds,
                llm_called=llm_called,
            )
            break

        tool_calls = response.get("tool_calls")
        if not tool_calls:
            content = (response.get("content") or "").strip()
            if content:
                logger.info(
                    "Agentic chat reply",
                    mode=mode.value,
                    llm_called=True,
                    prompt_summary_len=prompt_summary_len,
                    raw_llm_len=last_llm_raw_len,
                    final_len=len(content),
                    tool_rounds=tool_rounds,
                    substituted=last_llm_raw_len != len(content),
                )
                return content
            break

        messages.append(response)
        for tc in tool_calls:
            fn = tc.get("function", {})
            name = fn.get("name", "")
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            result = await execute_tool(
                db,
                name,
                args,
                owner_user_id=owner_user_id,
                owner_email=owner_email,
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.get("id", name),
                    "content": result,
                }
            )

    logger.info(
        "Agentic chat falling back to deep advisor",
        mode=mode.value,
        symbol=symbol,
        llm_called=llm_called,
        prompt_summary_len=prompt_summary_len,
        raw_llm_len=last_llm_raw_len,
        tool_rounds=tool_rounds,
    )

    if symbol:
        instrument = await resolve_or_create_instrument(db, symbol)
        return await build_deep_advisor_reply(
            db,
            instrument_id=instrument.id,
            symbol=instrument.symbol,
            user_question=user_question,
        )
    return (
        "Не удалось построить ответ через agentic pipeline. "
        "Уточните тикер или повторите вопрос."
    )
