"""K3 RF tax demo. Money math lives in target_portfolio.tax (one source of truth)."""

from app.services.tax_rf.service import demo_tax_payload, lth_unlock_date

__all__ = ["demo_tax_payload", "lth_unlock_date"]
