"""Remove age / income / expenses / savings / education stored by older profile versions.

Dry run by default: `python -m app.scripts.scrub_profile_personal_fields`
Apply:             `python -m app.scripts.scrub_profile_personal_fields --apply`
"""
from __future__ import annotations

import sys


def main(argv: list[str]) -> int:
    from app.services.investment_profile.service import LEGACY_PERSONAL_FIELDS, scrub_personal_fields
    from app.services.qa import durable_store

    rows = durable_store.load("investment_profiles")
    affected = [uid for uid, row in rows.items() if any(k in row for k in LEGACY_PERSONAL_FIELDS)]
    print(f"Анкет с личными полями: {len(affected)} из {len(rows)}")
    if "--apply" not in argv:
        print("Проверка без изменений. Для удаления запустите с --apply")
        return 0
    print(f"Очищено анкет: {scrub_personal_fields()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
