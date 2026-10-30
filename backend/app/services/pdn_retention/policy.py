"""Retention policy constants and purge planner.

Founder 08.10:
- account open: keep while open
- after delete: <= 30 days including backups
- security logs: 6 months
- payments: 5 years
- waitlist: until unsubscribe, or 6 months after launch
- interviews: 6 months
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone


@dataclass(frozen=True)
class RetentionRule:
    key: str
    max_age_days: int | None
    note: str


RULES: tuple[RetentionRule, ...] = (
    RetentionRule("account_open", None, "keep while account is open"),
    RetentionRule("account_after_delete", 30, "including backups"),
    RetentionRule("security_logs", 182, "6 months"),
    RetentionRule("payments", 1825, "5 years"),
    RetentionRule("waitlist_unsubscribed", 0, "delete on unsubscribe"),
    RetentionRule("waitlist_after_launch", 182, "6 months after launch if no unsubscribe"),
    RetentionRule("interviews", 182, "6 months"),
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def is_expired(
    *,
    kind: str,
    created_at: datetime,
    now: datetime | None = None,
    launch_at: datetime | None = None,
) -> bool:
    now = now or utcnow()
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    if kind == "account_open":
        return False
    if kind == "waitlist_unsubscribed":
        return True
    if kind == "waitlist_after_launch":
        if launch_at is None:
            return False
        if launch_at.tzinfo is None:
            launch_at = launch_at.replace(tzinfo=timezone.utc)
        return now >= launch_at + timedelta(days=182)
    rule = next((r for r in RULES if r.key == kind), None)
    if rule is None or rule.max_age_days is None:
        return False
    return now >= created_at + timedelta(days=rule.max_age_days)


def plan_purge(
    records: list[dict],
    *,
    now: datetime | None = None,
    launch_at: datetime | None = None,
) -> list[str]:
    now = now or utcnow()
    out: list[str] = []
    for row in records:
        if is_expired(
            kind=str(row["kind"]),
            created_at=row["created_at"],
            now=now,
            launch_at=launch_at,
        ):
            out.append(str(row["id"]))
    return out
