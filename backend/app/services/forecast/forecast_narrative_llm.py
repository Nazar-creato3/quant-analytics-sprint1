"""Optional LLM narrative for forecast pages — numbers stay from hierarchy/disclosure."""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.core.config import settings
from app.core.logging import get_logger

if TYPE_CHECKING:
    from app.services.prediction_hierarchy.types import ForecastOutput

logger = get_logger(__name__)

_FORECAST_COMPACT_SYSTEM = (
    "Ты — старший аналитик Quant Analytics. Пиши FORECAST COMPACT MODE для UI строго по-русски. "
    "Лимит 90–120 слов. Без вступления и дисклеймеров. "
    "Ровно четыре строки с префиксами (копируй префиксы дословно):\n"
    "Вердикт - одно связное предложение: ведущий сценарий, вероятность и что это значит для позиции.\n"
    "Почему - одно–два предложения аналитическим прозой; встрой 2–3 числа из контекста "
    "(импульс, ход, волатильность, сектор или макро), без списков через «·» и без "
    "английских ярлыков (vol regime, expansion, momentum как отдельные токены).\n"
    "Что изменит взгляд - 1–2 полных предложения с конкретными порогами из контекста.\n"
    "Действие - одно предложение с рекомендацией модели по-русски (ожидание, снижение размера и т.д.).\n"
    "Приоритет сигналов: импульс инструмента > режим/волатильность > сектор > макро > хвост > ликвидность. "
    "Не повторяй макро, если оно не меняет решение. Не выдумывай факты и новости — только переданный контекст. "
    "Честность метрик: если упоминаешь точность модели — только «точность классификации режима (тест)», "
    "не «точность направления» и не «directional accuracy». "
    "Запрещены шаблонная вода и param-dump: текущий контекст, важно отметить, probability soup, "
    "vol regime, expansion 0%, may be, could be."
    "Стиль — официально-деловой русский: без разговорных оборотов и сравнений («как подбросить монету», «рынок нервный», «цена скачет»); 50% называй «шансы 50 на 50». "
)

_FORECAST_ANALYST_SYSTEM = (
    "Ты — старший аналитик Quant Analytics внутри приложения. Пиши по-русски прямым "
    "аналитическим текстом: сначала вывод, затем почему именно так, затем риски и что "
    "отслеживать на горизонте прогноза. Не используй таблицы или обязательную структуру "
    "из семи разделов. "
    "Опирайся только на переданный контекст: иерархию forecast, интервальный прогноз, "
    "сценарные архетипы, macro/global regime, sector rotation, disclosure и риск-метрики. "
    "Не меняй вероятности, интервалы, рекомендации и названия сценариев; если точных "
    "новостей нет, не пиши отказ и не говори «insufficient news» — объясняй прогноз через "
    "иерархию, макро-режим, сценарии и диапазон исходов. "
    "Честность метрик: точность модели — только «точность классификации режима (тест)», "
    "не «точность направления» и не «directional accuracy». "
    "Не давай прямых советов «купить/продать»; формулируй как интерпретацию сценариев, "
    "рисков и условий подтверждения/опровержения."
    "Стиль — официально-деловой русский: без разговорных оборотов и сравнений («как подбросить монету», «рынок нервный», «цена скачет»); 50% называй «шансы 50 на 50». "
)

_FORECAST_COMPACT_USER_PROMPT = (
    "Сожми прогноз в FORECAST COMPACT MODE. Строго четыре строки: "
    "«Вердикт -», «Почему -», «Что изменит взгляд -», «Действие -»; лимит 90–120 слов. "
    "Текст — связные аналитические предложения, не перечень параметров через дефис."
)

_MARKET_HUMAN_SYSTEM = (
    "Ты пишешь «картину рынка» для обычного человека на русском. "
    "3–5 коротких абзацев. Живой язык, как разговор с клиентом за столом, не отчёт движка. "
    "Запрещены: названия классов и функций (GlobalMacroRegimeEngine, SectorRegimeEngine, "
    "prediction_hierarchy), английские ярлыки (risk-on, CPI proxy, б.п., OHLCV), дисклеймеры "
    "про прибыль и вероятности. "
    "Цифры только здравые: инфляция 0–20%, VIX 8–80, рост ВВП −5…10. Если цифра выглядит сломанной "
    "(например инфляция 300%) — не пиши её, опиши смысл словами. "
    "Не выдумывай новости. Только переданный контекст и tool-данные."
)

