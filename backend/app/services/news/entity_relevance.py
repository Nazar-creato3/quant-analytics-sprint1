"""Ticker-entity relevance for chat/news bucketing (MOEX names, aliases)."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class EntityMatch:
    score: float
    reason: str


_TICKER_ALIASES: dict[str, tuple[str, ...]] = {
    "GAZP": (
        "gazprom",
        "газпром",
        "газпр",
        "gazp",
        "pipe",
        "pipeline",
        "трубопровод",
        "северный поток",
        "nord stream",
    ),
    "SBER": ("sber", "сбер", "сбербанк", "sberbank"),
    "LKOH": (
        "lukoil",
        "лукойл",
        "luk oil",
        "lukoil international",
        "carlyle",
        "кarlyle",
        "treasury",
        "минфин",
        "license",
        "лиценз",
    ),
    "ROSN": ("rosneft", "роснефт"),
    "YNDX": ("yandex", "яндекс"),
    "IMOEX": ("imoex", "мосбирж"),
    "AAPL": ("apple", "эппл"),
    "MSFT": ("microsoft", "майкрософт"),
    "NVDA": ("nvidia", "нвидиа"),
    "VTBR": ("vtb", "втб"),
    "AMZN": (
        "amazon",
        "амазон",
        "aws",
        "amazon web services",
        "prime",
        "whole foods",
    ),
}

# Headlines that look financial but are unrelated noise for a given issuer.
_NOISE_FOR_ANY = re.compile(
    r"\b("
    r"india|инди[яи]|uganda|уганда|travel|туризм|tourism|"
    r"wildberries|вайлдберриз|shoplifting|celebrity|"
    r"jd\s+vance|vance|"
    r"local\s+police|traffic\s+accident"
    r")\b",
    re.IGNORECASE,
)

_MACRO_ONLY = re.compile(
    r"\b("
    r"ставк|fed|цб|инфля|gdp|cpi|sanction|санкц|геопол|"
    r"market\s+index|imoex|moex\s+index|sector\s+rotation"
    r")\b",
    re.IGNORECASE,
)


def _normalize_ticker(ticker: str) -> str:
    return ticker.strip().upper().split("-")[0].split(".")[0]


def entity_relevance_score(title: str, ticker: str) -> EntityMatch:
    """Score how strongly a headline relates to the requested symbol."""
    text = title.strip()
    if not text:
        return EntityMatch(0.0, "empty")
    sym = _normalize_ticker(ticker)
    lower = text.lower()

    if _NOISE_FOR_ANY.search(text) and sym not in ("INDIA", "UGAND"):
        aliases = _TICKER_ALIASES.get(sym, ())
        if not any(a in lower for a in aliases) and sym.lower() not in lower:
            return EntityMatch(0.05, "unrelated_noise")

    if sym.lower() in lower or f"({sym.lower()})" in lower:
        return EntityMatch(0.95, "ticker_literal")

    for alias in _TICKER_ALIASES.get(sym, ()):
        if alias in lower:
            return EntityMatch(0.88, f"alias:{alias}")

    if _MACRO_ONLY.search(text):
        return EntityMatch(0.35, "macro_only")

    return EntityMatch(0.20, "generic_financial")


def bucket_headline(
    title: str,
    *,
    ticker: str,
    corporate_min_score: float = 0.72,
    macro_min_score: float = 0.30,
) -> str:
    """
    Return bucket: corporate | macro | other.

    Corporate block requires entity relevance; unrelated noise goes to other.
    """
    match = entity_relevance_score(title, ticker)
    if match.score >= corporate_min_score:
        return "corporate"
    if match.score <= macro_min_score or match.reason in ("unrelated_noise", "macro_only"):
        return "macro" if match.reason == "macro_only" else "other"
    return "other"
