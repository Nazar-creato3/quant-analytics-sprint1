"""Lightweight GitHub REST client for repo health / metadata probes."""
from __future__ import annotations

import os
from typing import Any

import httpx

DEFAULT_API = "https://api.github.com"
DEFAULT_TIMEOUT = 15.0


class GitHubClientError(Exception):
    """Raised when GitHub API returns an error or the client is misconfigured."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


class GitHubClient:
    """GitHub REST v3 client. Token read from GITHUB_TOKEN env — never hardcoded."""

    def __init__(
        self,
        *,
        token: str | None = None,
        base_url: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._token = (token if token is not None else os.getenv("GITHUB_TOKEN", "")).strip()
        self._base_url = (base_url or os.getenv("GITHUB_API_URL") or DEFAULT_API).rstrip("/")
        self._timeout = timeout

    @property
    def token_configured(self) -> bool:
        return bool(self._token)

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "apex-intel-trading-engines",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = path if path.startswith("http") else f"{self._base_url}/{path.lstrip('/')}"
        try:
            with httpx.Client(timeout=self._timeout) as client:
                resp = client.request(method, url, headers=self._headers(), **kwargs)
        except httpx.TimeoutException as exc:
            raise GitHubClientError("GitHub request timed out", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise GitHubClientError(f"GitHub HTTP error: {exc}", retryable=True) from exc

        if resp.status_code == 401:
            raise GitHubClientError(
                "GitHub unauthorized — check GITHUB_TOKEN",
                status_code=401,
                retryable=False,
            )
        if resp.status_code == 403:
            detail = resp.text[:200]
            retryable = "rate limit" in detail.lower()
            raise GitHubClientError(
                f"GitHub forbidden: {detail}",
                status_code=403,
                retryable=retryable,
            )
        if resp.status_code == 404:
            raise GitHubClientError(
                "GitHub resource not found",
                status_code=404,
                retryable=False,
            )
        if resp.status_code >= 400:
            raise GitHubClientError(
                f"GitHub error {resp.status_code}: {resp.text[:200]}",
                status_code=resp.status_code,
                retryable=resp.status_code >= 500,
            )
        if resp.status_code == 204:
            return None
        return resp.json()

    def rate_limit(self) -> dict[str, Any]:
        """GET /rate_limit — works without token (lower limits)."""
        return self._request("GET", "/rate_limit")

    def get_repo(self, owner: str, repo: str) -> dict[str, Any]:
        """GET /repos/{owner}/{repo}."""
        return self._request("GET", f"/repos/{owner}/{repo}")

    def repo_health(self, owner: str, repo: str) -> dict[str, Any]:
        """Structured repo probe for trading-engine registry."""
        try:
            data = self.get_repo(owner, repo)
            return {
                "ok": True,
                "owner": owner,
                "repo": repo,
                "full_name": data.get("full_name"),
                "default_branch": data.get("default_branch"),
                "stars": data.get("stargazers_count"),
                "license": (data.get("license") or {}).get("spdx_id"),
                "archived": data.get("archived", False),
                "html_url": data.get("html_url"),
                "token_used": self.token_configured,
            }
        except GitHubClientError as exc:
            return {
                "ok": False,
                "owner": owner,
                "repo": repo,
                "error": str(exc),
                "status_code": exc.status_code,
                "token_used": self.token_configured,
            }
