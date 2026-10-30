"""Operator desks — what each person does. Culture over PDF."""

DESKS: list[dict[str, str]] = [
    {
        "id": "cio",
        "title": "CIO / book owner",
        "does": "Подписывает IPS (cap, max risk, banned, ESG). Не поднимает $250 до $10k. Halt = кэш.",
        "never": "Не обходит kill и не промоутит модель без freeze_id.",
    },
    {
        "id": "pm",
        "title": "PM / construction",
        "does": "allocate → construct (conviction, vol, TCM). Leftover остаётся кэшем, не 1/n.",
        "never": "Не открывает новый риск на halt. Не льёт остаток в слабые имена.",
    },
    {
        "id": "risk",
        "title": "Risk / compliance",
        "does": "VaR/ES, stress 2008/2020/rate, HHI/FF/SPY, PDT, locate≈1% ADV, pre-trade cap.",
        "never": "Не считает HTB-вендор обязательным. Не игнорирует stale bar / broker disconnect.",
    },
    {
        "id": "exec",
        "title": "Execution",
        "does": "SOR по своим fills, TWAP/VWAP Cartea ≥60s, bracket 2×ATR 2:1. Paper ≠ live MOEX.",
        "never": "Не шлёт MOEX на Alpaca. Не режет слайс быстрее минуты ради 'HFT'.",
    },
    {
        "id": "research",
        "title": "Research → prod",
        "does": "Карточка + nested CPCV + human confirm + MFA если включён. Пишет sign-off JSONL.",
        "never": "Не auto-promote из retrain. Не промоутит без feature freeze.",
    },
    {
        "id": "ops",
        "title": "Ops / DR",
        "does": "Nightly: digest, parity, DR seal floor, last-good features, freshness SLA.",
        "never": "Не затирает last-good пустым дампом. Не меняет sealed $250 на дефолт $10k.",
    },
    {
        "id": "client",
        "title": "Client reporting",
        "does": "Tear (QuantStats если есть), Brinson-lite по секторам, Euler risk contribution.",
        "never": "Не выдаёт paper excess как live PnL. Не обещает vendor Barra.",
    },
]


def desks() -> list[dict[str, str]]:
    return list(DESKS)
