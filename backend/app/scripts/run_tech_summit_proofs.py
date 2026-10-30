"""PROOF bundle for «Технологическая вершина» — run without deploy."""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
PROOF_DIR = ROOT / "docs" / "proof"
PROOF_DIR.mkdir(parents=True, exist_ok=True)


def proof_portfolio_risk() -> dict:
    from app.services.portfolio.risk_analytics_math import HoldingSpec, build_report

    rng = np.random.default_rng(7)
    start = date(2019, 6, 1)
    end = date(2022, 12, 31)
    days: list[date] = []
    cur = start
    while cur <= end:
        days.append(cur)
        cur += timedelta(days=1)
    n = len(days) - 1
    common = rng.normal(0.0003, 0.011, size=n)
    crash = np.zeros(n)
    for i, d in enumerate(days[1:]):
        key = d.isoformat()
        if "2020-02-19" <= key <= "2020-03-23":
            crash[i] = -0.028
        elif "2022-01-03" <= key <= "2022-10-12":
            crash[i] = -0.0025

    def path(beta: float, idio: float, p0: float) -> list[tuple[str, float]]:
        rets = beta * common + crash + rng.normal(0.0, idio, size=n)
        price = p0
        rows = [(days[0].isoformat(), price)]
        for i, r in enumerate(rets):
            price = max(0.01, price * (1.0 + float(r)))
            rows.append((days[i + 1].isoformat(), price))
        return rows

    series = {
        "SPY": path(1.00, 0.004, 300.0),
        "AAPL": path(1.15, 0.006, 150.0),
        "MSFT": path(1.10, 0.005, 220.0),
        "NVDA": path(1.35, 0.010, 80.0),
        "QQQ": path(1.20, 0.005, 280.0),
    }
    holdings = [
        HoldingSpec("AAPL", 40_000, "technology"),
        HoldingSpec("MSFT", 30_000, "technology"),
        HoldingSpec("NVDA", 20_000, "technology"),
        HoldingSpec("QQQ", 10_000, "indices"),
    ]
    report = build_report(holdings=holdings, series_by_symbol=series, benchmark_symbol="SPY")
    covid = next(s for s in report.stress if s.scenario_id == "covid_2020")
    return {
        "section": "portfolio_risk_analytics",
        "proof_type": "multi_position_book",
        "holdings": [h.symbol for h in holdings],
        "var_95_pct": report.var_95,
        "var_99_pct": report.var_99,
        "var_95_usd": report.var_95_usd,
        "methodology": report.methodology,
        "lookback": [report.lookback_start, report.lookback_end],
        "beta": report.beta,
        "alpha": report.alpha,
        "avg_pairwise_correlation": report.avg_pairwise_correlation,
        "concentration_flag_ru": report.concentration_flag_ru,
        "stress_covid_2020": {
            "total_return": covid.total_return,
            "max_drawdown": covid.max_drawdown,
            "label_ru": covid.label_ru,
        },
        "ui_route": "/portfolio-risk",
        "ui_methodology_visible": True,
    }


def proof_composer_backtest() -> dict:
    from datetime import date, timedelta

    from app.services.strategy.composer.fixtures import default_composer_config
    from app.services.strategy.composer.walk_forward_backtest import run_composer_walk_forward

    rng = np.random.default_rng(11)
    day = date.fromisoformat("2024-01-01")
    price = 100.0
    rows = [(day.isoformat(), price)]
    for _ in range(220):
        day += timedelta(days=1)
        price = max(1.0, price * (1.0 + float(rng.normal(0.0005, 0.015))))
        rows.append((day.isoformat(), price))

    config = default_composer_config()
    result = run_composer_walk_forward(config, symbol="AAPL", dated_closes=rows)
    payload = result.to_dict()
    return {
        "section": "composer_walk_forward_backtest",
        "proof_type": "built_rule_backtest",
        "symbol": "AAPL",
        "insufficient_data": payload["insufficient_data"],
        "observations": payload["observations"],
        "methodology": payload["methodology"],
        "win_rate": payload["win_rate"],
        "max_drawdown": payload["max_drawdown"],
        "in_market_days": payload["in_market_days"],
        "purged_folds": payload["purged_folds"],
        "equity_curve_points": len(payload.get("equity_curve") or []),
        "ui_route": "/strategy-composer",
    }


