"""K3 tax estimates for RF rules. Demo-only until lawyer confirms methodology."""

from app.services.tax_ru.rates import coupon_ndfl_rate, rates_snapshot
from app.services.tax_ru.service import explain_tax

__all__ = ["coupon_ndfl_rate", "explain_tax", "rates_snapshot"]
