"""Normalize market_outlook dicts to MarketOutlookScenario shape."""
from __future__ import annotations


def slug_scenario(title: str) -> str:
    slug = title.lower().strip()
    for ch in " -–—/\\":
        slug = slug.replace(ch, "_")
    cleaned = "".join(ch if ch.isalnum() or ch == "_" else "_" for ch in slug)
    return cleaned.strip("_") or "context"


def normalize_market_outlook_item(
    item: object,
    *,
    default_probability: float = 0.5,
    default_engine: str = "ForecastEngine",
) -> dict:
    """Adapt thin-enrichment / legacy dicts to MarketOutlookScenario shape."""
    if not isinstance(item, dict):
        return {
            "scenario": "context",
            "label_ru": str(item),
            "probability": default_probability,
            "probability_pct": round(default_probability * 100, 1),
            "engine": default_engine,
        }

    if item.get("scenario") and item.get("label_ru") is not None and item.get("engine"):
        prob = float(item.get("probability", default_probability))
        normalized = {
            "scenario": str(item["scenario"]),
            "label_ru": str(item["label_ru"]),
            "probability": prob,
            "probability_pct": float(item.get("probability_pct", round(prob * 100, 1))),
            "engine": str(item["engine"]),
        }
        if item.get("high_confidence") is not None:
            normalized["high_confidence"] = item["high_confidence"]
        return normalized

    if item.get("title"):
        title = str(item["title"])
        conf_pct = item.get("confidence_pct")
        prob = float(conf_pct / 100) if conf_pct is not None else default_probability
        engine = str(item.get("how") or item.get("engine") or default_engine)
        if len(engine) > 40:
            engine = default_engine
        return {
            "scenario": slug_scenario(title),
            "label_ru": title,
            "probability": prob,
            "probability_pct": round(prob * 100, 1),
            "engine": engine,
        }

    if item.get("label") or item.get("label_ru"):
        label_ru = str(item.get("label_ru") or item.get("label") or "Сценарий")
        prob = float(item.get("probability", default_probability))
        normalized = {
            "scenario": str(item.get("label") or slug_scenario(label_ru)),
            "label_ru": label_ru,
            "probability": prob,
            "probability_pct": float(item.get("probability_pct", round(prob * 100, 1))),
            "engine": str(item.get("engine", default_engine)),
        }
        if item.get("high_confidence") is not None:
            normalized["high_confidence"] = item["high_confidence"]
        return normalized

    text = str(item.get("what_happens") or item.get("text") or "Контекст")
    return {
        "scenario": "context",
        "label_ru": text,
        "probability": default_probability,
        "probability_pct": round(default_probability * 100, 1),
        "engine": default_engine,
    }
