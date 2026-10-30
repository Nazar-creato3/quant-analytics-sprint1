"""Server-side numeric-integrity validation for forecast tool responses."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from app.core.logging import get_logger
from app.services.forecast.distribution import DIRECTIONAL_SIGNAL_THRESHOLD, WEAK_SIGNAL_THRESHOLD

logger = get_logger(__name__)

ETF_INDEX_PAIRS: dict[str, str] = {
    "SPY": "^GSPC",
    "^GSPC": "SPY",
    "QQQ": "^IXIC",
    "^IXIC": "QQQ",
    "DIA": "^DJI",
    "^DJI": "DIA",
    "IWM": "^RUT",
    "^RUT": "IWM",
}

MIN_ETF_INDEX_CORR = 0.9


@dataclass(frozen=True, slots=True)
class IntegrityViolation:
    code: str
    message: str
    severity: str = "error"

    def to_dict(self) -> dict[str, str]:
        return {"code": self.code, "message": self.message, "severity": self.severity}


@dataclass
class IntegrityReport:
    ok: bool
    violations: list[IntegrityViolation] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "violations": [v.to_dict() for v in self.violations],
            "flags": list(self.flags),
        }


def _etf_index_correlation_violations(
    matrix: Mapping[str, Mapping[str, float]],
) -> list[IntegrityViolation]:
    violations: list[IntegrityViolation] = []
    seen: set[tuple[str, str]] = set()
    for etf, index in ETF_INDEX_PAIRS.items():
        pair = tuple(sorted((etf, index)))
        if pair in seen:
            continue
        seen.add(pair)
        if etf not in matrix or index not in matrix:
            continue
        corr = matrix.get(etf, {}).get(index)
        if corr is None:
            corr = matrix.get(index, {}).get(etf)
        if corr is None:
            continue
        if corr < MIN_ETF_INDEX_CORR:
            violations.append(
                IntegrityViolation(
                    code="etf_index_correlation_low",
                    message=f"{etf}/{index} correlation {corr:.3f} below {MIN_ETF_INDEX_CORR}",
                )
            )
    return violations


def _rolling_accuracy_violations(
    points: Sequence[Mapping[str, Any]],
) -> list[IntegrityViolation]:
    if len(points) < 2:
        return []
    accuracies = [
        float(p.get("regime_match_accuracy", p.get("directional_accuracy", 0)))
        for p in points
    ]
    maes = [float(p.get("mae", 0)) for p in points]
    violations: list[IntegrityViolation] = []
    if len(set(round(a, 4) for a in accuracies)) == 1 and len(set(round(m, 4) for m in maes)) > 1:
        violations.append(
            IntegrityViolation(
                code="identical_accuracy_differing_mae",
                message="Rolling accuracy identical across windows with differing MAE",
            )
        )
    return violations


def _distribution_violations(payload: Mapping[str, Any]) -> list[IntegrityViolation]:
    violations: list[IntegrityViolation] = []
    flags: list[str] = []
    strength = float(payload.get("signal_strength", 0))
    direction = str(payload.get("point_direction", "neutral"))
    p10 = float(payload.get("p10", 0))
    p90 = float(payload.get("p90", 0))
    symmetric = abs(p10 + p90) < 1e-5 or abs(abs(p10) - abs(p90)) < 1e-5
    low_conf = bool(payload.get("low_confidence", False))

    if direction in {"increase", "decrease"} and strength >= DIRECTIONAL_SIGNAL_THRESHOLD and symmetric:
        violations.append(
            IntegrityViolation(
                code="directional_symmetric_interval",
                message=(
                    f"Directional call ({direction}, strength {strength:.0%}) "
                    "paired with symmetric interval"
                ),
            )
        )
    if strength < WEAK_SIGNAL_THRESHOLD and direction != "neutral" and not low_conf:
        violations.append(
            IntegrityViolation(
                code="weak_signal_no_flag",
                message=f"Weak signal ({strength:.0%}) without low_confidence flag",
                severity="warning",
            )
        )
    return violations


def validate_tool_response(tool_name: str, payload: Mapping[str, Any]) -> IntegrityReport:
    """Run numeric-integrity checks on a tool response before it reaches the LLM or UI."""
    violations: list[IntegrityViolation] = []
    flags: list[str] = []

    if tool_name == "get_correlation_matrix":
        matrix = payload.get("correlation_matrix") or {}
        violations.extend(_etf_index_correlation_violations(matrix))

    if tool_name == "get_rolling_accuracy":
        points = payload.get("windows") or payload.get("rolling_accuracy") or []
        violations.extend(_rolling_accuracy_violations(points))

    if tool_name == "get_forecast_distribution":
        violations.extend(_distribution_violations(payload))

    for violation in violations:
        logger.warning(
            "Forecast numeric integrity violation",
            tool=tool_name,
            code=violation.code,
            message=violation.message,
        )
        flags.append(violation.code)

    ok = not any(v.severity == "error" for v in violations)
    return IntegrityReport(ok=ok, violations=violations, flags=flags)


def apply_validation_to_payload(
    tool_name: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Validate and annotate payload; never silently pass flagged error responses."""
    report = validate_tool_response(tool_name, payload)
    enriched = dict(payload)
    enriched["integrity"] = report.to_dict()
    if not report.ok:
        enriched["validation_failed"] = True
        enriched["validation_flags"] = report.flags
    return enriched


_DEPRECATED_LLM_METRIC_KEYS: frozenset[str] = frozenset(
    {"directional_accuracy", "live_vs_backtest_gap"}
)

_REGIME_MATCH_LABEL_RU = "точность классификации режима (тест)"
_CALIBRATION_ERROR_LABEL_RU = "средняя ошибка калибровки на эталонных рядах"


def _sanitize_rolling_window_for_llm(window: Mapping[str, Any]) -> dict[str, Any]:
    """Expose only honest regime-match metrics to LLM consumers."""
    cleaned = {k: v for k, v in window.items() if k not in _DEPRECATED_LLM_METRIC_KEYS}
    accuracy = window.get("regime_match_accuracy", window.get("directional_accuracy"))
    if accuracy is not None:
        cleaned["regime_match_accuracy"] = accuracy
        cleaned["metric_label_ru"] = _REGIME_MATCH_LABEL_RU
        cleaned["metric_definition_ru"] = (
            "Доля совпадений классификации режима на walk-forward горизонте; "
            "не точность направления цены вверх/вниз."
        )
    mae = window.get("mae")
    if mae is not None:
        cleaned["calibration_error_mae"] = mae
        cleaned["calibration_error_label_ru"] = "ошибка калибровки (MAE)"
    return cleaned


def sanitize_tool_payload_for_llm(tool_name: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    """Strip misleading deprecated aliases before tool JSON reaches an LLM."""
    cleaned: dict[str, Any] = {
        k: v for k, v in payload.items() if k not in _DEPRECATED_LLM_METRIC_KEYS
    }

    if tool_name == "get_rolling_accuracy":
        windows = payload.get("windows") or payload.get("rolling_accuracy") or []
        cleaned["windows"] = [_sanitize_rolling_window_for_llm(w) for w in windows if isinstance(w, Mapping)]
        cleaned["metric_glossary_ru"] = {
            "regime_match_accuracy": _REGIME_MATCH_LABEL_RU,
            "calibration_error_mae": _CALIBRATION_ERROR_LABEL_RU,
            "forbidden_terms": (
                "Не используй «directional accuracy», «точность направления» или "
                "«live vs backtest gap» — эти метрики измеряют классификацию режима."
            ),
        }

    return cleaned
