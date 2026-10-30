"""LLM-generated scenario verdict (Вердикт/Почему/…) via shared tool-calling stack."""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
from typing import TYPE_CHECKING, Any, Mapping, Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.services.forecast.forecast_narrative_llm import split_compact_narrative_layers
from app.services.llm.llm_service import LLMService, llm_enabled
from app.utils.cache import cache_get, cache_set

if TYPE_CHECKING:
    from app.services.prediction_hierarchy.types import ForecastOutput

logger = get_logger(__name__)

CACHE_TTL_SECONDS = 3600
VERDICT_LLM_TIMEOUT_SEC = 45.0

_VERDICT_TOOL_NAMES: tuple[str, ...] = (
    "get_forecast_distribution",
    "get_risk_metrics",
    "get_market_regime",
    "get_rolling_accuracy",
    "get_factor_exposures",
)

_TEMPLATE_BOILERPLATE_MARKERS: tuple[str, ...] = (
    "импульс слабый или отрицательный, базовый расчётный ход около",
    "разумно снизить размер или не наращивать риск",
    "рекомендация модели: уменьшить размер позиции",
)

SCENARIO_VERDICT_SYSTEM_RU = """Ты объясняешь сценарный прогноз конкретного финансового инструмента человеку \
без специального образования.

Данные ниже уже получены через analytics tools — используй их, не выдумывай цифры.
Если в tool-данных is_valid=false или insufficient_data=true — скажи, что метрика недоступна.

Честность метрик (обязательно):
- «regime_match_accuracy» / «точность классификации режима» — совпадение классификации режима на walk-forward \
тесте, НЕ точность угадывания направления цены вверх/вниз.
- «aggregate_calibration_error» / «ошибка калибровки» — средняя ошибка калибровки на эталонных рядах, \
НЕ разрыв live vs backtest.
- ЗАПРЕЩЕНО писать «directional accuracy», «точность направления», «live vs backtest gap» — даже если \
видишь их в сырых данных (их там быть не должно).
- Если упоминаешь точность модели — только «точность классификации режима (тест)» с конкретным процентом.

Требования:
- Текст уникален для ЭТОГО тикера и ЭТИХ цифр — не повторяй одинаковые формулировки для разных активов
- Начни с главного вывода для этого инструмента, не с шаблонной структуры
- Простым языком, без канцелярита «Рекомендация модели: уменьшить размер позиции»
- Деловой стиль без разговорных оборотов и сравнений («как подбросить монету», «рынок нервный», «цена скачет»); 50% — «шансы 50 на 50»
- Объясни разницу: «уверенность» в шапке vs вероятность ведущего сценария — это разные метрики
- ЗАПРЕЩЕНО копировать фразы: «импульс слабый или отрицательный, базовый расчётный ход около»

Формат — ровно 4 строки, префиксы дословно:
Вердикт -
Почему -
Что изменит взгляд -
Действие -
"""


def verdict_data_fingerprint(
    symbol: str,
    hierarchy: "ForecastOutput",
    disclosure: dict[str, Any],
    *,
    drift_flag: bool = False,
) -> str:
    payload = {
        "symbol": symbol.upper(),
        "as_of": hierarchy.as_of,
        "calibrated_confidence": round(hierarchy.calibrated_confidence, 4),
        "scenarios": disclosure.get("scenarios"),
        "breakdown": disclosure.get("breakdown"),
        "top_scenario": disclosure.get("top_scenario"),
        "top_probability": disclosure.get("top_probability"),
        "expected_move": disclosure.get("expected_move"),
        "volatility_regime": disclosure.get("volatility_regime"),
        "risk_action": disclosure.get("risk_action"),
        "confidence": disclosure.get("confidence"),
        "drift_flag": drift_flag,
        "metric_honesty_v": 2,
    }
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:20]


def _cache_key(symbol: str, fingerprint: str) -> str:
    return f"forecast:scenario_verdict:{symbol.upper()}:{fingerprint}"


