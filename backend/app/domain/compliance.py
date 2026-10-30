"""Compliance domain types — jurisdiction, account class, broker agreement."""
from __future__ import annotations

from enum import Enum


class Jurisdiction(str, Enum):
    """Regulatory jurisdiction governing market access."""

    GLOBAL = "global"
    US = "us"
    EU = "eu"
    UK = "uk"
    RU = "ru"


class AccountType(str, Enum):
    """Broker account classification affecting product eligibility."""

    RETAIL = "retail"
    PROFESSIONAL = "professional"
    INSTITUTIONAL = "institutional"


class BrokerAgreementStatus(str, Enum):
    """Status of signed broker/market-access agreements."""

    PENDING = "pending"
    SIGNED = "signed"
    SUSPENDED = "suspended"
    REVOKED = "revoked"
