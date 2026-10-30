#!/usr/bin/env python3
"""Fix config.py Bybit fields placement."""
from pathlib import Path

p = Path("/home/user1/myapp/backend/app/core/config.py")
text = p.read_text(encoding="utf-8")

# Remove wrongly appended fields
text = text.replace(
    "\n    BYBIT_API_BASE_URL: str = \"https://api.bybit.com\"\n    EXECUTION_SERVER_PUBLIC_IP: str | None = None\n",
    "\n",
)

if "BYBIT_API_BASE_URL" not in text:
    needle = '    ALPACA_OAUTH_REDIRECT_URI: str = ""\n'
    insert = needle + (
        '    BYBIT_API_BASE_URL: str = "https://api.bybit.com"\n'
        "    EXECUTION_SERVER_PUBLIC_IP: str | None = None\n"
    )
    text = text.replace(needle, insert, 1)

p.write_text(text, encoding="utf-8")
print("config fixed")