def tool_payload_from_hierarchy(
    hierarchy: "ForecastOutput",
    disclosure: dict[str, Any],
    *,
    live_direction_accuracy: Any | None = None,
    track_record: Any | None = None,
) -> dict[str, Any]:
    """Synthesize verdict tool JSON from already-built hierarchy — avoids 5× DB re-fetch."""
    interval = hierarchy.interval_forecast
    distribution = hierarchy.distribution_forecast
    risk_metrics = dict(hierarchy.risk_forecast.instrument_metrics or {})
    global_regime = hierarchy.global_regime
    sector = hierarchy.sector_regime

    distribution_payload: dict[str, Any] = {
        "symbol": hierarchy.symbol,
        "is_valid": interval is not None,
        "horizon_days": getattr(interval, "horizon_days", None),
        "p10": getattr(interval, "p10", None),
        "p90": getattr(interval, "p90", None),
        "p50": getattr(distribution, "p50", None) if distribution else None,
        "rolling_volatility": getattr(interval, "rolling_volatility", None),
        "calibrated_confidence": hierarchy.calibrated_confidence,
    }
    if hierarchy.action_forecast and hierarchy.action_forecast.recommendation:
        distribution_payload["action"] = hierarchy.action_forecast.recommendation.value

    rolling_payload: dict[str, Any] = {"symbol": hierarchy.symbol, "is_valid": False}
    if live_direction_accuracy is not None:
        rolling_payload = {
            "symbol": hierarchy.symbol,
            "is_valid": live_direction_accuracy.sample_size > 0,
            "accuracy": live_direction_accuracy.accuracy,
            "sample_size": live_direction_accuracy.sample_size,
            "ci_low": live_direction_accuracy.ci_low,
            "ci_high": live_direction_accuracy.ci_high,
            "horizon_days": live_direction_accuracy.horizon_days,
            "formatted_ru": live_direction_accuracy.formatted_ru,
        }

    track_payload: dict[str, Any] = {"is_valid": track_record is not None}
    if track_record is not None:
        track_payload = {
            "is_valid": True,
            "aggregate_calibration_error": getattr(
                track_record, "aggregate_calibration_error", None
            ),
            "drift_flag": getattr(track_record, "drift_flag", False),
            "rolling_accuracy": getattr(track_record, "rolling_accuracy", None),
        }

    factor_exposures = disclosure.get("breakdown") or {}
    if hierarchy.scenario_forecast:
        for sc in hierarchy.scenario_forecast.scenarios[:6]:
            label = getattr(sc, "label_ru", None) or getattr(sc, "name", None)
            if label:
                factor_exposures[str(label)] = sc.probability

    return {
        "get_forecast_distribution": distribution_payload,
        "get_risk_metrics": {
            "symbol": hierarchy.symbol,
            "is_valid": bool(risk_metrics),
            **risk_metrics,
            "plain_language_summary": hierarchy.risk_forecast.plain_language_summary,
        },
        "get_market_regime": {
            "is_valid": global_regime is not None,
            "dominant_regime": global_regime.dominant_regime if global_regime else None,
            "confidence": global_regime.confidence if global_regime else None,
            "sector": sector.sector if sector else None,
            "sector_momentum": sector.sector_momentum if sector else None,
        },
        "get_rolling_accuracy": rolling_payload,
        "get_factor_exposures": {
            "symbol": hierarchy.symbol,
            "is_valid": bool(factor_exposures),
            "factor_exposures": factor_exposures,
        },
        "track_record": track_payload,
    }


def _format_regime_accuracy_lines(
    rolling_regime_accuracy: Sequence[Mapping[str, Any]] | None,
) -> list[str]:
    if not rolling_regime_accuracy:
        return []
    lines = ["Track record (walk-forward, тест):"]
    for point in rolling_regime_accuracy[:3]:
        window = point.get("window_days")
        accuracy = point.get("regime_match_accuracy", point.get("directional_accuracy"))
        mae = point.get("mae")
        if not isinstance(accuracy, int | float):
            continue
        window_part = f"{window}d" if window is not None else "window"
        line = (
            f"  {window_part}: точность классификации режима {accuracy:.1%}"
        )
        if isinstance(mae, int | float):
            line += f", ошибка калибровки {mae:.3f}"
        lines.append(line)
    return lines