_MARKET_HUMAN_USER_PROMPT = (
    "Перескажи рыночную сводку человеческим языком: что происходит с рынком в целом, "
    "какой фон по страху и инфляции, какие отрасли сильнее, и что из этого следует на ближайшие недели. "
    "Без списков через точку с запятой и без имён внутренних модулей."
)

_COMPACT_LAYER_MARKERS: tuple[tuple[str, ...], ...] = (
    ("вердикт -", "verdict -"),
    ("почему -", "why -"),
    ("что изменит взгляд -", "what would change the view -", "что изменит -"),
    ("действие -", "action -"),
)


def split_compact_narrative_layers(text: str) -> list[str] | None:
    """Parse LLM compact forecast into four UI paragraphs; None if structure missing."""
    if not text or not text.strip():
        return None
    normalized = text.replace("\r\n", "\n").strip()
    lines = [ln.strip() for ln in normalized.split("\n") if ln.strip()]
    if not lines:
        return None

    joined_lower = normalized.lower()
    found: list[str | None] = [None, None, None, None]
    for idx, variants in enumerate(_COMPACT_LAYER_MARKERS):
        for variant in variants:
            pos = joined_lower.find(variant)
            if pos >= 0:
                start = pos + len(variant)
                end = len(normalized)
                for later_idx in range(idx + 1, len(_COMPACT_LAYER_MARKERS)):
                    for later in _COMPACT_LAYER_MARKERS[later_idx]:
                        later_pos = joined_lower.find(later, start)
                        if later_pos >= 0:
                            end = min(end, later_pos)
                chunk = normalized[start:end].strip(" \n-—")
                if chunk:
                    label = variants[0].replace(" -", "").strip()
                    found[idx] = f"{label[:1].upper()}{label[1:]} - {chunk}"
                break

    if all(found):
        return [str(item) for item in found]

    if len(lines) >= 4:
        return lines[:4]
    return None


def apply_llm_narrative_to_disclosure(
    disclosure: dict[str, Any],
    llm_text: str,
) -> dict[str, Any]:
    """Replace template disclosure paragraphs when LLM returned a valid 4-layer compact card."""
    layers = split_compact_narrative_layers(llm_text)
    if not layers:
        return disclosure
    updated = dict(disclosure)
    updated["paragraphs"] = layers
    engines = list(updated.get("engines_used") or [])
    if "LLMForecastNarrative" not in engines:
        engines.append("LLMForecastNarrative")
    updated["engines_used"] = engines
    return updated

_FORECAST_ANALYST_USER_PROMPT = (
    "Сформируй связное резюме прогноза для инвестора на основе контекста. "
    "Ответ должен быть цельным аналитическим текстом на 3–6 абзацев, не списком. "
    "Обязательно свяжи: направление/рекомендацию модели, интервал P10/P50/P90, "
    "ключевой сценарий или архетип, macro/global regime и главные риски."
)

_MARKET_ANALYST_USER_PROMPT = (
    "Сформируй связное резюме рыночного прогноза для человека без жаргона. "
    "Общий фон, что вероятнее, какие отрасли впереди, какие риски. Цельный текст, без dump чисел."
)


def _forecast_mode() -> str:
    mode = str(getattr(settings, "FORECAST_MODE", "compact") or "compact").strip().lower()
    return mode if mode in {"compact", "analyst"} else "compact"


