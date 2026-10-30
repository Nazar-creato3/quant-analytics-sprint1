"""Automated quality evaluation corpus for in-app chat anti-template regression."""
from __future__ import annotations

QUALITY_EVAL_QUESTIONS: tuple[str, ...] = (
    "какая цена у SBER",
    "сравни SBER и VTBR",
    "что происходит с рынком нефти",
    "какие факторы драйвят NVDA",
    "стоит ли пересматривать позицию в нефтянке с учётом санкций",
    "проанализируй весь мой портфель и скажи где риски",
    "какой режим рынка сейчас",
    "расскажи про макро — ставка и инфляция",
    "SHAP по AAPL",
    "новости по TSLA за неделю",
    "сравни SPY QQQ и IWM",
    "риск-метрики MSFT",
    "а что насчёт него",
    "как VaR у GOOGL",
    "factor exposure AMZN",
    "что с корреляцией tech сектора",
    "кратко: прогноз BTC-USD",
    "объясни bear case для META",
    "bull case для GLD",
    "liquidity risk COIN",
    "сравни банки SBER VTBR TCSG",
    "макро контекст для российского рынка",
    "regime detection SPY",
    "портфель: концентрация по секторам",
    "что изменилось с прошлой недели по AAPL",
    "earnings risk NFLX",
    "sanctions impact on oil stocks",
    "дивидендная доходность SBER vs LKOH",
    "momentum vs value сейчас",
    "tail risk QQQ",
    "какие новости по санкциям влияют на нефть",
    "compare XOM and CVX risk",
    "что с VIX и рынком",
    "factor rotation leaderboard",
    "insufficient data test XYZABC",
    "quick: price QQQ",
    "deep: reassess energy exposure given latest news",
    "portfolio VaR concentration check",
    "regulatory news impact on COIN",
    "macro uncertainty hedge ideas context only",
)

JUDGE_PROMPT_RU = """Оцени ответ аналитического чата (1-5):
1 = шаблонный/generic, не engages with question
5 = genuinely specific, data-grounded, non-templated

Question: {question}
Answer: {answer}

Reply JSON: {{"score": N, "reason": "..."}}"""