def _build_structured_context(
    symbol: str,
    hierarchy: "ForecastOutput",
    disclosure: dict[str, Any],
    *,
    drift_flag: bool = False,
    aggregate_calibration_error: float | None = None,
    rolling_regime_accuracy: Sequence[Mapping[str, Any]] | None = None,
) -> str:
    lines = [
        f"Тикер: {symbol}",
        f"as_of: {hierarchy.as_of}",
        (
            f"Уверенность модели (шапка UI): {hierarchy.calibrated_confidence:.1%} "
            "— НЕ вероятность одного сценария."
        ),
    ]
    if disclosure.get("top_scenario"):
        top_p = disclosure.get("top_probability")
        top_line = f"Ведущий сценарий: {disclosure['top_scenario']}"
        if isinstance(top_p, int | float):
            top_line += f" ({top_p:.1%} — вероятность архетипа)"
        lines.append(top_line)

    for item in disclosure.get("scenarios") or []:
        if not isinstance(item, dict):
            continue
        label = item.get("label_ru") or item.get("archetype")
        prob = item.get("probability")
        impact = item.get("impact")
        if label and isinstance(prob, int | float):
            impact_part = f", impact {impact:+.1%}" if isinstance(impact, int | float) else ""
            lines.append(f"  {label}: {prob:.1%}{impact_part}")

    breakdown = disclosure.get("breakdown") or {}
    if breakdown:
        parts = [f"{k}={v:.1%}" for k, v in breakdown.items() if isinstance(v, int | float)]
        if parts:
            lines.append("Attribution: " + ", ".join(parts))

    if isinstance(disclosure.get("expected_move"), int | float):
        lines.append(f"Expected move: {disclosure['expected_move']:+.2%}")
    if disclosure.get("volatility_regime"):
        lines.append(f"Vol regime: {disclosure['volatility_regime']}")
    if disclosure.get("risk_action"):
        lines.append(f"Action rule: {disclosure['risk_action']}")

    interval = hierarchy.interval_forecast
    lines.append(
        f"Interval {interval.horizon_days}d: P10 {interval.p10:+.1%}, P90 {interval.p90:+.1%}"
    )
    if hierarchy.point_forecast:
        lines.append(f"Momentum score: {hierarchy.point_forecast.momentum_score:.2f}")

    lines.extend(_format_regime_accuracy_lines(rolling_regime_accuracy))

    if aggregate_calibration_error is not None:
        lines.append(
            "Средняя ошибка калибровки на эталонных рядах (aggregate_calibration_error): "
            f"{aggregate_calibration_error:.3f}"
        )

    if drift_flag:
        err = (
            f" ({aggregate_calibration_error:.3f})"
            if aggregate_calibration_error is not None
            else ""
        )
        lines.append(
            f"WARNING: повышенная ошибка калибровки на эталонных рядах{err} — "
            "интерпретируйте прогнозы осторожнее"
        )

    return "\n".join(lines)


def shared_multiword_phrases(text_a: str, text_b: str, *, min_words: int = 4) -> list[str]:
    def tokens(text: str) -> list[str]:
        return re.findall(r"[\wа-яё]+", text.lower(), flags=re.IGNORECASE)

    words_a = tokens(text_a)
    words_b = tokens(text_b)
    shared: list[str] = []
    for length in range(min(len(words_a), len(words_b)), min_words - 1, -1):
        for i in range(len(words_a) - length + 1):
            phrase = " ".join(words_a[i : i + length])
            if phrase in " ".join(words_b):
                shared.append(phrase)
        if shared:
            break
    return shared[:5]


def _looks_like_template_boilerplate(text: str) -> bool:
    lower = text.lower()
    return any(marker in lower for marker in _TEMPLATE_BOILERPLATE_MARKERS)


def parse_verdict_layers(raw: str) -> list[str] | None:
    """Parse LLM output into four UI paragraphs; tolerant of minor format drift."""
    layers = split_compact_narrative_layers(raw)
    if layers and len(layers) >= 4:
        return layers[:4]

    normalized = raw.replace("\r\n", "\n").strip()
    prefix_patterns = [
        r"^вердикт\s*[-–—:]",
        r"^почему\s*[-–—:]",
        r"^что изменит",
        r"^действие\s*[-–—:]",
    ]
    lines = [ln.strip() for ln in normalized.split("\n") if ln.strip()]
    if len(lines) >= 4:
        matched = 0
        for i, pat in enumerate(prefix_patterns):
            if i < len(lines) and re.search(pat, lines[i], re.IGNORECASE):
                matched += 1
        if matched >= 3:
            return lines[:4]
    return None


