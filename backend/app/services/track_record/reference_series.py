"""Reference price series for public track-record validation."""
from __future__ import annotations

from dataclasses import dataclass

from app.core.logging import get_logger

logger = get_logger(__name__)

REAL_TICKER_BENCHMARKS: tuple[tuple[str, str, str], ...] = (
    ("AAPL", "AAPL (US equity)", "technology"),
    ("MSFT", "MSFT (US equity)", "technology"),
    ("SPY", "SPY (US ETF)", "financials"),
)

MIN_REAL_BENCHMARK_BARS = 40


@dataclass(frozen=True, slots=True)
class ReferenceBenchmark:
    """Benchmark label for validation replay — real tickers preferred."""

    key: str
    label: str
    sector: str
    prices: tuple[float, ...]
    is_synthetic: bool = False


def trend_prices(start: float, step: float, count: int) -> tuple[float, ...]:
    return tuple(start + step * index for index in range(count))


def oscillating_prices(start: float, amplitude: float, count: int) -> tuple[float, ...]:
    return tuple(
        start + amplitude * (1 if index % 2 == 0 else -1) * (0.5 + (index % 5) * 0.1)
        for index in range(count)
    )


def _fetch_yfinance_closes(symbol: str, *, period: str = "6mo") -> tuple[float, ...] | None:
    """
    Sync closes for track-record validation replay.

    Leftover: still yfinance-only. Keyed HTTP clients are async and this path
    runs from sync chart builders; wiring asyncio.run here risks nested-loop
    failures under FastAPI. Prefer platform bars chain in a later async refactor.
    """
    try:
        import yfinance as yf

        hist = yf.Ticker(symbol).history(period=period, auto_adjust=True)
        if hist.empty:
            return None
        closes = tuple(float(x) for x in hist["Close"].tolist() if x == x)
        return closes if len(closes) >= MIN_REAL_BENCHMARK_BARS else None
    except Exception as exc:
        logger.debug("yfinance benchmark fetch failed", symbol=symbol, error=str(exc))
        return None


def build_synthetic_reference_benchmarks() -> tuple[ReferenceBenchmark, ...]:
    """Fixed synthetic benchmarks — used only when real OHLCV is unavailable."""
    return (
        ReferenceBenchmark(
            key="benchmark_equity_trend",
            label="Equity trend benchmark (synthetic)",
            sector="technology",
            prices=trend_prices(100.0, 0.25, 140),
            is_synthetic=True,
        ),
        ReferenceBenchmark(
            key="benchmark_equity_cycle",
            label="Equity cycle benchmark (synthetic)",
            sector="financials",
            prices=trend_prices(80.0, 0.15, 100) + trend_prices(95.0, -0.2, 40),
            is_synthetic=True,
        ),
        ReferenceBenchmark(
            key="benchmark_defensive",
            label="Defensive benchmark (synthetic)",
            sector="utilities",
            prices=oscillating_prices(50.0, 0.4, 130),
            is_synthetic=True,
        ),
    )


# Russian benchmarks come from the local price store (no network); US ones need yfinance.
LOCAL_BENCHMARKS: tuple[tuple[str, str, str], ...] = (
    ("IMOEX", "Индекс Мосбиржи", "financials"),
    ("SBER", "SBER (акция MOEX)", "financials"),
    ("LKOH", "LKOH (акция MOEX)", "energy"),
)
_CACHE_TTL_SEC = 3600.0
_YF_RETRY_SEC = 1800.0
_cache: tuple[float, tuple[ReferenceBenchmark, ...]] | None = None
_yf_failed_at: float | None = None


def _local_closes(symbol: str, *, days: int = 126) -> tuple[float, ...] | None:
    try:
        from app.services.price_history import service

        px = tuple(p for _, p in service.closes(symbol)[-days:] if p == p and p > 0)
    except Exception as exc:
        logger.debug("local benchmark load failed", symbol=symbol, error=str(exc))
        return None
    return px if len(px) >= MIN_REAL_BENCHMARK_BARS else None


def _load_real() -> list[ReferenceBenchmark]:
    global _yf_failed_at
    import time

    real: list[ReferenceBenchmark] = []
    for symbol, label, sector in LOCAL_BENCHMARKS:
        prices = _local_closes(symbol)
        if prices:
            real.append(ReferenceBenchmark(key=f"real_{symbol.lower()}", label=label, sector=sector, prices=prices))
    if real:
        return real
    # yfinance blocks ~30 s per symbol when Yahoo is unreachable: after one failure, wait before retrying.
    if _yf_failed_at is not None and time.monotonic() - _yf_failed_at < _YF_RETRY_SEC:
        return real
    for symbol, label, sector in REAL_TICKER_BENCHMARKS:
        prices = _fetch_yfinance_closes(symbol)
        if prices is None:
            _yf_failed_at = time.monotonic()
            break
        real.append(ReferenceBenchmark(key=f"real_{symbol.lower()}", label=label, sector=sector, prices=prices))
    return real


def build_reference_benchmarks() -> tuple[ReferenceBenchmark, ...]:
    """Real closes when available (local MOEX store first, then yfinance); synthetic otherwise. Cached 1 h."""
    global _cache
    import time

    now = time.monotonic()
    if _cache is not None and now - _cache[0] < _CACHE_TTL_SEC:
        return _cache[1]
    real = _load_real()
    if real:
        out = tuple(real)
    else:
        logger.warning("Real ticker benchmarks unavailable — using synthetic reference series")
        out = build_synthetic_reference_benchmarks()
    _cache = (now, out)
    return out
