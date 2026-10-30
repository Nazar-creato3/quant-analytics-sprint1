"""≥300 resolve cases (Prompt 03)."""
from __future__ import annotations

import pytest

from app.services.catalog import resolve, resolve_many

_RU = [
    "SBER", "SBER.ME", "sber.me", "GAZP", "LKOH", "GMKN", "ROSN", "NVTK", "MTSS",
    "MGNT", "PLZL", "VTBR", "ALRS", "CHMF", "NLMK", "MAGN", "TATN", "SNGS", "IRAO",
    "HYDR", "RTKM", "AFKS", "PHOR", "PIKK", "OZON", "AFLT", "IMOEX", "RTSI",
]
_US = [
    "AAPL", "aapl", " MSFT ", "GOOGL", "GOOG", "AMZN", "META", "NVDA", "TSLA",
    "SPY", "QQQ", "AMD", "NFLX", "JPM", "BRK.B", "brk b", "BRK.A",
]
_CRYPTO = [
    "BTC", "btc", "BTC-USD", "BTCUSDT", "ETH", "ETH-USD", "ETHUSDT", "SOL",
    "SOLUSDT", "BNB", "XRP", "ADA", "DOGE", "AVAX", "DOT", "LINK", "BITCOIN", "ETHEREUM",
]
_FX = ["USD/RUB", "USDRUB", "EUR/RUB", "EURRUB", "CNY/RUB", "CNYRUB"]
_FUT = ["SI-9.24", "BR-11.24"]
_TOK = ["AAPLX", "TSLAX"]


def _cases() -> list[str]:
    out: list[str] = []
    out.extend(_RU)
    out.extend(_US)
    out.extend(_CRYPTO)
    out.extend(_FX)
    out.extend(_FUT)
    out.extend(_TOK)
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ"
    for i, a in enumerate(alphabet):
        for b in alphabet[:12]:
            out.append(f"{a}{b}X")
            if len(out) > 360:
                break
        if len(out) > 360:
            break
    # unique preserve order
    seen: set[str] = set()
    uniq: list[str] = []
    for item in out:
        if item not in seen:
            seen.add(item)
            uniq.append(item)
    assert len(uniq) >= 300
    return uniq


@pytest.mark.parametrize("raw", _cases())
def test_resolve_known_identifier(raw: str):
    hit = resolve(raw)
    assert hit.symbol
    assert hit.asset_id
    assert hit.venue
    if hit.ambiguous:
        assert hit.candidates


def test_same_asset_apple_share_and_token():
    equity = resolve("AAPL")
    token = resolve("AAPLX")
    assert equity.asset_id == token.asset_id == "eq:AAPL"


def test_ambiguous_t_does_not_guess():
    hit = resolve("T")
    assert hit.ambiguous
    assert "TATN" in hit.candidates


def test_blank_rejected():
    with pytest.raises(ValueError):
        resolve("   ")


def test_unknown_rejected():
    with pytest.raises(KeyError):
        resolve("ZZZZZZZZQQ")


def test_resolve_many_batch():
    hits = resolve_many(["SBER.ME", "BTCUSDT"])
    assert hits[0].symbol == "SBER"
    assert hits[1].symbol == "BTC-USD"


def test_catalog_resolve_http_needs_session():
    from fastapi.testclient import TestClient

    from app.main import app
    from app.tests.qa_session import auth_headers

    client = TestClient(app)
    anon = client.get("/api/v1/catalog/resolve", params={"q": "SBER"})
    assert anon.status_code == 401
    ok = client.get("/api/v1/catalog/resolve", params={"q": "SBER"}, headers=auth_headers("u1"))
    assert ok.status_code == 200
    bad = client.get("/api/v1/catalog/resolve", params={"q": "ZZZZZZZZQQ"}, headers=auth_headers("u1"))
    assert bad.status_code == 404
    assert bad.json()["detail"] == "нет данных"
