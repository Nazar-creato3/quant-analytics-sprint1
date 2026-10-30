from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class TradingMode(str, Enum):
    PAPER = "paper"
    LIVE = "live"


class TradingAccountBase(BaseModel):
    name: str
    base_currency: str = "USD"
    mode: TradingMode = TradingMode.PAPER


class TradingAccountCreate(TradingAccountBase):
    pass


class TradingAccountUpdate(BaseModel):
    name: str | None = None
    base_currency: str | None = None
    mode: TradingMode | None = None


class TradingAccountRead(TradingAccountBase):
    id: str
    user_id: str
    created_at: datetime

    class Config:
        from_attributes = True

from datetime import datetime
from pydantic import BaseModel


class TradingStrategyBase(BaseModel):
    name: str
    description: str | None = None
    is_active: bool = True
    account_id: str


class TradingStrategyCreate(TradingStrategyBase):
    pass


class TradingStrategyRead(TradingStrategyBase):
    id: str
    user_id: str
    created_at: datetime

    class Config:
        from_attributes = True





















        