async def _prefetch_verdict_tools(db: AsyncSession, symbol: str) -> dict[str, Any]:
    """Run forecast tools once in parallel — same data layer as in-app chat."""
    from app.services.chat.tools import execute_tool
    from app.services.forecast.numeric_integrity import sanitize_tool_payload_for_llm

    async def _one(name: str) -> tuple[str, Any]:
        args: dict[str, Any] = {"ticker": symbol}
        try:
            raw = await execute_tool(db, name, args)
            payload = json.loads(raw)
            if isinstance(payload, dict):
                payload = sanitize_tool_payload_for_llm(name, payload)
            return name, payload
        except Exception as exc:
            return name, {"error": str(exc)}

    results = await asyncio.gather(*[_one(name) for name in _VERDICT_TOOL_NAMES])
    return dict(results)


async def _run_verdict_llm(*, symbol: str, context: str, tool_payload: dict[str, Any]) -> str | None:
    """Single LLM call with pre-fetched tool JSON — avoids multi-round timeout."""
    tool_block = json.dumps(tool_payload, ensure_ascii=False, default=str)[:12000]
    user_prompt = (
        f"Сгенерируй сценарный вердикт для {symbol}. "
        "Четыре строки с префиксами Вердикт-/Почему-/Что изменит взгляд-/Действие-."
    )
    full_context = f"{context}\n\n--- Tool results (JSON) ---\n{tool_block}"

    try:
        return await asyncio.wait_for(
            LLMService.complete(
                "forecast_narrative",
                user_prompt,
                system=SCENARIO_VERDICT_SYSTEM_RU,
                context=full_context,
                temperature=0.62,
                max_tokens=720,
            ),
            timeout=VERDICT_LLM_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError:
        logger.warning("Scenario verdict LLM timed out", symbol=symbol)
        return None
    except Exception as exc:
        logger.warning("Scenario verdict LLM failed", symbol=symbol, error=str(exc))
        return None


async def try_generate_scenario_verdict(
    db: AsyncSession,
    *,
    symbol: str,
    hierarchy: "ForecastOutput",
    disclosure: dict[str, Any],
    drift_flag: bool = False,
    aggregate_calibration_error: float | None = None,
    live_vs_backtest_gap: float | None = None,
    rolling_regime_accuracy: Sequence[Mapping[str, Any]] | None = None,
    tool_payload: dict[str, Any] | None = None,
) -> list[str] | None:
    """Generate four verdict paragraphs; cached per ticker until underlying data changes."""
    if not llm_enabled():
        logger.info("Scenario verdict skipped — LLM disabled", symbol=symbol)
        return None

    fingerprint = verdict_data_fingerprint(
        symbol,
        hierarchy,
        disclosure,
        drift_flag=drift_flag,
    )
    cache_key = _cache_key(symbol, fingerprint)
    cached = await cache_get(cache_key)
    if isinstance(cached, dict) and cached.get("paragraphs"):
        paragraphs = list(cached["paragraphs"])
        if not _looks_like_template_boilerplate(" ".join(paragraphs)):
            return paragraphs
        logger.warning("Scenario verdict cache contained template boilerplate — regenerating", symbol=symbol)

    cal_error = aggregate_calibration_error if aggregate_calibration_error is not None else live_vs_backtest_gap
    context = _build_structured_context(
        symbol,
        hierarchy,
        disclosure,
        drift_flag=drift_flag,
        aggregate_calibration_error=cal_error,
        rolling_regime_accuracy=rolling_regime_accuracy,
    )

    tool_payload = tool_payload or await _prefetch_verdict_tools(db, symbol)
    raw = await _run_verdict_llm(symbol=symbol, context=context, tool_payload=tool_payload)
    if not raw:
        return None

    layers = parse_verdict_layers(raw)
    if not layers or len(layers) < 4:
        logger.warning(
            "Scenario verdict LLM returned invalid structure",
            symbol=symbol,
            raw_preview=raw[:200],
        )
        return None

    joined = " ".join(layers)
    if _looks_like_template_boilerplate(joined):
        logger.warning(
            "Scenario verdict LLM echoed template boilerplate — rejected",
            symbol=symbol,
        )
        return None

    await cache_set(
        cache_key,
        {"paragraphs": layers, "fingerprint": fingerprint, "source": "llm"},
        CACHE_TTL_SECONDS,
    )
    logger.info("Scenario verdict generated via LLM", symbol=symbol, fingerprint=fingerprint)
    return layers
