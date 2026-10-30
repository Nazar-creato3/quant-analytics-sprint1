#!/usr/bin/env python3
"""Screenshot: MSFT shows Bybit unlisted message before order form."""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE_URL = os.environ.get("HEALTH_CHECK_BASE_URL", "https://quantanalyticsclub.ru").rstrip("/")
EMAIL = os.environ.get("TEST_USER_A_EMAIL", "").strip()
PASSWORD = os.environ.get("TEST_USER_A_PASSWORD", "").strip()
OUT = Path(os.environ.get("SCREENSHOT_OUT", "/tmp/bybit_unlisted_msft.png"))


def main() -> int:
    if not EMAIL or not PASSWORD:
        print("SKIP missing TEST_USER_A_EMAIL/PASSWORD")
        return 2

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(f"{BASE_URL}/login")
        page.fill("#login-email", EMAIL)
        page.fill("#login-password", PASSWORD)
        page.click('button[type="submit"]')
        page.wait_for_url(re.compile(r".*/(terminal|operator|dashboard|settings|direct-deals).*"), timeout=60_000)

        page.goto(f"{BASE_URL}/direct-deals?symbol=MSFT")
        page.wait_for_load_state("networkidle", timeout=60_000)
        page.get_by_role("button", name="Торговля").click()
        page.get_by_text("Тикер недоступен на Bybit", exact=False).wait_for(timeout=30_000)
        page.get_by_text("этот тикер пока недоступен через Bybit", exact=False).wait_for(timeout=15_000)

        OUT.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(OUT), full_page=False)
        browser.close()

    print("SCREENSHOT_OK", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
