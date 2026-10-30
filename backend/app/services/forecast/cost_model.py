"""Round-trip cost in return units. Conservative, not venue-accurate TCA."""

from __future__ import annotations

from app.services.forecast.excess_labels import benchmark_symbol_for


def round_trip_cost_return(symbol: str) -> float:
    """Approximate one-way*2 friction as a return deducted from excess."""
    bench = benchmark_symbol_for(symbol)
    if bench == "BTC-USD":
        return 8.0 / 10_000.0
    if bench == "IMOEX":
        return 10.0 / 10_000.0
    return 4.0 / 10_000.0
