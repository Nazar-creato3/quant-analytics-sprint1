"""Russian mobile confirmation: normalisation, codes, limits, sms.ru, token gate."""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from app.services.auth import phone as ph


def test_normalize_russian_mobile_only():
    assert ph.normalize("+7 (912) 345-67-89").digits == "79123456789"
    assert ph.normalize("89123456789").digits == "79123456789"
    assert ph.normalize("9123456789").digits == "79123456789"
    for bad in ("+7 495 123-45-67", "+380 50 123 4567", "77012345678", "123"):
        with pytest.raises(ph.PhoneError):
            ph.normalize(bad)


def test_hash_is_keyed_and_stable():
    a = ph.normalize("+79123456789")
    assert a.hash == ph.normalize("89123456789").hash
    assert "9123456789" not in a.hash and len(a.hash) == 64
    assert a.last4 == "6789" and a.masked.endswith("67-89")


@pytest.fixture
def fake_cache(monkeypatch):
    store: dict = {}
    counters: dict = {}

    async def cset(k, v, ttl=None):
        store[k] = v

    async def cget(k):
        return store.get(k)

    async def cdel(k):
        store.pop(k, None)

    async def rl(key, n, window, fail_closed=True):
        counters[key] = counters.get(key, 0) + 1
        return counters[key] <= n, n - counters[key]

    monkeypatch.setattr(ph, "cache_set", cset)
    monkeypatch.setattr(ph, "cache_get", cget)
    monkeypatch.setattr(ph, "cache_delete", cdel)
    monkeypatch.setattr(ph, "rate_limit_check", rl)
    return store


@pytest.mark.asyncio
async def test_code_roundtrip_and_attempt_limit(monkeypatch, fake_cache):
    sent: list = []

    async def dispatch(phone, text):
        sent.append(text)

    monkeypatch.setattr(ph, "_dispatch", dispatch)
    monkeypatch.setattr(ph.secrets, "randbelow", lambda n: 23456)  # → 123456
    await ph.send_code("+79123456789", ip="1.2.3.4")
    assert "123456" in sent[0]
    with pytest.raises(ph.PhoneError):
        await ph.check_code("+79123456789", "000000")
    assert (await ph.check_code("+79123456789", "123456")).digits == "79123456789"
    with pytest.raises(ph.PhoneError):  # consumed
        await ph.check_code("+79123456789", "123456")

    await ph.send_code("+79123456789", ip="1.2.3.4")
    for _ in range(ph.MAX_ATTEMPTS):
        with pytest.raises(ph.PhoneError):
            await ph.check_code("+79123456789", "999999")
    with pytest.raises(ph.PhoneError):  # burned after too many attempts
        await ph.check_code("+79123456789", "123456")


@pytest.mark.asyncio
async def test_send_limits_per_number(monkeypatch, fake_cache):
    async def dispatch(phone, text):
        return None

    monkeypatch.setattr(ph, "_dispatch", dispatch)
    for _ in range(3):
        await ph.send_code("+79123456789", ip="1.2.3.4")
    with pytest.raises(ph.PhoneError) as err:
        await ph.send_code("+79123456789", ip="1.2.3.4")
    assert err.value.status == 429


@pytest.mark.asyncio
async def test_smsru_rejection_is_reported(monkeypatch):
    import httpx

    monkeypatch.setattr(ph.settings, "SMSRU_API_KEY", "key")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "sms.ru"
        return httpx.Response(200, json={"status": "OK", "sms": {"79123456789": {"status": "ERROR", "status_code": 207}}})

    real = httpx.AsyncClient

    monkeypatch.setattr(ph.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler)))
    with pytest.raises(ph.PhoneError):
        await ph._send_smsru(ph.normalize("+79123456789"), "x")


def test_token_gate(monkeypatch):
    from app.core import deps

    monkeypatch.setattr(deps.settings, "PHONE_SIGNIN_REQUIRED", True)
    monkeypatch.setattr(deps.settings, "QA_E2E_DEMO", False)
    with pytest.raises(HTTPException) as err:
        deps.phone_gate({"sub": "a@b.c"}, "/api/v1/portfolio/metrics")
    assert err.value.status_code == 403 and err.value.detail == "phone_confirmation_required"
    deps.phone_gate({"sub": "a@b.c"}, "/api/v1/auth/phone/confirm")  # exempt
    deps.phone_gate({"sub": "a@b.c"}, "/api/v1/legal/privacy")  # exempt
    deps.phone_gate({"sub": "a@b.c", "pv": True}, "/api/v1/portfolio/metrics")
    monkeypatch.setattr(deps.settings, "PHONE_SIGNIN_REQUIRED", False)
    deps.phone_gate({"sub": "a@b.c"}, "/api/v1/portfolio/metrics")