def _hierarchy_grounding(hierarchy: "ForecastOutput", symbol: str) -> str:
    interval = hierarchy.interval_forecast
    distribution = hierarchy.distribution_forecast
    action = hierarchy.action_forecast.recommendation.value
    conf = hierarchy.calibrated_confidence
    interval_parts = [
        f"P10 {interval.p10:+.1%}",
        f"P90 {interval.p90:+.1%}",
    ]
    if distribution is not None:
        interval_parts.insert(1, f"P50 {distribution.p50:+.1%}")
    lines = [
        f"Символ: {symbol}",
        f"as_of: {hierarchy.as_of}",
        f"Действие модели: {action}",
        f"Калиброванная уверенность: {conf:.0%}",
        f"Интервал прогноза (~{interval.horizon_days}д): "
        f"{', '.join(interval_parts)}, vol {interval.rolling_volatility:.1%}",
    ]
    if hierarchy.global_regime:
        lines.append(
            f"Глобальный режим: {hierarchy.global_regime.dominant_regime} "
            f"(conf {hierarchy.global_regime.confidence:.0%})"
        )
    if hierarchy.scenario_forecast and hierarchy.scenario_forecast.scenarios:
        sc_lines = []
        for sc in hierarchy.scenario_forecast.scenarios[:4]:
            impact = getattr(sc, "expected_impact", None)
            impact_part = f", impact {impact:+.1%}" if isinstance(impact, int | float) else ""
            label = getattr(sc, "label_ru", None) or getattr(sc, "name", "")
            sc_lines.append(f"{label}: {sc.probability:.0%}{impact_part}")
        lines.append("Сценарии: " + "; ".join(sc_lines))
    risk = hierarchy.risk_forecast.plain_language_summary.strip()
    if risk:
        lines.append(f"Риск (модель): {risk[:400]}")
    return "\n".join(lines)


def _disclosure_grounding(disclosure: dict[str, Any], *, include_layers: bool = False) -> str:
    lines: list[str] = []
    paragraphs = disclosure.get("paragraphs") or []
    if paragraphs:
        lines.append("Сценарное раскрытие:")
        lines.extend(f"- {p}" for p in paragraphs[:6])

    top = disclosure.get("top_scenario")
    top_prob = disclosure.get("top_probability")
    second = disclosure.get("second_scenario")
    second_prob = disclosure.get("second_probability")
    if top:
        top_line = f"Ведущий архетип: {top}"
        if isinstance(top_prob, int | float):
            top_line += f" ({top_prob:.1%})"
        if second:
            top_line += f"; второй: {second}"
            if isinstance(second_prob, int | float):
                top_line += f" ({second_prob:.1%})"
        lines.append(top_line)

    breakdown = disclosure.get("breakdown") or {}
    if isinstance(breakdown, dict) and breakdown:
        parts = [
            f"{key}={value:.1%}"
            for key, value in breakdown.items()
            if isinstance(value, int | float)
        ]
        if parts:
            lines.append("Архетипы: " + ", ".join(parts[:6]))

    scenarios = disclosure.get("scenarios") or []
    scenario_lines: list[str] = []
    for item in scenarios[:4]:
        if not isinstance(item, dict):
            continue
        name = item.get("label_ru") or item.get("name") or item.get("scenario")
        probability = item.get("probability")
        if not name:
            continue
        prob_part = f" {probability:.1%}" if isinstance(probability, int | float) else ""
        scenario_lines.append(f"{name}{prob_part}")
    if scenario_lines:
        lines.append("Сценарии disclosure: " + "; ".join(scenario_lines))

    layers = disclosure.get("layers") or {}
    if include_layers and isinstance(layers, dict) and layers:
        lines.append(f"Слои disclosure: {layers}")

    evidence = disclosure.get("evidence") or []
    if evidence:
        lines.append("Evidence disclosure: " + "; ".join(str(item) for item in evidence[:6]))

    return "\n".join(lines)


def _dict_lines(title: str, payload: dict[str, Any] | None, *, limit: int = 12) -> str:
    if not payload:
        return ""
    items = []
    for key, value in payload.items():
        if value is None:
            continue
        items.append(f"{key}={value}")
        if len(items) >= limit:
            break
    return f"{title}: " + ", ".join(items) if items else ""


def _market_collection_lines(title: str, values: list[Any] | tuple[Any, ...] | None, *, limit: int = 5) -> str:
    if not values:
        return ""
    rendered: list[str] = []
    for item in values[:limit]:
        if isinstance(item, dict):
            rendered.append(str({key: item[key] for key in list(item.keys())[:8]}))
        else:
            rendered.append(str(item))
    return f"{title}:\n" + "\n".join(f"- {item}" for item in rendered)


