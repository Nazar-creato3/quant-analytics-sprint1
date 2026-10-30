"""python -m app.services.maneuver_history --seed 38"""
from __future__ import annotations

import argparse
import logging

from app.services.maneuver_history.simulate import run_validation


def main() -> None:
    parser = argparse.ArgumentParser(description="Walk-forward maneuver history")
    parser.add_argument("--seed", type=int, default=38)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    result = run_validation(seed=args.seed, write=True)
    print(
        f"status={result.get('status')} seed={result.get('seed')} "
        f"scenarios={result.get('scenario_count')} leak_failures={result.get('leak_failures')}"
    )


if __name__ == "__main__":
    main()
