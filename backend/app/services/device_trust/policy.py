"""Device Trust Engine strategies (Prompt 62)."""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.domain.rbac import TrustLevel


@dataclass
class DevicePolicyDecision:
    allowed: bool
    reason: str
    require_manual_review: bool = False


class DevicePolicyStrategy(ABC):
    @abstractmethod
    def evaluate(
        self,
        *,
        active_devices: int,
        accounts_on_device: int,
        is_new_account_on_device: bool,
    ) -> DevicePolicyDecision:
        ...


class StandardUserPolicy(DevicePolicyStrategy):
    # Allow phone + tablet + desktop without blocking login on a second device.
    max_active_devices = 5
    max_active_accounts_per_device = 3

    def evaluate(
        self,
        *,
        active_devices: int,
        accounts_on_device: int,
        is_new_account_on_device: bool,
    ) -> DevicePolicyDecision:
        if active_devices >= self.max_active_devices:
            return DevicePolicyDecision(False, "max_active_devices", True)
        if is_new_account_on_device and accounts_on_device >= self.max_active_accounts_per_device:
            return DevicePolicyDecision(False, "max_accounts_per_device", True)
        return DevicePolicyDecision(True, "ok")


class PrivilegedIdentityPolicy(DevicePolicyStrategy):
    """Privileged: unlimited devices/accounts; never blocked by anti-abuse."""

    def evaluate(
        self,
        *,
        active_devices: int,
        accounts_on_device: int,
        is_new_account_on_device: bool,
    ) -> DevicePolicyDecision:
        return DevicePolicyDecision(True, "privileged_allow")


def policy_for_trust_level(trust: TrustLevel | str) -> DevicePolicyStrategy:
    t = TrustLevel(trust) if not isinstance(trust, TrustLevel) else trust
    if t == TrustLevel.PRIVILEGED:
        return PrivilegedIdentityPolicy()
    return StandardUserPolicy()