async def try_llm_forecast_narrative(
    *,
    symbol: str,
    hierarchy: "ForecastOutput",
    disclosure: dict[str, Any],
) -> str | None:
    """Synthesize a short narrative grounded in existing forecast payload; None if LLM off/failed."""
    from app.services.llm.llm_service import LLMService, llm_enabled

    if not llm_enabled():
        return None

    context_parts = [
        _hierarchy_grounding(hierarchy, symbol),
        _disclosure_grounding(disclosure, include_layers=_forecast_mode() == "analyst"),
    ]
    context = "\n\n".join(p for p in context_parts if p.strip())
    if not context.strip():
        return None

    mode = _forecast_mode()
    system = _FORECAST_COMPACT_SYSTEM if mode == "compact" else _FORECAST_ANALYST_SYSTEM
    prompt = _FORECAST_COMPACT_USER_PROMPT if mode == "compact" else _FORECAST_ANALYST_USER_PROMPT

    try:
        return await LLMService.complete(
            "forecast_narrative",
            prompt,
            system=system,
            context=context,
            temperature=0.45,
            max_tokens=420 if mode == "compact" else 1800,
        )
    except Exception as exc:
        from app.services.llm.errors import AITunnelUnavailableError

        if isinstance(exc, AITunnelUnavailableError):
            logger.warning("Forecast LLM narrative unavailable", symbol=symbol, error=str(exc))
        else:
            logger.warning("Forecast LLM narrative failed", symbol=symbol, error=str(exc))
        return None


async def try_llm_market_forecast_narrative(
    *,
    disclosure: dict[str, Any],
    global_regime: dict[str, Any],
    macro_indicators: dict[str, float] | None = None,
    market_outlook: list[dict[str, Any]] | None = None,
    sector_rotation: list[dict[str, Any]] | None = None,
    market_prediction_summary: dict[str, Any] | None = None,
    db: Any | None = None,
) -> str | None:
    from app.services.llm.llm_service import LLMService, llm_enabled

    if not llm_enabled():
        return None

    tool_blob = ""
    if db is not None:
        try:
            from app.services.chat.tools import execute_tool

            raw = await execute_tool(db, "get_market_regime", {})
            tool_blob = f"Данные tool get_market_regime (как в чате):\n{str(raw)[:4500]}"
        except Exception as exc:
            logger.debug("market_regime_tool_prefetch_failed", error=str(exc)[:160])

    macro_bits = []
    if macro_indicators:
        for key, value in macro_indicators.items():
            if value is None:
                continue
            if key in {"cpi", "wb_us_inflation"} and (value > 25 or value < -5):
                continue
            macro_bits.append(f"{key}={value}")
            if len(macro_bits) >= 16:
                break
    disclosure_text = _disclosure_grounding(disclosure, include_layers=True)
    summary_paras = None
    if isinstance(market_prediction_summary, dict):
        paras = market_prediction_summary.get("paragraphs")
        if isinstance(paras, list) and paras:
            summary_paras = "Черновик сводки:\n" + "\n".join(str(p) for p in paras[:8])
    context = "\n\n".join(
        part
        for part in [
            "Область: рынок в целом (MARKET)",
            tool_blob,
            _dict_lines("Глобальный режим", global_regime),
            disclosure_text,
            ("Макро: " + ", ".join(macro_bits)) if macro_bits else "",
            _market_collection_lines("Market outlook points", market_outlook),
            _market_collection_lines("Sector rotation", sector_rotation),
            summary_paras or "",
        ]
        if part and str(part).strip()
    ).strip()
    if not context:
        return None

    try:
        return await LLMService.complete(
            "forecast_narrative",
            _MARKET_HUMAN_USER_PROMPT,
            system=_MARKET_HUMAN_SYSTEM,
            context=context,
            temperature=0.45,
            max_tokens=900,
        )
    except Exception as exc:
        from app.services.llm.errors import AITunnelUnavailableError

        if isinstance(exc, AITunnelUnavailableError):
            logger.warning("Market forecast LLM narrative unavailable", error=str(exc))
        else:
            logger.warning("Market forecast LLM narrative failed", error=str(exc))
        return None
