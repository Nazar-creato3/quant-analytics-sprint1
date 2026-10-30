"""Cap (deploy budget) cannot exceed account total (all money on trading venues)."""
from __future__ import annotations

_EPS_USD = 0.01


def clamp_cap_to_balance(cap_usd: float, account_total_usd: float) -> float:
    """Return deploy cap that never exceeds 100% of account total."""
    cap = max(0.0, float(cap_usd or 0.0))
    total = max(0.0, float(account_total_usd or 0.0))
    return round(min(cap, total), 2)


def cap_exceeds_balance(cap_usd: float, account_total_usd: float) -> bool:
    return float(cap_usd or 0.0) > float(account_total_usd or 0.0) + _EPS_USD
