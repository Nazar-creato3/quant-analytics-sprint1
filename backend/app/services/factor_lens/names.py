"""Russian factor lens names and orthogonalization order (prompt 65, R10)."""
from __future__ import annotations

from enum import StrEnum

FACTOR_ORDER: tuple[str, ...] = (
    "market",
    "rates",
    "credit",
    "fx",
    "oil",
    "size",
    "value",
    "momentum",
    "dividends",
)

FACTOR_LABELS_RU: dict[str, str] = {
    "market": "рынок",
    "rates": "ставка",
    "credit": "кредит",
    "fx": "рубль",
    "oil": "нефть",
    "size": "размер",
    "value": "стоимость",
    "momentum": "моментум",
    "dividends": "дивиденды",
    "idiosyncratic": "собственный риск бумаг",
}

FX_USD_WEIGHT = 0.5
FX_CNY_WEIGHT = 0.5
RIDGE_LAMBDA = 1e-3
INDUSTRY_SHRINK = 0.25
BETA_WINDOW = 756  # ~3y of trading days
LOW_R2 = 0.5
ORTHO_CORR_LIMIT = 0.05


class FactorName(StrEnum):
    MARKET = "market"
    RATES = "rates"
    CREDIT = "credit"
    FX = "fx"
    OIL = "oil"
    SIZE = "size"
    VALUE = "value"
    MOMENTUM = "momentum"
    DIVIDENDS = "dividends"
