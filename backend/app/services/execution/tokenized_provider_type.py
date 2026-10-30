"""Tokenized equity execution provider types (Bybit primary, MEXC alternate)."""
from __future__ import annotations

from enum import Enum
from typing import Literal

TokenizedEquityProviderType = Literal["bybit", "mexc"]

TOKENIZED_EQUITY_VENUE = "tokenized_equity"


class TokenizedProvider(str, Enum):
    BYBIT = "bybit"
    MEXC = "mexc"

    @classmethod
    def normalize(cls, value: str | None) -> "TokenizedProvider":
        if not value:
            return cls.BYBIT
        v = value.lower().strip()
        if v in ("mexc", "mexc_tokenized"):
            return cls.MEXC
        return cls.BYBIT
