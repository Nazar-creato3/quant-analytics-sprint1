"""User-supplied exchange base_url cannot point at internal services (SSRF)."""
import pytest

from app.services.trading_keys.base_url_policy import BaseUrlRejected, checked_base_url


@pytest.mark.parametrize(
    "url",
    [
        "http://vault:8200",
        "https://169.254.169.254/latest",
        "http://api.bybit.com",
        "https://api.bybit.com.evil.example",
        "https://user:pw@api.bybit.com",
        "https://api.bybit.com:8443",
        "file:///etc/passwd",
    ],
)
def test_rejects(url):
    with pytest.raises(BaseUrlRejected):
        checked_base_url(url)


def test_accepts_exchange_hosts():
    assert checked_base_url("https://api-testnet.bybit.com/") == "https://api-testnet.bybit.com"
    assert checked_base_url(None) is None
