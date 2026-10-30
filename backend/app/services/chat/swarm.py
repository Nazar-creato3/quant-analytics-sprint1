"""Multi-agent map-reduce for complex portfolio-level chat questions."""
from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.services.chat.tools import execute_tool

logger = get_logger(__name__)

_SWARM_TRIGGERS = (
    "портфел",
    "portfolio",
    "все позиц",
    "all holdings",
    "риск.*концентрац",
    "correlation risk",
    "диверсиф",
)


def needs_swarm(question: str) -> bool:
    q = question.lower()
    return any(t in q for t in _SWARM_TRIGGERS if not t.startswith("риск")) or (
        "риск" in q and "концентрац" in q
    )


async def run_swarm_subtasks(
    db: AsyncSession,
    *,
    question: str,
    tickers: list[str],
) -> dict[str, Any]:
    """Parallel sub-calls for factor concentration, correlation, news, VaR."""
    tasks = []

    if tickers:
        tasks.append(("factor_concentration", execute_tool(db, "compare_tickers", {"tickers": tickers[:8]})))
        for t in tickers[:4]:
            tasks.append((f"news_{t}", execute_tool(db, "get_recent_news", {"ticker": t, "days_back": 7})))
            tasks.append((f"risk_{t}", execute_tool(db, "get_risk_metrics", {"ticker": t})))

    tasks.append(("market_regime", execute_tool(db, "get_market_regime", {})))
    tasks.append(("macro", execute_tool(db, "get_macro_context", {})))

    results: dict[str, Any] = {}
    if not tasks:
        return results

    names, coros = zip(*tasks)
    outputs = await asyncio.gather(*coros, return_exceptions=True)
    for name, out in zip(names, outputs):
        if isinstance(out, Exception):
            results[name] = {"error": str(out)}
        else:
            import json

            try:
                results[name] = json.loads(out)
            except json.JSONDecodeError:
                results[name] = out
    return results
