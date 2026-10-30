"""Give the e2e app role its published test password. Refuses to run otherwise."""
from __future__ import annotations

import os

from sqlalchemy import create_engine, text


def require_app_db_password() -> str:
    """Password comes from the environment. It is never logged."""
    flag = os.environ.get("QA_E2E_DEMO", "").strip().lower()
    if flag not in {"1", "true", "yes"}:
        raise SystemExit("refusing to set the app role password outside QA_E2E_DEMO")
    password = os.environ.get("APP_DB_PASSWORD", "").strip()
    if not password.isalnum():
        raise SystemExit("APP_DB_PASSWORD must be alphanumeric and non-empty")
    return password


def main() -> None:
    password = require_app_db_password()
    url = os.environ["MIGRATION_DATABASE_URL_SYNC"]
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(text(f"ALTER ROLE appuser WITH LOGIN PASSWORD '{password}'"))
    print("OK_appuser_password_set")


if __name__ == "__main__":
    main()
