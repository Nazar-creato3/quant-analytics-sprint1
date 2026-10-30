"""Primary labels for every new model: triple-barrier side + meta take/skip.

Side comes from the barrier outcome. Meta-label is 1 iff a primary rule
(Turtle / Donchian) proposed that same side and the barrier was not vertical.
Unlabeled bars stay 0 and must be dropped before fitting.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from app.services.alpha.horizons import ALPHA_HORIZONS, horizon_specs
from app.services.alpha.rules import primary_side
from app.services.forecast.triple_barrier import TripleBarrierConfig, triple_barrier_labels


@dataclass(frozen=True, slots=True)
class PrimaryLabels:
    horizon: int
    recipe: str
    side: tuple[int, ...]
    meta_take: tuple[int, ...]
    n_side: int
    n_take: int


def _tb(
    closes: Sequence[float],
    *,
    highs: Sequence[float] | None,
    lows: Sequence[float] | None,
    config: TripleBarrierConfig,
) -> list[int]:
    return triple_barrier_labels(closes, highs=highs, lows=lows, config=config)


def primary_labels(
    closes: Sequence[float],
    *,
    highs: Sequence[float] | None = None,
    lows: Sequence[float] | None = None,
    horizon: int = 5,
    volumes: Sequence[float] | None = None,
) -> PrimaryLabels:
    spec = horizon_specs((horizon,))[0]
    side = _tb(closes, highs=highs, lows=lows, config=spec.tb_config)
    rule = primary_side(closes, highs=highs, lows=lows, volumes=volumes)
    meta: list[int] = []
    for s, r in zip(side, rule):
        if s == 0 or r == 0:
            meta.append(0)
        else:
            meta.append(1 if s == r else 0)
    n_side = sum(1 for x in side if x != 0)
    n_take = sum(meta)
    return PrimaryLabels(
        horizon=int(horizon),
        recipe="triple_barrier+meta_label",
        side=tuple(int(x) for x in side),
        meta_take=tuple(int(x) for x in meta),
        n_side=n_side,
        n_take=n_take,
    )


def directional_y(labels: PrimaryLabels) -> list[int]:
    """Fit target for direction models: TB side, zeros dropped by the trainer."""
    return list(labels.side)


def meta_y(labels: PrimaryLabels) -> list[int]:
    """Fit target for the take/skip head. Only defined where side != 0."""
    out: list[int] = []
    for s, m in zip(labels.side, labels.meta_take):
        if s == 0:
            out.append(0)
        else:
            out.append(int(m))
    return out


def stack_primary_labels(
    closes: Sequence[float],
    *,
    highs: Sequence[float] | None = None,
    lows: Sequence[float] | None = None,
    volumes: Sequence[float] | None = None,
    horizons: Sequence[int] = ALPHA_HORIZONS,
) -> dict[int, PrimaryLabels]:
    return {
        int(h): primary_labels(
            closes, highs=highs, lows=lows, horizon=int(h), volumes=volumes
        )
        for h in horizons
    }
