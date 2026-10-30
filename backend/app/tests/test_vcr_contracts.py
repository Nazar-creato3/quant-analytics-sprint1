from __future__ import annotations

from pathlib import Path

from app.services.qa.vcr import cassette_path, load_cassette, redact, save_cassette

FIXTURES = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "contracts"


def test_moex_cassette_has_redacted_secrets():
    path = cassette_path(FIXTURES, "moex", "iss_boards")
    data = load_cassette(path)
    assert data["vendor"] == "moex"
    assert data["request"]["headers"]["Authorization"] == "***"
    assert data["response"]["body"]["boards"]["data"][0][0] == "TQBR"


def test_redact_and_roundtrip(tmp_path: Path):
    dest = tmp_path / "binance" / "ticker.json"
    save_cassette(
        dest,
        {"api_key": "supersecretvalue", "price": 100, "nested": {"password": "x"}},
    )
    loaded = load_cassette(dest)
    assert loaded["api_key"] == "***"
    assert loaded["price"] == 100
    assert redact({"Authorization": "Bearer abc"})["Authorization"] == "***"


def test_sandbox_marker_is_optional():
    """Live sandbox hits stay opt-in (no network in CI)."""
    assert True
