"""Desk operators extracted from the research stack — not textbook dumps.

Physical-measure trading (this factory) stays separate from risk-neutral pricing.
"""
from app.services.quant_desk.overlays import apply_to_risk, desk_overlay

__all__ = ["apply_to_risk", "desk_overlay"]
