"""Weekly backtest deep analysis — aggregation and reporting."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BacktestRun
from app.services.backtest_analysis.classifier import (
    ExitClassification,
    classify_trade_log,
    filter_clean_trades,
)


def _stable_hash(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _equity_stats(equity_curve: list[dict]) -> dict[str, Any]:
    if not equity_curve:
        return {"points": 0, "max_drawdown_pct": 0.0}
    values = [float(p.get("equity", p.get("value", 0))) for p in equity_curve]
    peak = values[0]
    max_dd = 0.0
    for v in values:
        peak = max(peak, v)
        if peak > 0:
            max_dd = max(max_dd, (peak - v) / peak * 100)
    return {"points": len(values), "max_drawdown_pct": round(max_dd, 4)}


def _exit_breakdown(trades: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for t in trades:
        cls = t.get("exit_classification", ExitClassification.UNCLASSIFIED.value)
        counts[cls] = counts.get(cls, 0) + 1
    return counts


def _duration_distribution(trades: list[dict[str, Any]]) -> dict[str, int]:
    buckets = {"0-1d": 0, "1-5d": 0, "5-20d": 0, "20d+": 0}
    for t in trades:
        entry = t.get("entry_date")
        exit_d = t.get("exit_date")
        if not entry or not exit_d:
            continue
        try:
            e = datetime.fromisoformat(str(entry).replace("Z", "+00:00"))
            x = datetime.fromisoformat(str(exit_d).replace("Z", "+00:00"))
            days = (x - e).days
        except (ValueError, TypeError):
            continue
        if days <= 1:
            buckets["0-1d"] += 1
        elif days <= 5:
            buckets["1-5d"] += 1
        elif days <= 20:
            buckets["5-20d"] += 1
        else:
            buckets["20d+"] += 1
    return buckets


def aggregate_runs(runs: list[BacktestRun], *, clean_only: bool = True) -> dict[str, Any]:
    """Aggregate completed backtest runs into a weekly analysis report."""
    by_strategy: dict[str, list[dict]] = {}
    by_symbol: dict[str, list[dict]] = {}
    all_trades: list[dict[str, Any]] = []
    returns: list[float] = []
    slippage_impact = 0.0

    for run in runs:
        if run.status != "complete":
            continue
        trades = classify_trade_log(run.trade_log or [])
        if clean_only:
            trades = [t for t in trades if t.get("exit_classification") == ExitClassification.CLEAN_EXIT.value]
        all_trades.extend(trades)
        ret = float(run.total_return_pct or 0)
        returns.append(ret)
        by_strategy.setdefault(run.strategy, []).append({"run_id": run.id, "return_pct": ret})
        by_symbol.setdefault(run.ticker, []).append({"run_id": run.id, "return_pct": ret})
        slippage_impact += float((run.metrics or {}).get("total_commission", 0))

    avg_return = sum(returns) / len(returns) if returns else 0.0
    win_trades = [t for t in all_trades if float(t.get("pnl", 0)) > 0]
    win_rate = len(win_trades) / len(all_trades) if all_trades else 0.0

    # Walk-forward: split runs by created_at into IS/OOS halves
    sorted_runs = sorted(runs, key=lambda r: r.created_at or datetime.min.replace(tzinfo=timezone.utc))
    mid = len(sorted_runs) // 2
    is_runs = sorted_runs[:mid] if mid else sorted_runs
    oos_runs = sorted_runs[mid:] if mid else []

    def _avg_ret(subset: list[BacktestRun]) -> float:
        vals = [float(r.total_return_pct or 0) for r in subset if r.status == "complete"]
        return sum(vals) / len(vals) if vals else 0.0

    report_core = {
        "run_count": len(runs),
        "clean_trade_count": len(all_trades),
        "avg_return_pct": round(avg_return, 4),
        "win_rate": round(win_rate, 4),
        "by_strategy": by_strategy,
        "by_symbol": by_symbol,
        "exit_breakdown": _exit_breakdown(classify_trade_log(
            [t for run in runs for t in (run.trade_log or [])]
        )),
        "duration_distribution": _duration_distribution(all_trades),
        "slippage_fee_impact": round(slippage_impact, 2),
        "in_sample_avg_return_pct": round(_avg_ret(is_runs), 4),
        "out_of_sample_avg_return_pct": round(_avg_ret(oos_runs), 4),
        "stability_score": round(1.0 - abs(_avg_ret(is_runs) - _avg_ret(oos_runs)) / 100, 4),
    }

    if runs:
        latest = max(runs, key=lambda r: r.created_at or datetime.min.replace(tzinfo=timezone.utc))
        report_core["equity_curve_sample"] = (latest.equity_curve or [])[:120]
        report_core["drawdown_profile"] = _equity_stats(latest.equity_curve or [])

    report_core["improvements"] = _suggest_improvements(report_core)
    report_core["reproducibility_hash"] = _stable_hash(report_core)
    return report_core


def _suggest_improvements(report: dict[str, Any]) -> list[str]:
    suggestions: list[str] = []
    if report.get("win_rate", 0) < 0.45:
        suggestions.append("Win rate below 45% on clean exits — review entry filters and regime gating.")
    if report.get("stability_score", 1) < 0.7:
        suggestions.append("IS/OOS return gap is large — reduce overfitting or widen walk-forward windows.")
    breakdown = report.get("exit_breakdown", {})
    if breakdown.get(ExitClassification.NON_CLEAN_EXIT.value, 0) > breakdown.get(ExitClassification.CLEAN_EXIT.value, 0):
        suggestions.append("Non-clean exits dominate — tighten stop discipline and kill-switch thresholds.")
    if not suggestions:
        suggestions.append("Performance stable on clean exits — consider incremental sizing tests.")
    return suggestions


WEEKLY_ANALYSIS_STRATEGY = "weekly_analysis"
LEGACY_WEEKLY_TICKER = "_PORTFOLIO_"


def is_real_backtest_run(run: BacktestRun) -> bool:
    """Weekly summary rows must not look like ticker backtests (GA16-273)."""
    if run.strategy == WEEKLY_ANALYSIS_STRATEGY:
        return False
    if (run.ticker or "").strip() in {LEGACY_WEEKLY_TICKER, "—", "-"}:
        return False
    return True


async def load_runs_for_week(db: AsyncSession, *, days: int = 7) -> list[BacktestRun]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    result = await db.execute(
        select(BacktestRun)
        .where(BacktestRun.created_at >= since)
        .order_by(desc(BacktestRun.created_at))
    )
    return [r for r in result.scalars().all() if is_real_backtest_run(r)]


async def build_weekly_report(db: AsyncSession, *, days: int = 7) -> dict[str, Any]:
    """Build a versioned weekly deep analysis report."""
    runs = await load_runs_for_week(db, days=days)
    now = datetime.now(timezone.utc)
    week_label = now.strftime("%Y-W%W")
    report = aggregate_runs(runs, clean_only=True)
    report["kind"] = "weekly_backtest_analysis"
    report["week_label"] = week_label
    report["generated_at"] = now.isoformat()
    report["analysis_window_days"] = days
    return report
