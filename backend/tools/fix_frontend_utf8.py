#!/usr/bin/env python3
"""Fix UTF-8 on VPS frontend files by re-reading with cp1251 fallback."""
from pathlib import Path

ROOT = Path("/home/user1/myapp/frontend/src/components")
files = [
    ROOT / "settings/TradingAccountsPanel.tsx",
    ROOT / "trading/TokenizedEquitiesOnboarding.tsx",
    ROOT / "trading/TradingDisclosuresModal.tsx",
]

for path in files:
    if not path.exists():
        print("missing", path)
        continue
    raw = path.read_bytes()
    for enc in ("utf-8", "cp1251", "latin-1"):
        try:
            text = raw.decode(enc)
            path.write_text(text, encoding="utf-8")
            print("fixed", path, "from", enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        print("FAILED", path)

for path in files:
    try:
        path.read_text(encoding="utf-8")
        print("verify ok", path.name)
    except Exception as exc:
        print("verify FAIL", path.name, exc)
