#!/usr/bin/env python3
"""Browser E2E: Settings tokenized provider toggle visibly switches Bybit/MEXC."""
from __future__ import annotations

import os
import re
import sys

from playwright.sync_api import sync_playwright

BASE_URL = os.environ.get("HEALTH_CHECK_BASE_URL", "https://quantanalyticsclub.ru").rstrip("/")
EMAIL = os.environ.get("TEST_USER_A_EMAIL", "").strip()
PASSWORD = os.environ.get("TEST_USER_A_PASSWORD", "").strip()

SELECTED_RE = re.compile(r"border-emerald-500/50")


def _login(page) -> None:
    page.goto(f"{BASE_URL}/login")
    page.fill("#login-email", EMAIL)
    page.fill("#login-password", PASSWORD)
    page.click('button[type="submit"]')
    page.wait_for_url(re.compile(r".*/(terminal|operator|dashboard|settings).*"), timeout=60_000)


def _selected_label(page) -> str:
    for label in ("Bybit (primary)", "MEXC (alternate)"):
        btn = page.get_by_role("button", name=label)
        cls = btn.get_attribute("class") or ""
        if SELECTED_RE.search(cls):
            return label
    raise AssertionError("no provider button appears selected")


def main() -> int:
    if not EMAIL or not PASSWORD:
        print("SKIP missing TEST_USER_A_EMAIL/PASSWORD")
        return 2

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        _login(page)
        page.goto(f"{BASE_URL}/settings")
        page.wait_for_load_state("networkidle", timeout=60_000)
        page.get_by_text("Tokenized equity provider (execution routing)").wait_for(timeout=30_000)

        start = _selected_label(page)
        target = "MEXC (alternate)" if start == "Bybit (primary)" else "Bybit (primary)"
        page.get_by_role("button", name=target).click()
        page.get_by_text("Execution provider updated", exact=False).wait_for(timeout=15_000)
        after = _selected_label(page)
        assert after == target, f"expected selected {target}, got {after}"

        # Toggle back to confirm bidirectional switch
        page.get_by_role("button", name=start).click()
        page.get_by_text("Execution provider updated", exact=False).wait_for(timeout=15_000)
        restored = _selected_label(page)
        assert restored == start, f"expected restore to {start}, got {restored}"

        browser.close()

    print(f"SETTINGS_TOGGLE_E2E_OK start={start} switched_to={target} restored={start}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
