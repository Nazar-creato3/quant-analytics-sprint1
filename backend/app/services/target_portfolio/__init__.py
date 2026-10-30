"""Target portfolio (Prompt 36). Prompt 37 calls build_target."""

from app.services.target_portfolio.service import build_for_user, build_target, construct
from app.services.target_portfolio.types import METHODS, MODEL_VERSION

__all__ = ["METHODS", "MODEL_VERSION", "build_for_user", "build_target", "construct"]
