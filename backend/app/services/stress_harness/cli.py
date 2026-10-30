"""
CLI entry point for StressHarness (Prompt 27).

Usage:
    python -m app.services.stress_harness.cli --profile-id USER_UUID
    python -m app.services.stress_harness.cli --profile-id USER_UUID --scenario rate_shock --shock 100
    python -m app.services.stress_harness.cli --profile-id USER_UUID --json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

from app.core.logging import get_logger, setup_logging
from app.db.session import AsyncSessionLocal
from app.services.scenario.types import ScenarioName
from app.services.stress_harness import CustomScenarioRequest, StressHarness

logger = get_logger(__name__)


async def _run(args: argparse.Namespace) -> dict:
    harness = StressHarness()
    async with AsyncSessionLocal() as db:
        context = await harness.loader.load_profile_portfolio(
            db,
            args.profile_id,
            portfolio_value_usd=args.portfolio_value,
        )
        if not context.portfolio.positions:
            raise RuntimeError("No open portfolio positions found for stress testing")

        if args.scenario:
            scenario = ScenarioName(args.scenario)
            report = harness.run_custom_scenario(
                context,
                CustomScenarioRequest(
                    scenario=scenario,
                    shock_strength=args.shock,
                    target_instrument_id=args.target_instrument_id,
                    target_sector=args.target_sector,
                ),
            )
        else:
            report = harness.run_all_scenarios(
                context,
                target_instrument_id=args.target_instrument_id,
                target_sector=args.target_sector,
            )
    return report.to_dict()


def main() -> int:
    setup_logging()
    parser = argparse.ArgumentParser(description="Run portfolio stress harness")
    parser.add_argument("--profile-id", required=True, help="Profile / user UUID")
    parser.add_argument(
        "--scenario",
        choices=[name.value for name in ScenarioName],
        help="Run a single custom scenario instead of the full suite",
    )
    parser.add_argument("--shock", type=float, default=50.0, help="Shock strength parameter")
    parser.add_argument("--target-instrument-id", type=int, default=None)
    parser.add_argument("--target-sector", default=None)
    parser.add_argument("--portfolio-value", type=float, default=None, help="Portfolio USD notional")
    parser.add_argument("--json", action="store_true", help="Output raw JSON report")
    args = parser.parse_args()

    try:
        result = asyncio.run(_run(args))
    except Exception as exc:
        logger.error("Stress harness failed", error=str(exc))
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        worst = result["worst_scenario"]
        print(f"\nStress report — profile {result['profile_id']}")
        print(f"Portfolio value: ${result['portfolio_value_usd']:,.0f}")
        print(f"Worst scenario: {worst['scenario_name']} (loss ${abs(worst['estimated_pnl_usd']):,.0f})")
        print(f"Max loss: {result['max_loss_fraction'] * 100:.2f}% (${result['max_loss_usd']:,.0f})")
        print(f"Scenarios run: {len(result['scenario_results'])}")
        review_count = len(result["positions_to_review"])
        print(f"Positions to review: {review_count}")
        for row in result["scenario_results"]:
            print(
                f"  - {row['scenario_name']}: "
                f"P&L ${row['estimated_pnl_usd']:,.0f}, "
                f"Δvar {row['portfolio_variance_delta']:.6f}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
