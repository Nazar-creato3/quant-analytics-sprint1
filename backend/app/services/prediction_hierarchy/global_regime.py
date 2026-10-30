"""Global Macro Regime Engine (Prompt 32)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from app.services.prediction_hierarchy.types import GlobalRegimeLabel, GlobalRegimeResult
from app.services.quant_math import correlation

DEFAULT_CONFIRMATION_WINDOW = 5
GLOBAL_CONFIDENCE_DAMPING = 0.35

CREDIT_SPREAD_SOURCE_FRED = "fred_hy_oas"
CREDIT_SPREAD_SOURCE_NONE = "unavailable"
# ICE BofA US High Yield OAS (FRED BAMLH0A0HYM2) is already the spread over
# Treasuries. Long-run median is near 4.5–5 %; below ~3.5 % is a calm credit
# market, above ~5.5 % is stress.
HY_OAS_STRESS = 0.055
HY_OAS_CALM = 0.035


@dataclass(frozen=True, slots=True)
class MacroIndicatorSnapshot:
    """Macro inputs from Prompt 16 data core."""

    rate_cb: float | None = None
    cpi: float | None = None
    unemployment: float | None = None
    dxy: float | None = None
    vix: float | None = None
    oil_brent: float | None = None
    cross_asset_correlation: float = 0.0
    credit_spread_proxy: float | None = None
    hy_oas_pct: float | None = None
    gov_10y_pct: float | None = None


def compute_credit_spread_proxy(
    *,
    hy_oas_pct: float | None = None,
    gov_10y_pct: float | None = None,
) -> tuple[float | None, str]:
    """HY credit spread as a fraction from FRED HY OAS; None when not loaded.

    ``gov_10y_pct`` is accepted for compatibility and not subtracted: the OAS
    is already measured over Treasuries (subtracting the 10Y yield drove the
    spread to zero). There is no static fallback number.
    """
    del gov_10y_pct
    if hy_oas_pct is None:
        return None, CREDIT_SPREAD_SOURCE_NONE
    return round(max(0.0, float(hy_oas_pct) / 100.0), 6), CREDIT_SPREAD_SOURCE_FRED


def compute_cross_asset_correlation(
    asset_return_series: Sequence[Sequence[float]],
) -> float:
    """Average pairwise correlation across major asset classes."""
    series_list = [list(s) for s in asset_return_series if len(s) >= 5]
    if len(series_list) < 2:
        return 0.0
    correlations: list[float] = []
    for left_index in range(len(series_list)):
        for right_index in range(left_index + 1, len(series_list)):
            left = series_list[left_index]
            right = series_list[right_index]
            length = min(len(left), len(right))
            if length < 2:
                continue
            correlations.append(abs(correlation(left[-length:], right[-length:])))
    if not correlations:
        return 0.0
    return sum(correlations) / len(correlations)


class GlobalMacroRegimeEngine:
    """Probabilistic global macro regime classifier."""

    def __init__(
        self,
        *,
        confirmation_window_bars: int = DEFAULT_CONFIRMATION_WINDOW,
    ) -> None:
        self._confirmation_window = confirmation_window_bars
        self._previous_regime: str | None = None
        self._regime_age_bars: int = 0

    def classify(
        self,
        indicators: MacroIndicatorSnapshot,
        *,
        previous_regime: str | None = None,
        regime_age_bars: int = 0,
    ) -> GlobalRegimeResult:
        """Return probabilistic global regime distribution."""
        spread: float | None
        if indicators.hy_oas_pct is not None:
            spread, spread_source = compute_credit_spread_proxy(hy_oas_pct=indicators.hy_oas_pct)
        elif indicators.credit_spread_proxy is not None:
            spread = indicators.credit_spread_proxy
            spread_source = "macro_series_normalized"
        else:
            spread, spread_source = None, CREDIT_SPREAD_SOURCE_NONE

        scores: dict[str, float] = {label.value: 0.05 for label in GlobalRegimeLabel}

        # Missing inputs add no evidence (no default VIX of 20).
        vix = indicators.vix
        if vix is not None and vix >= 30:
            scores[GlobalRegimeLabel.RISK_OFF.value] += 0.35
            scores[GlobalRegimeLabel.MACRO_UNCERTAINTY.value] += 0.20
        elif vix is not None and vix <= 18:
            scores[GlobalRegimeLabel.RISK_ON.value] += 0.30

        if spread is not None:
            stress, calm = (HY_OAS_STRESS, HY_OAS_CALM) if spread_source == CREDIT_SPREAD_SOURCE_FRED else (0.025, 0.012)
            if spread >= stress:
                scores[GlobalRegimeLabel.CREDIT_STRESS.value] += 0.30
            elif spread <= calm:
                scores[GlobalRegimeLabel.RISK_ON.value] += 0.15

        if indicators.cpi is not None and indicators.cpi > 3.5:
            scores[GlobalRegimeLabel.INFLATION_SHOCK_REGIME.value] += 0.25

        cross_corr = indicators.cross_asset_correlation
        if cross_corr >= 0.6:
            scores[GlobalRegimeLabel.RISK_OFF.value] += 0.20
            scores[GlobalRegimeLabel.MACRO_UNCERTAINTY.value] += 0.15

        if indicators.dxy is not None and indicators.dxy > 105:
            scores[GlobalRegimeLabel.RISK_OFF.value] += 0.10

        total = sum(scores.values())
        distribution = {label: value / total for label, value in scores.items()}
        dominant = max(distribution, key=distribution.get)
        if max(distribution.values()) - min(distribution.values()) < 1e-9:
            # No input moved any score: say so instead of picking the first label.
            dominant = GlobalRegimeLabel.MACRO_UNCERTAINTY.value
        dominant_prob = distribution[dominant]
        confidence = min(1.0, 0.45 + dominant_prob * 0.55)

        prev = previous_regime or self._previous_regime
        age = regime_age_bars if regime_age_bars else self._regime_age_bars
        damping_active = prev is not None and dominant != prev and age < self._confirmation_window
        if damping_active:
            confidence *= 1.0 - GLOBAL_CONFIDENCE_DAMPING

        result = GlobalRegimeResult(
            distribution=distribution,
            dominant_regime=dominant,
            confidence=round(confidence, 4),
            confirmation_window_bars=self._confirmation_window,
            confidence_damping_active=damping_active,
            credit_spread_proxy=spread,
            credit_spread_source=spread_source,
        )
        result.validate()
        return result

    def update_regime_history(
        self,
        current_dominant: str,
    ) -> tuple[str | None, int]:
        """Track regime age for confirmation window."""
        if self._previous_regime == current_dominant:
            self._regime_age_bars += 1
        else:
            prev = self._previous_regime
            self._previous_regime = current_dominant
            self._regime_age_bars = 1
            return prev, 1
        return self._previous_regime, self._regime_age_bars

    @staticmethod
    def apply_global_confidence_damping(
        lower_level_confidence: float,
        global_result: GlobalRegimeResult,
    ) -> float:
        """Global regime confidence caps lower-level confidence."""
        capped = min(lower_level_confidence, global_result.confidence)
        if global_result.confidence_damping_active:
            capped *= 1.0 - GLOBAL_CONFIDENCE_DAMPING
        return max(0.0, min(1.0, capped))

    @staticmethod
    def indicators_from_dict(raw: Mapping[str, float | None]) -> MacroIndicatorSnapshot:
        return MacroIndicatorSnapshot(
            rate_cb=raw.get("rate_cb"),
            cpi=raw.get("cpi"),
            unemployment=raw.get("unemployment"),
            dxy=raw.get("dxy"),
            vix=raw.get("vix"),
            oil_brent=raw.get("oil_brent"),
            cross_asset_correlation=float(raw.get("cross_asset_correlation", 0.0) or 0.0),
            credit_spread_proxy=raw.get("credit_spread_proxy"),
            hy_oas_pct=raw.get("hy_oas_pct"),
            gov_10y_pct=raw.get("gov_10y_pct"),
        )
