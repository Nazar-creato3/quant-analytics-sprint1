"""Portfolio risk analytics: FHS VaR (same as GET /risk) plus factor/stress.

VaR/ES come from ``risk_engine.fhs``. Historical ``portfolio_math.var`` is
shadow-only. Factor betas, correlation, and stress stay here.
Parametric/normal VaR is intentionally not used: it understates tail risk.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Mapping, Sequence

import numpy as np

from app.services.risk.portfolio_math import (
    cumulative_return,
    max_drawdown,
    multi_factor_betas,
    ols_alpha_beta,
    simple_returns,
)
from app.services.risk.portfolio_math._utils import as_float_array
from app.services.risk.portfolio_math.var import MIN_OBSERVATIONS
from app.services.risk_engine.fhs import fhs_var_es
from app.services.risk_engine.shadow import shadow_compare

LOOKBACK_TRADING_DAYS = 252
MIN_RETURN_OBSERVATIONS = MIN_OBSERVATIONS
CONCENTRATION_CORR_THRESHOLD = 0.70
CONCENTRATION_WEIGHT_THRESHOLD = 0.50

STRESS_SCENARIOS: dict[str, dict[str, str]] = {
    "covid_2020": {
        "id": "covid_2020",
        "label_ru": "Март 2020 (резкое падение рынка)",
        "start": "2020-02-19",
        "end": "2020-03-23",
        "description_ru": (
            "Текущие веса портфеля прогнаны через дневные доходности "
            "с 19 февраля по 23 марта 2020."
        ),
    },
    "bear_2022": {
        "id": "bear_2022",
        "label_ru": "Медвежий рынок 2022",
        "start": "2022-01-03",
        "end": "2022-10-12",
        "description_ru": (
            "Текущие веса портфеля прогнаны через дневные доходности "
            "с 3 января по 12 октября 2022 (медвежий рынок акций США)."
        ),
    },
}

VAR_METHODOLOGY = {
    "method": "fhs_ewma",
    "method_ru": (
        "Оценка возможного дневного убытка по прошлым движениям портфеля. Это не обещание результата."
    ),
    "rejected_method": "parametric_normal",
    "rejected_reason_ru": (
        "Параметрический VaR с нормальным распределением систематически "
        "занижает хвостовой риск — поэтому не используется."
    ),
    "lookback_trading_days": LOOKBACK_TRADING_DAYS,
    "weights_assumption_ru": (
        "Веса = текущий состав портфеля. Историческая ребалансировка не моделируется."
    ),
}


def fhs_var_triple(returns: Sequence[float]) -> tuple[float | None, float | None, float | None]:
    """Portfolio-Risk VaR/ES from the unified FHS engine; None if too short."""
    values = [float(x) for x in returns]
    if len(values) < MIN_RETURN_OBSERVATIONS:
        return None, None, None
    shadow_compare(values)
    var95, es95 = fhs_var_es(values, alpha=0.05)
    var99, _ = fhs_var_es(values, alpha=0.01)
    return float(var95), float(var99), float(es95)


@dataclass(frozen=True, slots=True)
class HoldingSpec:
    symbol: str
    notional_usd: float
    sector: str = "unknown"
    signed_weight: float | None = None


@dataclass(frozen=True, slots=True)
class StressResult:
    scenario_id: str
    label_ru: str
    start: str
    end: str
    description_ru: str
    total_return: float | None
    max_drawdown: float | None
    worst_day_return: float | None
    missing_symbols: tuple[str, ...]
    observations: int
    equity_curve: tuple[tuple[str, float], ...]
    methodology_ru: str


@dataclass
class PortfolioRiskReport:
    computed_at: str
    lookback_start: str
    lookback_end: str
    lookback_days: int
    data_as_of: str
    nav_usd: float
    holdings: list[dict]
    sector_weights: dict[str, float]
    var_95: float | None
    var_99: float | None
    expected_shortfall_95: float | None
    var_95_usd: float | None
    var_99_usd: float | None
    expected_shortfall_95_usd: float | None
    observations: int
    alpha: float | None
    beta: float | None
    r_squared: float | None
    alpha_daily: float | None
    benchmark_symbol: str
    market_driven_return: float | None
    residual_return: float | None
    portfolio_window_return: float | None
    correlation_symbols: list[str]
    correlation_matrix: list[list[float | None]]
    avg_pairwise_correlation: float | None
    concentration_share: float | None
    concentration_flag_ru: str | None
    factor_exposures: dict[str, float]
    stress: list[StressResult]
    insufficient_data: bool
    methodology: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "computed_at": self.computed_at,
            "lookback_start": self.lookback_start,
            "lookback_end": self.lookback_end,
            "lookback_days": self.lookback_days,
            "data_as_of": self.data_as_of,
            "nav_usd": self.nav_usd,
            "holdings": self.holdings,
            "sector_weights": self.sector_weights,
            "var_95": self.var_95,
            "var_99": self.var_99,
            "expected_shortfall_95": self.expected_shortfall_95,
            "var_95_usd": self.var_95_usd,
            "var_99_usd": self.var_99_usd,
            "expected_shortfall_95_usd": self.expected_shortfall_95_usd,
            "observations": self.observations,
            "alpha": self.alpha,
            "beta": self.beta,
            "r_squared": self.r_squared,
            "alpha_daily": self.alpha_daily,
            "benchmark_symbol": self.benchmark_symbol,
            "market_driven_return": self.market_driven_return,
            "residual_return": self.residual_return,
            "portfolio_window_return": self.portfolio_window_return,
            "correlation_symbols": self.correlation_symbols,
            "correlation_matrix": self.correlation_matrix,
            "avg_pairwise_correlation": self.avg_pairwise_correlation,
            "concentration_share": self.concentration_share,
            "concentration_flag_ru": self.concentration_flag_ru,
            "factor_exposures": self.factor_exposures,
            "stress": [
                {
                    "scenario_id": s.scenario_id,
                    "label_ru": s.label_ru,
                    "start": s.start,
                    "end": s.end,
                    "description_ru": s.description_ru,
                    "total_return": s.total_return,
                    "max_drawdown": s.max_drawdown,
                    "worst_day_return": s.worst_day_return,
                    "missing_symbols": list(s.missing_symbols),
                    "observations": s.observations,
                    "equity_curve": [{"date": d, "equity": v} for d, v in s.equity_curve],
                    "methodology_ru": s.methodology_ru,
                }
                for s in self.stress
            ],
            "insufficient_data": self.insufficient_data,
            "methodology": self.methodology,
            "notes": self.notes,
        }


def align_return_matrix(
    series_by_symbol: Mapping[str, Sequence[tuple[str, float]]],
) -> tuple[list[str], list[str], np.ndarray]:
    """Inner-join dated closes, return (dates, symbols, T×N simple returns)."""
    date_sets: list[set[str]] | None = None
    ordered = [s for s in series_by_symbol.keys()]
    close_maps: dict[str, dict[str, float]] = {}
    for symbol in ordered:
        mapping = {d: float(p) for d, p in series_by_symbol[symbol] if p and p > 0}
        close_maps[symbol] = mapping
        keys = set(mapping)
        date_sets = keys if date_sets is None else date_sets & keys
    if not date_sets or len(date_sets) < 3:
        return [], ordered, np.zeros((0, len(ordered)))
    dates = sorted(date_sets)
    prices = np.column_stack([[close_maps[s][d] for d in dates] for s in ordered])
    rets = prices[1:] / prices[:-1] - 1.0
    return dates[1:], ordered, rets


def portfolio_returns(returns: np.ndarray, weights: Sequence[float]) -> np.ndarray:
    w = np.asarray(weights, dtype=float)
    if returns.size == 0 or w.size == 0:
        return np.array([], dtype=float)
    if returns.ndim != 2 or returns.shape[1] != w.size:
        raise ValueError("returns/weights shape mismatch")
    return returns @ w


def correlation_matrix(returns: np.ndarray) -> tuple[np.ndarray, float | None]:
    if returns.ndim != 2 or returns.shape[0] < 5 or returns.shape[1] < 2:
        return np.array([]), None
    with np.errstate(invalid="ignore", divide="ignore"):
        corr = np.corrcoef(returns, rowvar=False)
    if corr.ndim == 0:
        return np.array([]), None
    corr = np.where(np.isfinite(corr), corr, np.nan)
    n = corr.shape[0]
    vals = [corr[i, j] for i in range(n) for j in range(i + 1, n) if np.isfinite(corr[i, j])]
    avg = float(np.mean(vals)) if vals else None
    return corr, avg


def sector_label(raw: str | None) -> str:
    """Screen text. English sector codes stay off the portfolio table."""
    table = {
        "banks": "банки",
        "energy": "энергетика",
        "tech": "технологии",
        "technology": "технологии",
        "indices": "индексы",
        "crypto": "крипто",
        "fund": "фонд",
    }
    key = (raw or "").strip().lower()
    if not key or key == "unknown":
        return "нет данных"
    if key in table:
        return table[key]
    if key.isascii():
        return "нет данных"
    return key


def sector_weights(holdings: Sequence[HoldingSpec], nav: float) -> dict[str, float]:
    if nav <= 0:
        return {}
    acc: dict[str, float] = {}
    for h in holdings:
        acc[h.sector or "unknown"] = acc.get(h.sector or "unknown", 0.0) + abs(h.notional_usd)
    return {k: round(v / nav, 6) for k, v in sorted(acc.items(), key=lambda kv: -kv[1])}


def concentration_message(
    *,
    sector_w: Mapping[str, float],
    avg_corr: float | None,
) -> tuple[float | None, str | None]:
    if not sector_w:
        return None, None
    top_key, top_share = max(sector_w.items(), key=lambda kv: kv[1])
    top_sector = sector_label(top_key)
    if avg_corr is not None and avg_corr >= CONCENTRATION_CORR_THRESHOLD and top_share >= CONCENTRATION_WEIGHT_THRESHOLD:
        pct = round(top_share * 100)
        corr_pct = round(avg_corr * 100)
        return top_share, (
            f"{pct}% вашего портфеля в секторе «{top_sector}» и в среднем движется "
            f"одинаково (средняя парная корреляция {corr_pct}%) — низкая реальная диверсификация."
        )
    if top_share >= 0.70:
        pct = round(top_share * 100)
        return top_share, (
            f"{pct}% портфеля сосредоточено в секторе «{top_sector}» — "
            f"концентрация по отрасли, даже если тикеров несколько."
        )
    if avg_corr is not None and avg_corr >= CONCENTRATION_CORR_THRESHOLD:
        corr_pct = round(avg_corr * 100)
        return top_share, (
            f"{corr_pct}% среднего содвижения позиций — мнимая диверсификация: "
            f"тикеры разные, фактор риска общий."
        )
    return top_share, None


def equity_curve(dates: Sequence[str], returns: Sequence[float]) -> tuple[tuple[str, float], ...]:
    arr = as_float_array(returns)
    n = min(len(dates), len(arr))
    if n == 0:
        return ()
    eq = np.cumprod(1.0 + arr[:n])
    return tuple((dates[i], float(eq[i])) for i in range(n))


def stress_current_weights(
    *,
    weights_by_symbol: Mapping[str, float],
    series_by_symbol: Mapping[str, Sequence[tuple[str, float]]],
    scenario: Mapping[str, str],
) -> StressResult:
    start, end = scenario["start"], scenario["end"]
    windowed: dict[str, list[tuple[str, float]]] = {}
    missing: list[str] = []
    for symbol, weight in weights_by_symbol.items():
        if abs(weight) < 1e-12:
            continue
        rows = [(d, p) for d, p in series_by_symbol.get(symbol, []) if start <= d <= end]
        if len(rows) < 5:
            missing.append(symbol)
            continue
        windowed[symbol] = rows
    dates, used, rets = align_return_matrix(windowed)
    # Keep original book weights; names without history contribute 0 (cash-like).
    w = np.array([weights_by_symbol[s] for s in used], dtype=float) if used else np.array([])
    port = portfolio_returns(rets, w) if used else np.array([])
    tot = cumulative_return(port)
    mdd = max_drawdown(port)
    worst = float(np.min(port)) if port.size else None
    curve = equity_curve(dates, port)
    # downsample curve for UI (max ~90 points)
    if len(curve) > 90:
        step = max(1, len(curve) // 90)
        curve = curve[::step] + (curve[-1],)

    return StressResult(
        scenario_id=scenario["id"],
        label_ru=scenario["label_ru"],
        start=start,
        end=end,
        description_ru=scenario["description_ru"],
        total_return=tot,
        max_drawdown=mdd,
        worst_day_return=worst,
        missing_symbols=tuple(missing),
        observations=int(port.size),
        equity_curve=curve,
        methodology_ru=(
            "Текущие веса × исторические дневные доходности инструментов. "
            "Это не бэктест ребалансировки и не P&L реальных сделок 2020/2022 годов."
        ),
    )


def build_report(
    *,
    holdings: Sequence[HoldingSpec],
    series_by_symbol: Mapping[str, Sequence[tuple[str, float]]],
    benchmark_symbol: str = "SPY",
    lookback_days: int = LOOKBACK_TRADING_DAYS,
    factor_returns: Mapping[str, Sequence[float]] | None = None,
    now: datetime | None = None,
) -> PortfolioRiskReport:
    now = now or datetime.now(timezone.utc)
    notes: list[str] = []
    nav = float(sum(abs(h.notional_usd) for h in holdings))
    if nav <= 0:
        return PortfolioRiskReport(
            computed_at=now.isoformat(),
            lookback_start="",
            lookback_end="",
            lookback_days=lookback_days,
            data_as_of=now.isoformat(),
            nav_usd=0.0,
            holdings=[],
            sector_weights={},
            var_95=None,
            var_99=None,
            expected_shortfall_95=None,
            var_95_usd=None,
            var_99_usd=None,
            expected_shortfall_95_usd=None,
            observations=0,
            alpha=None,
            beta=None,
            r_squared=None,
            alpha_daily=None,
            benchmark_symbol=benchmark_symbol,
            market_driven_return=None,
            residual_return=None,
            portfolio_window_return=None,
            correlation_symbols=[],
            correlation_matrix=[],
            avg_pairwise_correlation=None,
            concentration_share=None,
            concentration_flag_ru=None,
            factor_exposures={},
            stress=[],
            insufficient_data=True,
            methodology={**VAR_METHODOLOGY, "lookback_trading_days": lookback_days},
            notes=["Открытых позиций нет — VaR и стресс не считаются."],
        )

    weights = {h.symbol: h.notional_usd / nav for h in holdings}
    holding_rows = [
        {
            "symbol": h.symbol,
            "notional_usd": round(h.notional_usd, 2),
            "weight": round(weights[h.symbol], 6),
            "sector": sector_label(h.sector),
        }
        for h in holdings
    ]
    sec_w = sector_weights(holdings, nav)

    # Keep full history for stress windows; VaR/corr use the trailing lookback only.
    full_history = {
        symbol: sorted((d, p) for d, p in rows if p and p > 0)
        for symbol, rows in series_by_symbol.items()
    }
    trimmed: dict[str, list[tuple[str, float]]] = {
        symbol: ordered[-(lookback_days + 5) :] for symbol, ordered in full_history.items()
    }

    symbols = [h.symbol for h in holdings]
    present = {s: trimmed[s] for s in symbols if s in trimmed and len(trimmed[s]) >= 5}
    missing = [s for s in symbols if s not in present]
    if missing:
        notes.append("Нет достаточной истории котировок: " + ", ".join(missing))

    dates, used, rets = align_return_matrix(present)
    w = np.array([weights[s] for s in used], dtype=float) if used else np.array([])
    port = portfolio_returns(rets, w) if used else np.array([])
    lookback_start = dates[0] if dates else ""
    lookback_end = dates[-1] if dates else ""

    var95, var99, es95 = fhs_var_triple(port)
    def usd(frac: float | None) -> float | None:
        return None if frac is None else round(frac * nav, 2)

    bench_series = trimmed.get(benchmark_symbol) or series_by_symbol.get(benchmark_symbol, [])
    alpha_d = beta = r2 = None
    mkt_driven = residual = window_ret = None
    if bench_series and used:
        b_dates, b_used, b_rets = align_return_matrix(
            {**{s: present[s] for s in used}, benchmark_symbol: list(bench_series)}
        )
        if benchmark_symbol in b_used and b_rets.size:
            bench_idx = b_used.index(benchmark_symbol)
            asset_idx = [i for i, s in enumerate(b_used) if s != benchmark_symbol]
            if asset_idx:
                aligned_asset = b_rets[:, asset_idx]
                aligned_w = np.array(
                    [weights[s] for s in b_used if s != benchmark_symbol], dtype=float
                )
                # renormalize to original surviving weight sum
                aligned_port = portfolio_returns(aligned_asset, aligned_w)
                aligned_mkt = b_rets[:, bench_idx]
                n = min(len(aligned_port), len(aligned_mkt))
                aligned_port, aligned_mkt = aligned_port[-n:], aligned_mkt[-n:]
                alpha_d, beta, r2 = ols_alpha_beta(aligned_port, aligned_mkt)
                window_ret = cumulative_return(aligned_port)
                if beta is not None:
                    mkt_driven = cumulative_return(beta * aligned_mkt)
                    residual = cumulative_return(aligned_port - beta * aligned_mkt)
                port = aligned_port
                dates = b_dates[-n:]
                var95, var99, es95 = fhs_var_triple(port)

    corr, avg_corr = correlation_matrix(rets) if rets.size else (np.array([]), None)
    corr_list: list[list[float | None]] = []
    if corr.size:
        corr_list = [
            [None if not np.isfinite(v) else round(float(v), 4) for v in row]
            for row in corr
        ]
    conc_share, conc_msg = concentration_message(sector_w=sec_w, avg_corr=avg_corr)

    ff = multi_factor_betas(port, factor_returns or {})
    # MVP factor view = sector weights; FF betas overlay when provided.
    factor_view = {f"sector:{k}": v for k, v in sec_w.items()}
    factor_view.update({f"ff:{k}": v for k, v in ff.items()})

    stress_results = [
        stress_current_weights(
            weights_by_symbol=weights,
            series_by_symbol=full_history,
            scenario=sc,
        )
        for sc in STRESS_SCENARIOS.values()
    ]

    insufficient = len(port) < MIN_RETURN_OBSERVATIONS
    if insufficient:
        var95, var99, es95 = None, None, None
        notes.append(
            f"Недостаточно пересекающихся дневных доходностей "
            f"({len(port)} < {MIN_RETURN_OBSERVATIONS}) — VaR скрыт, а не выдуман."
        )

    annual_alpha = None if alpha_d is None else float(alpha_d * 252)

    methodology = {
        **VAR_METHODOLOGY,
        "lookback_trading_days": lookback_days,
        "lookback_start": lookback_start,
        "lookback_end": lookback_end,
        "observations": int(len(port)),
        "benchmark_symbol": benchmark_symbol,
        "alpha_definition_ru": (
            "Дневной α — свободный член OLS: r_p = α + β·r_benchmark + ε. "
            "Показатель «α год.» = α_дневной × 252 (простое аннуализирование, не CAGR)."
        ),
        "beta_definition_ru": f"β к {benchmark_symbol} на том же окне, что и VaR.",
        "correlation_window_ru": f"Парные корреляции дневных доходностей на окне {lookback_days} сессий.",
        "stress_definition_ru": (
            "Стресс = текущие веса × исторические доходности шокового окна. "
            "Не является P&L вашего тогдашнего портфеля."
        ),
        "computed_at": now.isoformat(),
    }

    return PortfolioRiskReport(
        computed_at=now.isoformat(),
        lookback_start=lookback_start,
        lookback_end=lookback_end,
        lookback_days=lookback_days,
        data_as_of=now.isoformat(),
        nav_usd=round(nav, 2),
        holdings=holding_rows,
        sector_weights=sec_w,
        var_95=var95,
        var_99=var99,
        expected_shortfall_95=es95,
        var_95_usd=usd(var95),
        var_99_usd=usd(var99),
        expected_shortfall_95_usd=usd(es95),
        observations=int(len(port)),
        alpha=annual_alpha,
        beta=beta,
        r_squared=r2,
        alpha_daily=alpha_d,
        benchmark_symbol=benchmark_symbol,
        market_driven_return=mkt_driven,
        residual_return=residual,
        portfolio_window_return=window_ret,
        correlation_symbols=used,
        correlation_matrix=corr_list,
        avg_pairwise_correlation=avg_corr,
        concentration_share=conc_share,
        concentration_flag_ru=conc_msg,
        factor_exposures=factor_view,
        stress=stress_results,
        insufficient_data=insufficient,
        methodology=methodology,
        notes=notes,
    )


def parse_iso_date(value: str) -> date:
    return date.fromisoformat(value[:10])
