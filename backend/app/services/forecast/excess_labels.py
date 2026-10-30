"""Labels: beat the benchmark over 20 / 60 sessions, not raw price-up."""
from __future__ import annotations

from typing import Sequence


def _aligned_return(series: Sequence[float], i: int, horizon: int) -> float | None:
    if i < 0 or i + horizon >= len(series):
        return None
    start = float(series[i])
    end = float(series[i + horizon])
    if start <= 0 or end <= 0:
        return None
    return end / start - 1.0


def excess_direction_labels(
    closes: Sequence[float],
    benchmark: Sequence[float] | None,
    *,
    horizon: int = 20,
    cost_return: float = 0.0,
) -> list[int]:
    """+1 if name beats benchmark after optional round-trip cost. 0 = unlabeled."""
    n = len(closes)
    bench = list(benchmark) if benchmark and len(benchmark) >= n else None
    out = [0] * n
    for i in range(n - horizon):
        asset = _aligned_return(closes, i, horizon)
        if asset is None:
            continue
        if bench is not None:
            # Align from the end so unequal histories still match recent bars.
            b_i = len(bench) - n + i
            br = _aligned_return(bench, b_i, horizon)
            if br is None:
                continue
            excess = asset - br - float(cost_return)
        else:
            excess = asset - float(cost_return)
        out[i] = 1 if excess > 0.0 else -1
    return out


def benchmark_symbol_for(symbol: str) -> str:
    raw = (symbol or "").strip().upper()
    if raw.endswith("-USD") or raw.endswith("USDT") or raw in {"BTC", "ETH", "SOL", "BNB"}:
        return "BTC-USD"
    try:
        from app.services.market_data.moex_spot import is_moex_ticker

        if is_moex_ticker(raw):
            return "IMOEX"
    except Exception:
        pass
    return "SPY"


RESEARCH_HORIZONS: tuple[int, ...] = (1, 5, 21)
