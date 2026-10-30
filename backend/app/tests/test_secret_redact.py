"""Tests for secret redaction in provider errors."""
from app.utils.secret_redact import redact_secrets


def test_redact_apikey_in_url():
    raw = (
        "Client error '403 Forbidden' for url "
        "'https://financialmodelingprep.com/api/v3/economic_calendar?apikey=SECRETKEY123&from=2026-08-07'"
    )
    out = redact_secrets(raw)
    assert "SECRETKEY123" not in out
    assert "apikey=" in out


def test_redact_polygon_apiKey_camelcase():
    raw = "Client error for url 'https://api.polygon.io/v2/last/trade/AAPL?apiKey=POLY_SECRET_XYZ'"
    out = redact_secrets(raw)
    assert "POLY_SECRET_XYZ" not in out
    assert "apiKey=" in out or "apikey=" in out.lower()


def test_redact_finnhub_token_query():
    raw = "https://finnhub.io/api/v1/company-news?symbol=AAPL&token=fh_secret_abc&from=2026-01-01"
    out = redact_secrets(raw)
    assert "fh_secret_abc" not in out


def test_redact_bearer_token():
    out = redact_secrets("Authorization failed Bearer abcdefghijklmnop")
    assert "abcdefghijklmnop" not in out
    assert "Bearer ***" in out


def test_redact_tiingo_token_scheme():
    out = redact_secrets("Unauthorized Token tiingo_secret_value_99")
    assert "tiingo_secret_value_99" not in out
    assert "Token ***" in out
