#!/usr/bin/env python3
"""Create (or re-activate) an account by the operator, bypassing public signup.

Public registration stays closed until approved legal texts + RKN notice
(app/services/legal/gates.py). Team members and invited testers get accounts here.

Run inside the backend container:
  docker compose -f docker-compose.yml -f docker-compose.prod.yml exec backend \
      python scripts/create_user.py user@example.com --role admin
The password is asked interactively and never printed.
"""
from __future__ import annotations

import argparse
import asyncio
import getpass
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select

from app.core.security import hash_password
from app.db.models import User, UserRole
from app.db.session import AsyncSessionLocal


async def _optional(db, label: str, make_coro) -> None:
    """Run an extra step in a savepoint so its failure cannot roll back the account."""
    try:
        async with db.begin_nested():
            await make_coro()
    except Exception as exc:  # noqa: BLE001 - extras must not block account creation
        print(f"  ({label} skipped: {type(exc).__name__})")


async def main(email: str, role: str, password: str) -> int:
    email = email.strip().lower()
    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == email))).scalar_one_or_none()
        created = user is None
        if created:
            user = User(email=email, hashed_password=hash_password(password))
            db.add(user)
        else:
            user.hashed_password = hash_password(password)
        user.role = UserRole(role)
        user.is_active = True
        user.is_whitelisted = True
        user.must_change_password = False
        user.email_verified_at = user.email_verified_at or now
        user.trial_started_at = user.trial_started_at or now
        await db.flush()

        if created:
            from app.services.access_policy.service import access_policy_service
            from app.services.settings.new_user_defaults import seed_new_user_settings
            from app.services.subscription.paywall import paywall_subscription_service

            uid = user.id
            await _optional(db, "trial", lambda: access_policy_service.start_trial(db, uid))
            await _optional(
                db, "paywall trial", lambda: paywall_subscription_service.start_trial_on_first_login(db, uid)
            )
            await _optional(db, "default settings", lambda: seed_new_user_settings(db, email))
        await db.commit()
    print(("Created" if created else "Updated") + f": {email} (role={role})")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("email")
    parser.add_argument("--role", choices=[r.value for r in UserRole], default="viewer")
    args = parser.parse_args()
    pw = getpass.getpass("Password (min 10 chars): ")
    if len(pw) < 10 or pw != getpass.getpass("Repeat: "):
        print("Passwords do not match or are shorter than 10 characters.")
        raise SystemExit(1)
    raise SystemExit(asyncio.run(main(args.email, args.role, pw)))
