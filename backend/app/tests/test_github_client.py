"""Unit tests for GitHub client (mocked HTTP, no real token required)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.services.github.client import GitHubClient, GitHubClientError


def test_github_client_token_from_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test_token")
    client = GitHubClient()
    assert client.token_configured is True


def test_github_client_no_token():
    client = GitHubClient(token="")
    assert client.token_configured is False


def test_rate_limit_success():
    client = GitHubClient(token="test")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"resources": {"core": {"remaining": 4999}}}
    with patch("httpx.Client") as client_cls:
        inst = client_cls.return_value.__enter__.return_value
        inst.request.return_value = mock_resp
        data = client.rate_limit()
    assert "resources" in data


def test_get_repo_not_found():
    client = GitHubClient(token="test")
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.text = "Not Found"
    with patch("httpx.Client") as client_cls:
        inst = client_cls.return_value.__enter__.return_value
        inst.request.return_value = mock_resp
        with pytest.raises(GitHubClientError) as exc:
            client.get_repo("ccxt", "ccxt")
    assert exc.value.status_code == 404


def test_get_repo_unauthorized():
    client = GitHubClient(token="bad")
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = "Bad credentials"
    with patch("httpx.Client") as client_cls:
        inst = client_cls.return_value.__enter__.return_value
        inst.request.return_value = mock_resp
        with pytest.raises(GitHubClientError) as exc:
            client.get_repo("ccxt", "ccxt")
    assert exc.value.status_code == 401
    assert exc.value.retryable is False


def test_repo_health_ok():
    client = GitHubClient(token="test")
    with patch.object(
        client,
        "get_repo",
        return_value={
            "full_name": "ccxt/ccxt",
            "default_branch": "master",
            "stargazers_count": 33000,
            "license": {"spdx_id": "MIT"},
            "archived": False,
            "html_url": "https://github.com/ccxt/ccxt",
        },
    ):
        result = client.repo_health("ccxt", "ccxt")
    assert result["ok"] is True
    assert result["license"] == "MIT"
    assert result["stars"] == 33000


def test_repo_health_error():
    client = GitHubClient(token="test")
    with patch.object(client, "get_repo", side_effect=GitHubClientError("rate limit", status_code=403)):
        result = client.repo_health("ccxt", "ccxt")
    assert result["ok"] is False
    assert result["status_code"] == 403


def test_request_timeout():
    client = GitHubClient(token="test")
    with patch("httpx.Client") as client_cls:
        inst = client_cls.return_value.__enter__.return_value
        inst.request.side_effect = httpx.TimeoutException("timeout")
        with pytest.raises(GitHubClientError) as exc:
            client.rate_limit()
    assert exc.value.retryable is True
