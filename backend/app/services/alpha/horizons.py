"""Multi-horizon excess stack: 1d / 5d / 21d, not a single LightGBM target."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from app.services.forecast.excess_labels import excess_direction_labels
from app.services.forecast.triple_barrier import TripleBarrierConfig

ALPHA_HORIZONS: tuple[int, ...] = (1, 5, 21)
# Map session count → TB holding so labels expire with the forecast window.
TB_HOLDING_BY_HORIZON: dict[int, int] = {1: 1, 5: 5, 21: 15}


@dataclass(frozen=True, slots=True)
class HorizonSpec:
    days: int
    tb_holding: int
    model_suffix: str

    @property
    def tb_config(self) -> TripleBarrierConfig:
        return TripleBarrierConfig(
            atr_multiplier=1.5,
            max_holding_days=self.tb_holding,
            atr_window=14,
        )


def horizon_specs(horizons: Sequence[int] = ALPHA_HORIZONS) -> tuple[HorizonSpec, ...]:
    return tuple(
        HorizonSpec(
            days=int(h),
            tb_holding=int(TB_HOLDING_BY_HORIZON.get(int(h), min(int(h), 15))),
            model_suffix=f"h{int(h)}",
        )
        for h in horizons
    )


def excess_return(
    closes: Sequence[float],
    i: int,
    horizon: int,
    benchmark: Sequence[float] | None = None,
) -> float | None:
    if i < 0 or i + horizon >= len(closes):
        return None
    start = float(closes[i])
    end = float(closes[i + horizon])
    if start <= 0 or end <= 0:
        return None
    asset = end / start - 1.0
    if not benchmark or len(benchmark) < len(closes):
        return asset
    b_i = len(benchmark) - len(closes) + i
    if b_i < 0 or b_i + horizon >= len(benchmark):
        return asset
    b0, b1 = float(benchmark[b_i]), float(benchmark[b_i + horizon])
    if b0 <= 0 or b1 <= 0:
        return asset
    return asset - (b1 / b0 - 1.0)


def excess_stack(
    closes: Sequence[float],
    benchmark: Sequence[float] | None = None,
    *,
    horizons: Sequence[int] = ALPHA_HORIZONS,
    cost_return: float = 0.0,
) -> dict[int, list[int]]:
    """Signed excess labels for every research horizon (0 = unlabeled)."""
    return {
        int(h): excess_direction_labels(
            closes, benchmark, horizon=int(h), cost_return=cost_return
        )
        for h in horizons
    }


def latest_excess_map(
    closes: Sequence[float],
    benchmark: Sequence[float] | None = None,
    *,
    horizons: Sequence[int] = ALPHA_HORIZONS,
) -> dict[str, float | None]:
    n = len(closes)
    out: dict[str, float | None] = {}
    for h in horizons:
        # Last *completed* window ending at the latest bar (no look-ahead).
        i = n - 1 - int(h)
        out[f"excess_{int(h)}d"] = excess_return(closes, i, int(h), benchmark) if i >= 0 else None
    return out
