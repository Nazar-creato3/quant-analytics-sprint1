"""Lawyer catalog: drafts, hashes, fail-closed gates, no approved placeholders."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import settings
from app.services.legal.catalog import (
    REQUIRED_CODES,
    CatalogError,
    get_document,
    load_decisions,
    load_ui_texts,
    reset_cache,
    validate_catalog,
)
from app.services.legal.gates import payment_open, registration_open, waitlist_open
from app.services.legal.yaml_lite import load as load_yaml
from app.services.waitlist.service import join
from app.services.waitlist.service import reset as reset_waitlist
from app.services.subscription_billing.service import quote

REPO = Path(__file__).resolve().parents[3]
FORBIDDEN = (
    "рекомендуем",
    "советуем",
    "подходит вам",
    "соответствует вашему профилю",
    "купите",
    "продайте",
)


def setup_function() -> None:
    reset_cache()
    reset_waitlist()


def teardown_function() -> None:
    reset_cache()
    reset_waitlist()


def test_catalog_has_required_drafts_and_matching_sha256() -> None:
    assert validate_catalog() == []
    for code in REQUIRED_CODES:
        row = get_document(code)
        assert row is not None, code
        assert row["status"] == "draft"
        assert row["version"] == "0.1.0"
        assert len(row["sha256"]) == 64
        path = REPO / row["path"]
        raw = path.read_text(encoding="utf-8")
        body = raw.split("---", 2)[2].lstrip("\n")
        import hashlib

        assert hashlib.sha256(body.encode("utf-8")).hexdigest() == row["sha256"]
    rkn = get_document("rkn_notice")
    assert rkn is not None
    assert rkn["status"] == "draft"
    assert (REPO / "legal" / "ui_texts.ru.yaml").is_file()
    decisions = load_decisions()
    assert set(decisions) == {f"L-{i:02d}" for i in range(1, 13)}


def test_consent_split_keeps_lawyer_wording() -> None:
    src = (REPO / "legal" / "README.md").read_text(encoding="utf-8")
    assert "Тексты не переписывать" in src
    pd = get_document("consent_pd")
    assert pd is not None
    assert "Я, зарегистрированный пользователь сервиса Quant Analytics" in pd["body"]
    wait = get_document("consent_waitlist")
    assert wait is not None
    assert "в целях ведения листа ожидания" in wait["body"]


def test_approved_unfilled_placeholder_is_catalog_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.legal import catalog as catalog_mod

    sample = tmp_path / "privacy" / "9.9.9.md"
    sample.parent.mkdir()
    (tmp_path / "operator.yaml").write_text(
        (REPO / "legal" / "operator.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    body = "Оператор {{operator.full_name}}\n"
    digest = __import__("hashlib").sha256(body.encode("utf-8")).hexdigest()
    sample.write_text(
        "---\ncode: privacy\nversion: 9.9.9\neffective_date: null\nstatus: approved\n"
        f"approved_by: test\nsha256: {digest}\n---\n\n{body}",
        encoding="utf-8",
    )
    monkeypatch.setattr(catalog_mod, "LEGAL_ROOT", tmp_path)
    catalog_mod.reset_cache()
    with pytest.raises(CatalogError, match="unfilled placeholders"):
        catalog_mod._read_file(sample)
    catalog_mod.reset_cache()


def test_gates_closed_until_approved_and_rkn(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "QA_E2E_DEMO", False)
    assert registration_open() is False
    assert waitlist_open() is False
    assert payment_open() is False
    blocked = join(
        email="a@example.com",
        name=None,
        broker="unset",
        portfolio_range="нет данных",
        consent=True,
        honeypot="",
    )
    assert blocked["status"] == "rejected"
    assert quote(user_id="legal", plan="personal", period="month")["status"] == "off"


def test_demo_opens_registration_keeps_payment_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "QA_E2E_DEMO", True)
    assert registration_open() is True
    assert waitlist_open() is False
    assert payment_open() is False


def test_ui_texts_forbidden_words_only_in_allow_list() -> None:
    texts = load_ui_texts()
    allow = set(texts.get("forbidden_allow_phrases") or [])
    blob_parts = []

    def walk(key: str, value: object) -> None:
        if key in {"forbidden_words", "forbidden_allow_phrases"}:
            return
        if isinstance(value, dict):
            for child, item in value.items():
                walk(str(child), item)
        elif isinstance(value, list):
            for item in value:
                walk(key, item)
        else:
            blob_parts.append(str(value).lower())

    walk("", texts)
    blob = "\n".join(blob_parts)
    for phrase in FORBIDDEN:
        assert phrase not in blob
    footer = texts["maneuver"]["card"]["footer"]
    assert any(item.lower() in footer.lower() for item in allow)


def test_yaml_lite_operator_keys() -> None:
    data = load_yaml((REPO / "legal" / "operator.yaml").read_text(encoding="utf-8"))
    assert data["rkn"]["notice"] == ""
    assert data["operator"]["full_name"] == "{{operator.full_name}}"
    assert data["exchange"] == {}
    assert data["payments"]["receipts_enabled"] is False


def test_payment_stays_closed_without_receipts(monkeypatch: pytest.MonkeyPatch) -> None:
    """D-149-4: even with approved texts + RKN, no cash register → payment closed."""
    from app.services.legal import gates as gates_mod

    monkeypatch.setattr(settings, "QA_E2E_DEMO", False)
    monkeypatch.setattr(gates_mod, "_all_approved", lambda _codes: True)
    monkeypatch.setattr(gates_mod, "receipts_enabled", lambda: False)
    assert payment_open() is False
    monkeypatch.setattr(gates_mod, "receipts_enabled", lambda: True)
    assert payment_open() is True
