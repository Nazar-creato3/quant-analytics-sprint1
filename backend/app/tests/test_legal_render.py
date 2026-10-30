"""Public legal texts: operator details filled, chosen variants only, no drafting notes."""
from app.services.legal import catalog
from app.services.legal.catalog import INTERNAL_CODES, render_body, select_variants


def test_select_variants_line_inline_and_heading():
    body = "\n".join(
        [
            "## 3. Раздел [L-08:А]",
            "[L-04:Б] Не передаётся.",
            "[L-04:А] Передаётся бирже.",
            "| x | [L-06:А] договор и согласие / [L-06:Б] согласие | y |",
        ]
    )
    out = select_variants(body, {"L-04": "B", "L-06": "A", "L-08": "A"})
    assert "## 3. Раздел" in out and "[L-" not in out
    assert "Не передаётся." in out and "Передаётся бирже" not in out
    assert "договор и согласие" in out and "/ согласие" not in out


def test_render_hides_braces_and_notes():
    out = render_body("## consent_pd — Согласие\n\nПодпись у отметки: x\n\nОператор {{operator.nope}}.\n<!-- юристу -->\n", {"version": "0.1.0"})
    assert out.startswith("# Согласие")
    assert "{{" not in out and "Подпись у отметки" not in out and "юристу" not in out


def test_catalog_valid_and_new_documents_present():
    assert catalog.validate_catalog() == []
    for code in ("recommendations", "cookies", "consent_broker", "disclaimer"):
        doc = catalog.get_document(code)
        assert doc is not None and "{{" not in doc["rendered"]
    rec = catalog.get_document("recommendations")["rendered"]
    assert "10.2-2" in rec and "@" in rec  # owner's address for legal notices


def test_policy_says_no_cross_border_and_lists_sms():
    text = catalog.get_document("privacy")["rendered"]
    assert "Трансграничная передача персональных данных не осуществляется" in text
    assert "SMS" in text
    assert "rkn_notice" in INTERNAL_CODES
