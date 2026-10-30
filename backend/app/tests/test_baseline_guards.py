"""Static guards for the NEVER REGRESS baseline — no secrets, no network."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
BASELINE_DIR = REPO_ROOT / "docs" / "baseline"
MANIFEST_PATH = BASELINE_DIR / "manifest.json"
CRITICAL_MODULES_PATH = BASELINE_DIR / "CRITICAL_MODULES.md"
ENV_TEMPLATE_PATH = BASELINE_DIR / "baseline-env-template.md"
POLICY_PATH = REPO_ROOT / "docs" / "BASELINE_NO_REGRESS.md"

TAG_PATTERN = re.compile(r"^baseline/no-regress-\d{8}$")
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")

REQUIRED_SCRIPTS = (
    "scripts/capture_baseline_snapshot.ps1",
    "scripts/rollback_to_baseline.ps1",
    "scripts/restore_baseline.ps1",
)

REQUIRED_HEALTH_TESTS = (
    "test_market_data_freshness",
    "test_no_cross_user_position_leak",
    "test_chat_no_raw_debug_output",
    "test_websocket_delivers_message",
)

HEALTH_ALIASES_MARKERS = (
    'router.get("/market/indices")',
    'router.get("/positions")',
    'router.post("/chat")',
)


@pytest.fixture(scope="module")
def manifest() -> dict:
    assert MANIFEST_PATH.is_file(), f"missing {MANIFEST_PATH.relative_to(REPO_ROOT)}"
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_manifest_required_fields(manifest: dict) -> None:
    for key in ("tag", "sha", "branch", "created_at", "policy_version", "what_works"):
        assert key in manifest, f"manifest missing key: {key}"
    assert TAG_PATTERN.match(manifest["tag"]), manifest["tag"]
    assert SHA_PATTERN.match(manifest["sha"]), manifest["sha"]
    assert isinstance(manifest["what_works"], list) and len(manifest["what_works"]) >= 5


def test_critical_modules_doc_exists() -> None:
    text = CRITICAL_MODULES_PATH.read_text(encoding="utf-8")
    assert "Tier 1" in text
    assert "health_check_aliases" in text.lower() or "Health aliases" in text


def test_baseline_env_template_names_only() -> None:
    text = ENV_TEMPLATE_PATH.read_text(encoding="utf-8")
    assert "SECRET_KEY" in text
    assert "changeme" not in text.lower()
    assert "REPLACE_WITH" not in text


def test_policy_doc_exists() -> None:
    assert POLICY_PATH.is_file()
    body = POLICY_PATH.read_text(encoding="utf-8")
    assert "baseline/no-regress-" in body
    assert "rollback_to_baseline" in body


def test_baseline_scripts_exist() -> None:
    for rel in REQUIRED_SCRIPTS:
        assert (REPO_ROOT / rel).is_file(), rel


def test_critical_test_files_exist(manifest: dict) -> None:
    for rel in manifest.get("critical_test_files", []):
        path = REPO_ROOT / "backend" / rel
        assert path.is_file(), rel


def test_health_regression_tests_present() -> None:
    path = REPO_ROOT / "backend" / "app" / "tests" / "test_health_regression.py"
    text = path.read_text(encoding="utf-8")
    for name in REQUIRED_HEALTH_TESTS:
        assert f"def {name}" in text, name


def test_health_check_aliases_routes() -> None:
    path = REPO_ROOT / "backend" / "app" / "api" / "health_check_aliases.py"
    text = path.read_text(encoding="utf-8")
    for marker in HEALTH_ALIASES_MARKERS:
        assert marker in text, marker


def test_cursor_rule_exists() -> None:
    rule = REPO_ROOT / ".cursor" / "rules" / "no-regress-baseline.mdc"
    assert rule.is_file()
    assert "baseline/no-regress" in rule.read_text(encoding="utf-8")


def test_manifest_restore_scripts_exist(manifest: dict) -> None:
    for rel in manifest.get("restore_scripts", []):
        assert (REPO_ROOT / rel).is_file(), rel
