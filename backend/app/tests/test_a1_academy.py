"""Academy A1: provider switch, outbound redaction, on-prem compose, token owner."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.core.config import Settings, settings
from app.services.explanations.service import FORBIDDEN, filter_wording
from app.services.llm.destination import host_is_non_public
from app.services.llm.errors import AITunnelUnavailableError
from app.services.llm.llm_service import LLMService, _post_completion
from app.services.market_data.license import (
    ISS_DELAY_LABEL,
    quote_envelope,
    stamp_quote,
)
from app.services.privacy.service import OUTBOUND_FIELD_TABLE, prepare_llm_outbound
from app.services.qa.feature_flags import is_enabled, reset_for_tests

REPO = Path(__file__).resolve().parents[3]
_ACCOUNT = "ACC-998877"
_NAME = "Nina Volkova"
_NAME_RU = "Иван Петров"
_TOKEN = "t.BrokerSecretToken99"


def test_outbound_payload_has_no_raw_account_name_or_token() -> None:
    payload = {
        "model": "kimi-k3",
        "messages": [
            {
                "role": "user",
                "content": (
                    f"account_id={_ACCOUNT} name: {_NAME} token={_TOKEN} "
                    f"client_name: {_NAME_RU}"
                ),
            }
        ],
        "user": {
            "account_id": _ACCOUNT,
            "name": _NAME,
            "client_name": _NAME_RU,
            "broker_token": _TOKEN,
        },
        "tools": [{"type": "function", "function": {"name": "get_market_regime"}}],
        "ticker": "SBER",
        "price": "250.5",
    }
    outbound = prepare_llm_outbound(payload)
    blob = json.dumps(outbound, ensure_ascii=False)
    assert _ACCOUNT not in blob
    assert _NAME not in blob
    assert _NAME_RU not in blob
    assert _TOKEN not in blob
    assert outbound["user"]["account_id"].startswith("sha256:")
    assert outbound["user"]["name"] == "[redacted]"
    assert outbound["user"]["broker_token"] == "[redacted]"
    assert outbound["tools"][0]["function"]["name"] == "get_market_regime"
    assert outbound["ticker"] == "SBER"
    assert outbound["price"] == "250.5"
    joined = " ".join(row["field"] + row["treatment"] + row["may_send"] for row in OUTBOUND_FIELD_TABLE)
    assert "account_id" in joined
    assert "sha256" in joined
    assert "broker_token" in joined
    assert "no" in joined


@pytest.mark.asyncio
async def test_onprem_does_not_call_a_public_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "LLM_ONPREM", True)
    monkeypatch.setattr(settings, "LLM_PROVIDER", "onprem")
    monkeypatch.setattr(settings, "LLM_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_ONPREM_BASE_URL", "https://api.aitunnel.ru/v1")
    monkeypatch.setattr(settings, "AITUNNEL_API_KEY", "sk-should-not-leave")
    assert host_is_non_public("https://api.aitunnel.ru/v1") is False

    def boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("public model host was contacted")

    monkeypatch.setattr("app.services.llm.llm_service.httpx.AsyncClient", boom)
    with pytest.raises(AITunnelUnavailableError):
        await _post_completion(
            {
                "model": "local",
                "messages": [{"role": "user", "content": f"token={_TOKEN}"}],
            }
        )


@pytest.mark.asyncio
async def test_onprem_local_payload_is_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "LLM_ONPREM", True)
    monkeypatch.setattr(settings, "LLM_PROVIDER", "onprem")
    monkeypatch.setattr(settings, "LLM_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_ONPREM_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setattr(settings, "LLM_ONPREM_API_KEY", "")
    monkeypatch.setattr(settings, "AITUNNEL_API_KEY", "sk-cloud-must-stay")

    mock_resp = AsyncMock()
    mock_resp.raise_for_status = lambda: None
    mock_resp.status_code = 200
    mock_resp.json = lambda: {"choices": [{"message": {"content": "ok"}}], "usage": {}}
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_resp)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with patch("app.services.llm.llm_service.httpx.AsyncClient", return_value=mock_client):
        out = await LLMService.complete(
            "forecast_narrative",
            f"account_id={_ACCOUNT} name: {_NAME} token={_TOKEN}",
        )
    assert out == "ok"
    url = mock_client.post.call_args[0][0]
    assert url.startswith("http://127.0.0.1:11434/")
    body = json.dumps(mock_client.post.call_args[1]["json"], ensure_ascii=False)
    assert _ACCOUNT not in body
    assert _NAME not in body
    assert _TOKEN not in body
    headers = mock_client.post.call_args[1]["headers"]
    assert "sk-cloud-must-stay" not in json.dumps(headers)


def test_provider_default_is_the_configured_gateway() -> None:
    assert Settings.model_fields["LLM_PROVIDER"].default == "aitunnel"
    assert Settings.model_fields["LLM_ONPREM"].default is False


def test_token_data_license_tag_is_owner_only() -> None:
    own = quote_envelope(
        symbol="SBER",
        price="10",
        source="tinvest_user",
        as_of="2026-10-06",
        delayed=False,
        audience="owner",
        viewer_user_id="user-a",
        token_owner_id="user-a",
    )
    assert own["license_tag"] == "owner_only"
    assert own["display_allowed"] is True
    assert own["price"] == "10"

    other = quote_envelope(
        symbol="SBER",
        price="10",
        source="tinvest_user",
        as_of="2026-10-06",
        delayed=False,
        audience="owner",
        viewer_user_id="user-b",
        token_owner_id="user-a",
    )
    assert other["license_tag"] == "owner_only"
    assert other["display_allowed"] is False
    assert other["price"] is None

    public = quote_envelope(
        symbol="SBER",
        price="10",
        source="tinvest_user",
        as_of="2026-10-06",
        delayed=False,
        audience="public",
        viewer_user_id="user-a",
        token_owner_id="user-a",
    )
    assert public["price"] is None

    spoofed = stamp_quote(
        {
            "symbol": "SBER",
            "price": "10",
            "source": "tinvest_user",
            "delayed": False,
            "token_owner_id": "user-a",
            "viewer_user_id": "user-a",
        },
        viewer_user_id="user-b",
    )
    assert spoofed["price"] is None
    assert spoofed["license_tag"] == "owner_only"

    matched = stamp_quote(
        {
            "symbol": "SBER",
            "price": "10",
            "source": "tinvest_user",
            "delayed": False,
            "token_owner_id": "user-a",
        },
        viewer_user_id="user-a",
    )
    assert matched["price"] == "10"


def test_moex_delay_label_unchanged() -> None:
    env = quote_envelope(
        symbol="SBER",
        price="100",
        source="iss_moex",
        as_of="2024-01-31",
        delayed=True,
        audience="public",
    )
    assert env["license_tag"] == "display_allowed"
    assert env["freshness_label"] == ISS_DELAY_LABEL
    assert env["price"] == "100"
    platform = quote_envelope(
        symbol="SBER",
        price="10",
        source="tinvest_platform",
        as_of="2026-10-06",
        delayed=False,
        audience="owner",
        viewer_user_id="user-a",
        token_owner_id="user-a",
    )
    assert platform["license_tag"] == "forbidden"
    assert platform["price"] is None


def test_founder_flags_and_forbidden_wording_stay() -> None:
    reset_for_tests()
    assert is_enabled("qa_act_live") is False
    assert is_enabled("qa_maneuvers_user_rules") is False
    assert is_enabled("qa_act_model_profile") is False
    assert is_enabled("qa_target_portfolio") is True
    assert is_enabled("qa_maneuver_generator") is True
    for phrase in ("рекомендуем", "советуем", "подходит вам", "соответствует вашему профилю"):
        assert phrase in FORBIDDEN
        assert filter_wording(f"Текст: {phrase}")


def _service_blocks(text: str) -> dict[str, str]:
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith("services:"))
    blocks: dict[str, str] = {}
    current: str | None = None
    buf: list[str] = []
    for line in lines[start + 1 :]:
        if line and not line.startswith(" ") and not line.startswith("#"):
            break
        if line.startswith("  ") and not line.startswith("   ") and line.rstrip().endswith(":"):
            if current is not None:
                blocks[current] = "\n".join(buf)
            current = line.strip()[:-1]
            buf = [line]
        elif current is not None:
            buf.append(line)
    if current is not None:
        blocks[current] = "\n".join(buf)
    return blocks


def test_onprem_compose_profile_has_no_public_route() -> None:
    text = (REPO / "docker-compose.yml").read_text(encoding="utf-8")
    assert "8.8.8.8" not in text
    assert "1.1.1.1" not in text
    assert not any(line.strip().startswith("dns:") for line in text.splitlines())
    blocks = _service_blocks(text)
    postgres = blocks["postgres"]
    assert "profiles:" not in postgres
    assert "apex-net" in postgres
    assert "pull_policy" not in postgres
    for name in ("postgres-onprem", "redis-onprem", "backend-onprem"):
        block = blocks[name]
        assert 'profiles: ["onprem"]' in block
        assert "pull_policy: never" in block
        assert "- onprem" in block
        assert "apex-net" not in block
        assert "build:" not in block
    assert "internal: true" in text
    assert 'com.docker.network.bridge.enable_ip_masquerade: "false"' in text
    assert "image: apex-onprem-backend:local" in blocks["backend-onprem"]
