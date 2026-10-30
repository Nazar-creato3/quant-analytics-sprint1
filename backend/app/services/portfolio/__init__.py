"""Portfolio services."""

from typing import Any

__all__ = ["build_portfolio_metrics"]


def __getattr__(name: str) -> Any:
    if name == "build_portfolio_metrics":
        from app.services.portfolio.metrics import build_portfolio_metrics

        return build_portfolio_metrics
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
