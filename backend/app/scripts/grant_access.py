"""Give a founder / team / expert demo account working access (paper mode, no payment).

    docker compose ... exec backend python -m app.scripts.grant_access --email you@example.com
    docker compose ... exec backend python -m app.scripts.grant_access --email expert@example.com --show
    docker compose ... exec backend python -m app.scripts.grant_access --email expert@example.com --create

--create makes the account first (for an expert demo login while public sign-up is closed):
the password is typed twice with hidden input and never printed; the e-mail is marked
confirmed. The expert accepts the user agreement and the personal-data consent himself
on first sign-in — the operator does not accept them on his behalf.

Sets the access level to paper_trading (every analytics and paper-mode feature, bots included;
real-money trading stays off) and marks the subscription as granted by the operator, so the
trial paywall does not lock the account. --show only prints the current state.
"""
from __future__ import annotations

import argparse
import asyncio


def _ask_password() -> str:
    import getpass

    first = getpass.getpass("Пароль для входа (не отображается): ")
    if len(first) < 8:
        raise SystemExit("Пароль короче 8 символов — учётная запись не создана")
    if getpass.getpass("Повторите пароль: ") != first:
        raise SystemExit("Пароли не совпали — учётная запись не создана")
    return first


async def run(email: str, show: bool, create: bool = False) -> None:
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.db.models import User
    from app.db.session import AsyncSessionLocal
    from app.domain.access_policy import AccessLevel
    from app.services.access_policy.service import access_policy_service
    from app.services.subscription.paywall import paywall_subscription_service

    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(User).where(User.email == email.lower()))).scalar_one_or_none()
        if user is None and create:
            from app.core.security import hash_password
            from app.db.models import UserRole

            now = datetime.now(timezone.utc)
            user = User(
                email=email.lower().strip(),
                hashed_password=hash_password(_ask_password()),
                role=UserRole.VIEWER,
                is_active=True,
                is_whitelisted=True,
                email_verified_at=now,
                trial_started_at=now,
            )
            db.add(user)
            await db.flush()
            print(f"{email}: учётная запись создана")
        elif user is None:
            print(f"Пользователь {email} не найден (добавьте --create, чтобы создать)")
            return
        policy = await access_policy_service.read(db, user.id)
        print(f"{email}: уровень доступа {policy.access_level.value}")
        if show:
            return
        if policy.access_level != AccessLevel.PAPER_TRADING:
            await access_policy_service.set_level(
                db, user.id, AccessLevel.PAPER_TRADING, approved=True, reason="operator_grant"
            )
        await paywall_subscription_service.mark_paid(db, user.id, external_ref="operator_grant")
        await db.commit()
        policy = await access_policy_service.read(db, user.id)
        print(f"{email}: теперь {policy.access_level.value}, подписка выдана оператором")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--email", required=True)
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--create", action="store_true", help="создать учётную запись, если её нет")
    args = ap.parse_args()
    asyncio.run(run(args.email, args.show, args.create))


if __name__ == "__main__":
    main()
