#!/usr/bin/env python3
"""One-shot forecast retrain trigger (run inside celery-pipeline container)."""
from __future__ import annotations

from app.tasks.forecast import retrain_forecast_models_task


def main() -> None:
    result = retrain_forecast_models_task.apply(args=(["AAPL", "MSFT", "SPY"],)).get(timeout=600)
    print(result)


if __name__ == "__main__":
    main()
