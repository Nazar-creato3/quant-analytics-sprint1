"""Structured forecast enrichment — deepen thin daily-builder sections."""
from __future__ import annotations

from typing import Any

from app.schemas.forecast import StructuredForecastSections
from app.services.analysis.context import AnalysisContext, format_factor_snippet
from app.services.forecast.outlook_normalize import normalize_market_outlook_item
from app.services.forecast.outlook_normalize import slug_scenario
from app.services.prediction_hierarchy.narrator import _ACTION_RU
from app.services.prediction_hierarchy.types import ForecastOutput


def _outlook_item(
    title: str,
    what_happens: str,
    *,
    engine: str = "ForecastEngine",
    probability: float | None = None,
) -> dict[str, Any]:
    prob = 0.5 if probability is None else probability
    slug = slug_scenario(title)
    return {
        "scenario": slug,
        "label_ru": title,
        "probability": round(prob, 4),
        "probability_pct": round(prob * 100, 1),
        "engine": engine,
        "what_happens": what_happens,
    }


def enrich_structured_forecast(
    structured: StructuredForecastSections | None,
    *,
    hierarchy: ForecastOutput,
    payload: dict[str, Any] | None,
    analysis: AnalysisContext,
    narrator_texts: list[str],
    disclosure,
    symbol: str,
) -> StructuredForecastSections:
    """Add depth from hierarchy, macro, news, factors, and scenarios when sections are sparse."""
    if structured is None:
        structured = StructuredForecastSections()

    outlook = list(structured.market_outlook or [])
    actionable = list(structured.actionable_summary or [])
    sector_risks = list(structured.sector_risks or [])
    tail_events = list(structured.tail_risk_events or [])
    engines = set(structured.engines_used or [])

    thin = len(outlook) + len(actionable) < 3

    action = hierarchy.action_forecast.recommendation
    action_ru = _ACTION_RU.get(action, action.value.replace("_", " "))
    conf = hierarchy.calibrated_confidence
    summary_line = (
        f"{symbol}: {action_ru} (уверенность {conf:.0%}); "
        f"интервал {hierarchy.interval_forecast.p10:+.1%}…{hierarchy.interval_forecast.p90:+.1%}"
    )
    if summary_line not in actionable:
        actionable.insert(0, summary_line)

    if thin and hierarchy.instruction_block:
        line = hierarchy.instruction_block.strip()
        if line and line not in actionable:
            actionable.append(line)

    if thin and narrator_texts:
        for text in narrator_texts[:3]:
            item = _outlook_item(symbol, text, probability=conf)
            if item not in outlook:
                outlook.append(item)

    if analysis.macro_snippet:
        macro_item = _outlook_item(
            "Макро-контекст",
            analysis.macro_snippet,
            engine="MacroRegistry",
            probability=conf,
        )
        if macro_item not in outlook:
            outlook.append(macro_item)
        engines.add("MacroRegistry")

    if analysis.eu_macro_snippet:
        eu_item = _outlook_item(
            "Еврозона (Eurostat)",
            analysis.eu_macro_snippet,
            engine="MacroRegistry",
            probability=conf,
        )
        if eu_item not in outlook:
            outlook.append(eu_item)
        engines.add("MacroRegistry")

    factor_line = format_factor_snippet(analysis.factor_exposures)
    if factor_line and factor_line not in actionable:
        actionable.append(factor_line)
        engines.add("FactorEngine")

    if hierarchy.global_regime:
        regime = hierarchy.global_regime.dominant_regime.replace("_", " ")
        regime_line = (
            f"Глобальный режим: {regime} "
            f"(уверенность {hierarchy.global_regime.confidence:.0%}, GlobalMacroRegimeEngine)."
        )
        if regime_line not in actionable:
            actionable.append(regime_line)
        outlook.append(
            _outlook_item(
                "Режим рынка",
                regime_line,
                engine="GlobalMacroRegimeEngine",
                probability=hierarchy.global_regime.confidence,
            )
        )
        engines.add("GlobalMacroRegimeEngine")

    if hierarchy.sector_regime:
        sr = hierarchy.sector_regime
        sector_line = (
            f"Сектор {sr.sector}: ротация {sr.rotation.rotation_flag.value.replace('_', ' ')}, "
            f"оценка {sr.rotation.composite_score:.3f}, импульс {sr.sector_momentum:.2f}."
        )
        outlook.append(
            _outlook_item(
                f"Сектор {sr.sector}",
                sector_line,
                engine="SectorRegimeEngine",
                probability=min(1.0, abs(sr.rotation.composite_score) + 0.2),
            )
        )
        engines.add("SectorRegimeEngine")

    if analysis.news_headlines:
        news_bits = "; ".join(
            f"«{h.title[:100]}»"
            + (
                f" [{h.sentiment_label}]"
                if h.sentiment_label and h.sentiment_label != "neutral"
                else ""
            )
            for h in analysis.news_headlines[:3]
        )
        sentiment_note = ""
        if analysis.news_sentiment:
            ns = analysis.news_sentiment
            sentiment_note = (
                f" Тональность: +{ns.positive}/−{ns.negative}/≈{ns.neutral}"
                f" (avg {ns.avg_score:+.2f})."
            )
        outlook.append(
            _outlook_item(
                "Новости",
                f"Релевантные заголовки по {symbol}: {news_bits}.{sentiment_note}",
                engine="NewsAggregator",
                probability=min(1.0, len(analysis.news_headlines) * 0.15),
            )
        )
        engines.add("NewsAggregator")
        if analysis.news_sentiment:
            ns = analysis.news_sentiment
            sentiment_line = (
                f"NewsAggregator: тональность +{ns.positive}/−{ns.negative}/≈{ns.neutral} "
                f"(avg {ns.avg_score:+.2f})."
            )
            if sentiment_line not in actionable:
                actionable.append(sentiment_line)

    if analysis.event_risk:
        er = analysis.event_risk
        tail_events.append(
            {
                "label": "event_risk_window",
                "label_ru": "Событийный/новостной риск",
                "probability": round(min(1.0, er.news_impact_probability), 4),
                "probability_pct": round(er.news_impact_probability * 100, 1),
                "engine": "EventRiskLayer",
                "symbol": symbol,
            }
        )
        if er.reason and er.reason not in actionable:
            actionable.append(f"EventRiskLayer: {er.reason}")
        engines.add("EventRiskLayer")

    scenarios = hierarchy.scenario_forecast.scenarios if hierarchy.scenario_forecast else ()
    narrative = [s for s in scenarios if s.scenario_type in {"pessimistic", "realistic", "optimistic", "classic"}]
    if thin and narrative:
        top = sorted(narrative, key=lambda s: s.probability, reverse=True)[:2]
        for sc in top:
            narrative_ru = sc.impact_narrative_ru or sc.label_ru
            if narrative_ru:
                outlook.append(
                    _outlook_item(
                        f"Сценарий: {sc.label_ru}",
                        f"{narrative_ru} (вероятность {sc.probability:.0%}, ScenarioEngine).",
                        engine="ScenarioEngine",
                        probability=sc.probability,
                    )
                )
        engines.add("ScenarioEngine")

    risk_summary = hierarchy.risk_forecast.plain_language_summary.strip()
    if risk_summary and risk_summary not in actionable:
        actionable.append(risk_summary)

    for item in hierarchy.risk_forecast.risk_items[:3]:
        summary = item.plain_language_summary.strip()
        if summary and summary not in actionable:
            actionable.append(summary)

    disclosure_summary = getattr(disclosure, "executive_summary", None) or (
        disclosure.to_dict().get("executive_summary") if disclosure else None
    )
    if thin and disclosure_summary and disclosure_summary not in actionable:
        actionable.append(str(disclosure_summary))

    if payload:
        for item in (payload.get("sector_opportunities") or [])[:2]:
            if isinstance(item, dict):
                title = item.get("title") or item.get("label_ru") or item.get("text")
                if title and not any(
                    isinstance(o, dict) and o.get("what_happens") == title for o in outlook
                ):
                    outlook.append(item if "what_happens" in item else _outlook_item(str(title), str(title)))

    if analysis.data_gaps:
        gap_note = (
            "Ограничения данных (не хватает для более глубокого анализа): "
            + "; ".join(analysis.data_gaps[:4])
        )
        if len(analysis.data_gaps) > 4:
            gap_note += f" (+ещё {len(analysis.data_gaps) - 4})"
        if gap_note not in actionable:
            actionable.append(gap_note)

    if hierarchy.basis_block:
        for block in hierarchy.basis_block[:2]:
            conclusion = (block.conclusion_ru or "").strip()
            if conclusion and len(conclusion) > 20:
                item = _outlook_item(
                    f"Слой {block.layer}",
                    conclusion,
                    engine=str(block.engine),
                    probability=conf,
                )
                if item not in outlook:
                    outlook.append(item)

    engines.update(structured.engines_used or [])
    if payload and payload.get("engines_used"):
        engines.update(payload["engines_used"])

    default_prob = hierarchy.calibrated_confidence
    normalized_outlook = [
        normalize_market_outlook_item(item, default_probability=default_prob)
        for item in outlook
    ]

    return StructuredForecastSections(
        market_outlook=normalized_outlook,
        sector_opportunities=list(structured.sector_opportunities or []),
        sector_risks=sector_risks,
        regime_forecast=structured.regime_forecast or {},
        tail_risk_events=tail_events,
        actionable_summary=actionable,
        high_confidence_predictions=list(structured.high_confidence_predictions or []),
        engines_used=sorted(engines),
    )
