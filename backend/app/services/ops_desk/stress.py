"""Free stress book: canned 2008 / 2020 / rate-spike shocks. No vendor scenarios."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


# Equity-index equivalent shocks (total return). Applied via name beta to SPY.
SCENARIOS: dict[str, dict[str, float]] = {
    "gfc_2008": {"equity": -0.40, "rate": 0.0, "label": "2008 GFC peak-to-trough"},
    "covid_2020": {"equity": -0.34, "rate": -0.10, "label": "2020 COVID crash"},
    "rate_spike": {"equity": -0.12, "rate": 0.20, "label": "sharp rates up / multiple expansion"},
}


@dataclass(frozen=True, slots=True)
class StressHit:
    name: str
    label: str
    pnl_frac: float
    worst_name: str
    worst_pnl: float


def apply_stress(
    weights: Sequence[float],
    betas: Sequence[float],
    *,
    durations: Sequence[float] | None = None,
    scenario: str,
) -> StressHit:
    spec = SCENARIOS.get(scenario) or SCENARIOS["rate_spike"]
    eq = float(spec["equity"])
    rt = float(spec["rate"])
    pnl = 0.0
    worst_i = 0
    worst = 0.0
    for i, w in enumerate(weights):
        b = float(betas[i]) if i < len(betas) else 1.0
        dur = float(durations[i]) if durations and i < len(durations) else 0.0
        name_pnl = b * eq + dur * (-rt)  # duration long loses when rates spike
        contrib = float(w) * name_pnl
        pnl += contrib
        if contrib < worst:
            worst = contrib
            worst_i = i
    return StressHit(
        name=scenario,
        label=str(spec["label"]),
        pnl_frac=round(pnl, 6),
        worst_name=str(worst_i),
        worst_pnl=round(worst, 6),
    )


def run_all(
    weights: Sequence[float],
    betas: Sequence[float],
    *,
    durations: Sequence[float] | None = None,
    symbols: Sequence[str] = (),
) -> list[StressHit]:
    out: list[StressHit] = []
    for key in SCENARIOS:
        hit = apply_stress(weights, betas, durations=durations, scenario=key)
        if symbols and 0 <= int(hit.worst_name) < len(symbols):
            hit = StressHit(hit.name, hit.label, hit.pnl_frac, str(symbols[int(hit.worst_name)]), hit.worst_pnl)
        out.append(hit)
    return out
