"""Market relevance filtering for news ingestion and ranking."""
from __future__ import annotations

import re

# Topics that affect markets globally (English + Russian macro headlines)
_MARKET_TOPICS = re.compile(
    r"\b("
    r"earnings|revenue|profit|guidance|forecast|gdp|cpi|inflation|fed|ecb|boe|"
    r"central\s+bank|rate\s+hike|rate\s+cut|interest\s+rate|treasury|bond|yield|"
    r"oil|crude|gold|commodity|sanctions|tariff|trade\s+war|merger|acquisition|"
    r"ipo|bankruptcy|default|recession|unemployment|payroll|fomc|opec|"
    r"stock\s+market|s&p|nasdaq|dow\s+jones|crypto|bitcoin|ethereum|"
    r"ставк|инфляц|дефляц|эконом|рынок|акци|облигац|нефт|газ|бирж|"
    r"курс|рубл|доллар|евро|санкц|экспорт|импорт|валют|"
    r"цб\s*рф|центробанк|фрс|moex|imoex|индекс|"
    r"дивиденд|выручк|прибыл|убыт|ipo|merger"
    r")\b",
    re.IGNORECASE,
)

# Local crime / military noise without direct market linkage
_EXCLUDE_PATTERNS = re.compile(
    r"\b("
    r"дрон|бпла|wildberries|вайлдберриз|уголовн|убийств|краж|"
    r"drone\s+attack|murder\s+case|criminal\s+case|shoplifting|"
    r"local\s+police|traffic\s+accident|celebrity\s+gossip"
    r")\b",
    re.IGNORECASE,
)

# Military/geopolitical only when market-relevant
_MILITARY_MARKET = re.compile(
    r"\b("
    r"sanctions|embargo|blockade|ceasefire|invasion|nuclear|"
    r"oil\s+supply|gas\s+pipeline|strait|shipping|commodity\s+price"
    r")\b",
    re.IGNORECASE,
)


def compute_market_relevance(text: str, ticker: str = "") -> float:
    """Score 0..1 how market-relevant an article is."""
    text_lower = text.lower()
    if _EXCLUDE_PATTERNS.search(text) and not _MILITARY_MARKET.search(text):
        return 0.0

    score = 0.0
    if ticker and ticker.lower() in text_lower:
        score += 0.35
    topic_hits = len(_MARKET_TOPICS.findall(text))
    score += min(topic_hits * 0.12, 0.5)
    if _MILITARY_MARKET.search(text):
        score += 0.25
    financial_keywords = ["earnings", "revenue", "profit", "loss", "guidance", "forecast", "macro"]
    score += min(sum(1 for kw in financial_keywords if kw in text_lower) * 0.08, 0.25)
    return round(min(score, 1.0), 3)


def is_market_relevant(text: str, ticker: str = "", min_score: float = 0.15) -> bool:
    """Return True if article passes market relevance threshold."""
    return compute_market_relevance(text, ticker) >= min_score


# General-news agencies: their feed mixes sport, accidents and politics with the economy.
GENERAL_NEWS_SOURCES: frozenset[str] = frozenset({"interfax", "rbc"})

_NON_ECONOMIC = re.compile(
    r"\b("
    r"футбол|хоккей|теннис|баскетбол|рпл|кхл|матч|чемпионат|олимпи|турнир|"
    r"дтп|авари|землетрясен|пожар|погиб|пострадал|госпитализ|медпомощ|"
    r"беспилотник|бпла|обстрел|атак[аиу]|ракетн|минобороны|всу|"
    r"выпускник|школ|погод|снегопад|шторм|"
    r"football|soccer|hockey|tennis|earthquake|wildfire"
    r")",
    re.IGNORECASE,
)


# Same topics, matched as word starts: the trailing \b of _MARKET_TOPICS stops Russian stems
# ("ставк" in "ставку") from ever matching.
_MARKET_STEMS = re.compile(_MARKET_TOPICS.pattern[: -len(r"\b")] if _MARKET_TOPICS.pattern.endswith(r"\b") else _MARKET_TOPICS.pattern, re.IGNORECASE)


def is_economic_news(title: str, description: str = "", source: str = "") -> bool:
    """Whether a headline belongs in the economic news panel.

    Financial publishers pass as is. General-news agencies (Interfax, RBC) need a market
    topic in the text and no sport/accident/war wording without a market link.
    """
    src = (source or "").strip().lower()
    text = f"{title or ''} {description or ''}"
    if src not in GENERAL_NEWS_SOURCES:
        return True
    if _NON_ECONOMIC.search(text) and not _MILITARY_MARKET.search(text):
        return False
    return bool(_MARKET_STEMS.search(text))


# Curated macro RSS feeds — real headlines, never treated as demo content.
TRUSTED_RSS_SOURCES: frozenset[str] = frozenset({"investing_com", "rbc", "interfax"})


def is_trusted_rss_source(source: str) -> bool:
    """Return True for configured legal RSS macro feeds."""
    return (source or "").strip().lower() in TRUSTED_RSS_SOURCES