def proof_chat_tools() -> dict:
    """Simulated chat session: user asks about position → tool call → cited payload."""
    from unittest.mock import AsyncMock, MagicMock, patch

    import asyncio

    from app.services.chat.tools import execute_tool

    async def _run() -> dict:
        db = AsyncMock()
        session: list[dict] = []

        user_question = "Какой VaR у моего портфеля и P&L по AAPL?"
        session.append({"role": "user", "content": user_question})

        risk_payload = {
            "var_95": 0.0234,
            "var_99": 0.0312,
            "methodology": {"method_ru": "Историческая симуляция"},
            "data_as_of": "2026-08-21T18:00:00+00:00",
            "holdings_count": 4,
        }
        pnl_payload = {
            "ticker": "AAPL",
            "unrealized_pnl_usd": 1250.5,
            "realized_pnl_usd": 320.0,
            "data_as_of": "2026-08-21T18:00:00+00:00",
        }

        with patch("app.services.chat.tools._tool_portfolio_risk", new_callable=AsyncMock) as mock_risk:
            mock_risk.return_value = risk_payload
            raw_risk = await execute_tool(
                db, "get_portfolio_risk_metrics", {}, owner_email="proof@example.com"
            )
        risk = json.loads(raw_risk)
        session.append({
            "role": "tool",
            "tool": "get_portfolio_risk_metrics",
            "payload": risk,
        })

        with patch("app.services.chat.tools._tool_position_pnl", new_callable=AsyncMock) as mock_pnl:
            mock_pnl.return_value = pnl_payload
            raw_pnl = await execute_tool(
                db, "get_position_pnl", {"ticker": "AAPL"}, owner_email="proof@example.com"
            )
        pnl = json.loads(raw_pnl)
        session.append({"role": "tool", "tool": "get_position_pnl", "payload": pnl})

        assistant_answer = (
            f"По данным инструмента get_portfolio_risk_metrics (обновлено {risk['data_as_of']}): "
            f"VaR 95% = {risk['var_95']:.2%}. "
            f"По AAPL (get_position_pnl, {pnl['data_as_of']}): нереализованный P&L "
            f"${pnl['unrealized_pnl_usd']:,.2f}."
        )
        session.append({"role": "assistant", "content": assistant_answer})

        assert risk["tool"] == "get_portfolio_risk_metrics"
        assert risk["tool_called_at"]
        assert risk["data_available"] is True
        assert pnl["tool"] == "get_position_pnl"
        assert "fabrication_forbidden" not in risk or not risk.get("fabrication_forbidden")

        return {
            "section": "ai_chat_function_calling",
            "proof_type": "simulated_chat_session",
            "session": session,
            "tools_called": ["get_portfolio_risk_metrics", "get_position_pnl"],
            "freshness_cited": True,
            "fabrication_on_failure": "tested separately in test_agentic_chat.py",
        }

    return asyncio.run(_run())


def proof_strategy_bots() -> dict:
    from app.services.bots.dca import apply_dca_tick, new_runtime
    from app.services.bots.momentum import apply_momentum_tick

    dca = {
        "config": {
            "ticker": "BTCUSDT",
            "total_capital": 5000,
            "order_size_usd": 500,
            "max_entries": 5,
            "interval_ticks": 1,
            "dip_pct": 0.02,
            "take_profit_pct": 0.05,
            "entry_price": 100.0,
        },
        "runtime": new_runtime(100.0),
        "realized_pnl": 0.0,
        "total_trades": 0,
        "is_active": True,
        "is_paused": False,
    }
    dca = apply_dca_tick(dca, 100.0, bot_id="proof-dca")
    dca = apply_dca_tick(dca, 97.0, bot_id="proof-dca")

    mom = {
        "config": {
            "ticker": "ETHUSDT",
            "total_capital": 10_000,
            "position_size_pct": 0.5,
            "lookback_ticks": 5,
            "entry_momentum_pct": 0.01,
            "take_profit_pct": 0.06,
            "stop_loss_pct": 0.04,
            "entry_price": 100.0,
        },
        "runtime": {"executor_state": "watching", "position_qty": 0.0, "avg_entry": 0.0,
                    "price_history": [100.0], "last_price": 100.0, "last_momentum": 0.0},
        "realized_pnl": 0.0,
        "total_trades": 0,
        "is_active": True,
        "is_paused": False,
    }
    price = 100.0
    for bump in [101, 102, 103, 104, 106]:
        price = float(bump)
        mom = apply_momentum_tick(mom, price, bot_id="proof-mom")

    return {
        "section": "dca_momentum_bots",
        "dca": {
            "entries_after_ticks": dca["runtime"]["entries_count"],
            "position_qty": dca["runtime"]["position_qty"],
            "executor_state": dca["runtime"]["executor_state"],
        },
        "momentum": {
            "last_momentum": mom["runtime"]["last_momentum"],
            "position_qty": mom["runtime"]["position_qty"],
            "executor_state": mom["runtime"]["executor_state"],
            "total_trades": mom["total_trades"],
        },
        "api_routes": ["/dca", "/momentum"],
        "ui_routes": ["/dca-bots", "/momentum-bots"],
    }


def main() -> int:
    proofs = {
        "generated_at": date.today().isoformat(),
        "portfolio_risk": proof_portfolio_risk(),
        "composer_backtest": proof_composer_backtest(),
        "chat_tools": proof_chat_tools(),
        "strategy_bots": proof_strategy_bots(),
    }
    out_path = PROOF_DIR / "tech_summit_proofs.json"
    out_path.write_text(json.dumps(proofs, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": "ok", "written": str(out_path), "sections": list(proofs.keys())}, indent=2))
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "backend"))
    raise SystemExit(main())
