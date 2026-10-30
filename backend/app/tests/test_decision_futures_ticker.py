"""GA16-283: futures market summary must use the user ticker, not MIX."""
from __future__ import annotations

from app.services.decision_core.sources import _d58b


def test_missing_ticker_is_no_data() -> None:
    out = _d58b("u1", "paper", "p1", {})
    assert out["data_status"] == "нет данных"
    assert out["reason"] == "нет данных"


def test_user_ticker_is_passed(monkeypatch) -> None:
    seen: list[str] = []

    def capture(ticker: str, **_kwargs: object) -> dict:
        seen.append(ticker)
        return {"data_status": "ok", "ticker": ticker}

    monkeypatch.setattr("app.services.futures_market.service.explain_market", capture)
    out = _d58b("u1", "paper", "p1", {"futures": [{"ticker": "SiH6"}]})
    assert seen == ["SiH6"]
    assert out["ticker"] == "SiH6"
