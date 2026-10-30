"""GA16-271: the night path must not invent capital 0 or a 250 limit."""
from __future__ import annotations

from app.tasks.execution import nightly_ops_dr_task


def test_missing_portfolio_size_does_not_seal_250(monkeypatch) -> None:
    called: list[object] = []

    class Settings:
        DEFAULT_PORTFOLIO_SIZE = 0

    def refuse(**kwargs: object) -> dict:
        called.append(kwargs)
        return {"seal": {"deploy_cap": 250.0}}

    monkeypatch.setattr("app.core.config.settings", Settings())
    monkeypatch.setattr("app.services.ops_desk.live_hooks.run_nightly_dr", refuse)
    result = nightly_ops_dr_task()
    assert called == []
    assert result["ok"] is False
    assert result["reason"] == "нет данных"
