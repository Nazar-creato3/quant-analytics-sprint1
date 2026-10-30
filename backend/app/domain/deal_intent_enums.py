"""DealIntent-specific enumerations."""
from __future__ import annotations

from enum import Enum


class DealIntentDirection(str, Enum):
    LONG = "long"
    SHORT = "short"


class TriggerType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    CONDITION = "condition"


class TimeInForce(str, Enum):
    DAY = "day"
    GTC = "gtc"
    IOC = "ioc"
    FOK = "fok"
    GTD = "gtd"


class RiskTag(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EVENT_RISK = "event_risk"


class DealIntentStatus(str, Enum):
    DRAFT = "draft"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    HELD = "held"
    EXECUTING = "executing"
    FILLED = "filled"
    CANCELLED = "cancelled"
    FAILED = "failed"


TERMINAL_DEAL_INTENT_STATUSES: frozenset[DealIntentStatus] = frozenset(
    {
        DealIntentStatus.REJECTED,
        DealIntentStatus.FILLED,
        DealIntentStatus.CANCELLED,
        DealIntentStatus.FAILED,
    }
)
