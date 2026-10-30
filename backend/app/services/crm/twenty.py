"""Twenty CRM REST client — automatic application origination sync."""
from __future__ import annotations

import re
from enum import Enum
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.domain.application_flow import ApplicationORM, ApplicationStatus

logger = get_logger(__name__)

DEFAULT_TIMEOUT = 20.0


class CrmSyncStatus(str, Enum):
    PENDING = "pending"
    SYNCED = "synced"
    FAILED = "failed"
    SKIPPED = "skipped"


# Maps application status → Twenty opportunity / person stage label.
STAGE_BY_STATUS: dict[str, str] = {
    ApplicationStatus.PENDING_VERIFICATION.value: "Pending Email Verification",
    ApplicationStatus.PENDING_REVIEW.value: "Email Verified — Pending Review",
    ApplicationStatus.APPROVED.value: "Approved",
    ApplicationStatus.REJECTED.value: "Rejected",
}


class TwentyCrmError(Exception):
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


def _split_name(full_name: str | None) -> tuple[str, str]:
    if not full_name or not full_name.strip():
        return ("Applicant", "")
    parts = full_name.strip().split(None, 1)
    if len(parts) == 1:
        return (parts[0], "")
    return (parts[0], parts[1])


def _company_name(app: ApplicationORM) -> str:
    if app.name and app.name.strip():
        return app.name.strip()
    local = app.email.split("@", 1)[0]
    return f"Apex Applicant ({local})"


def _person_payload(app: ApplicationORM, *, stage: str, company_id: str | None) -> dict[str, Any]:
    first, last = _split_name(app.name)
    payload: dict[str, Any] = {
        "name": {"firstName": first, "lastName": last},
        "emails": {"primaryEmail": app.email, "additionalEmails": []},
        "phones": {"primaryPhoneNumber": app.phone, "primaryPhoneCallingCode": ""},
        "jobTitle": f"Apex Application — {stage}",
    }
    if company_id:
        payload["company"] = {"connect": {"where": {"id": company_id}}}
    return payload


def _company_payload(app: ApplicationORM) -> dict[str, Any]:
    return {
        "name": _company_name(app),
        "domainName": {
            "primaryLinkUrl": "",
            "primaryLinkLabel": app.jurisdiction or "apex-intel",
            "secondaryLinks": [],
        },
    }


def _extract_id(body: Any) -> str | None:
    if not isinstance(body, dict):
        return None
    data = body.get("data")
    if isinstance(data, dict) and data.get("id"):
        return str(data["id"])
    if body.get("id"):
        return str(body["id"])
    record = body.get("record")
    if isinstance(record, dict) and record.get("id"):
        return str(record["id"])
    return None


class TwentyCrmClient:
    """Twenty CRM REST client. Credentials from TWENTY_API_URL + TWENTY_API_KEY env."""

    def __init__(
        self,
        *,
        api_url: str | None = None,
        api_key: str | None = None,
        workspace_id: str | None = None,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self._api_url = (api_url if api_url is not None else settings.TWENTY_API_URL).rstrip("/")
        self._api_key = (api_key if api_key is not None else settings.TWENTY_API_KEY).strip()
        self._workspace_id = (
            workspace_id if workspace_id is not None else settings.TWENTY_WORKSPACE_ID
        ).strip()
        self._timeout = timeout

    @property
    def configured(self) -> bool:
        return bool(self._api_url and self._api_key)

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "User-Agent": "apex-intel-crm-sync",
        }
        if self._workspace_id:
            headers["X-Workspace-Id"] = self._workspace_id
        return headers

    def _rest_url(self, path: str) -> str:
        clean = path.lstrip("/")
        if clean.startswith("rest/"):
            return f"{self._api_url}/{clean}"
        return f"{self._api_url}/rest/{clean}"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict[str, Any] | None = None,
    ) -> Any:
        if not self.configured:
            raise TwentyCrmError("Twenty CRM not configured", retryable=False)

        url = self._rest_url(path)
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                resp = await client.request(method, url, headers=self._headers(), json=json)
        except httpx.TimeoutException as exc:
            raise TwentyCrmError("Twenty CRM request timed out", retryable=True) from exc
        except httpx.RequestError as exc:
            raise TwentyCrmError(f"Twenty CRM network error: {exc}", retryable=True) from exc

        if resp.status_code in (401, 403):
            raise TwentyCrmError(
                "Twenty CRM authentication failed",
                status_code=resp.status_code,
                retryable=False,
            )
        if resp.status_code == 429:
            raise TwentyCrmError(
                "Twenty CRM rate limited",
                status_code=429,
                retryable=True,
            )
        if resp.status_code >= 500:
            raise TwentyCrmError(
                f"Twenty CRM server error ({resp.status_code})",
                status_code=resp.status_code,
                retryable=True,
            )
        if resp.status_code >= 400:
            detail = resp.text[:500]
            raise TwentyCrmError(
                f"Twenty CRM client error ({resp.status_code}): {detail}",
                status_code=resp.status_code,
                retryable=False,
            )

        if not resp.content:
            return {}
        try:
            return resp.json()
        except Exception:  # noqa: BLE001
            return {"raw": resp.text[:2000]}

    async def health_check(self) -> dict[str, Any]:
        """Probe Twenty CRM connectivity (list people with limit=1)."""
        if not self.configured:
            return {
                "ok": False,
                "configured": False,
                "detail": "TWENTY_API_URL or TWENTY_API_KEY not set",
            }
        try:
            body = await self._request("GET", "people?limit=1")
            return {
                "ok": True,
                "configured": True,
                "api_url": self._api_url,
                "workspace_id_set": bool(self._workspace_id),
                "probe": "rest/people?limit=1",
                "sample_keys": list(body.keys())[:6] if isinstance(body, dict) else [],
            }
        except TwentyCrmError as exc:
            return {
                "ok": False,
                "configured": True,
                "api_url": self._api_url,
                "error": str(exc),
                "status_code": exc.status_code,
                "retryable": exc.retryable,
            }

    async def create_company(self, app: ApplicationORM) -> str:
        body = await self._request("POST", "companies", json=_company_payload(app))
        company_id = _extract_id(body)
        if not company_id:
            raise TwentyCrmError("Twenty CRM company create returned no id", retryable=False)
        return company_id

    async def create_person(self, app: ApplicationORM, *, company_id: str, stage: str) -> str:
        payload = _person_payload(app, stage=stage, company_id=company_id)
        body = await self._request("POST", "people", json=payload)
        person_id = _extract_id(body)
        if not person_id:
            raise TwentyCrmError("Twenty CRM person create returned no id", retryable=False)
        return person_id

    async def update_person_stage(
        self,
        person_id: str,
        app: ApplicationORM,
        *,
        stage: str,
        company_id: str | None = None,
    ) -> None:
        payload = _person_payload(app, stage=stage, company_id=company_id)
        # PATCH partial — drop company connect if unchanged
        if not company_id:
            payload.pop("company", None)
        await self._request("PATCH", f"people/{person_id}", json=payload)

    async def add_note(self, person_id: str, *, title: str, body: str) -> None:
        note_payload = {
            "title": title[:200],
            "bodyV2": {"markdown": body[:4000]},
            "person": {"connect": {"where": {"id": person_id}}},
        }
        try:
            await self._request("POST", "notes", json=note_payload)
        except TwentyCrmError as exc:
            # Notes are best-effort; person stage update is the source of truth.
            logger.warning("Twenty CRM note create failed", person_id=person_id, error=str(exc))

    def _note_body(self, app: ApplicationORM, event: str) -> str:
        lines = [
            f"**Event:** {event}",
            f"**Application ID:** `{app.id}`",
            f"**Status:** {app.status}",
            f"**Email:** {app.email}",
            f"**Phone:** {app.phone}",
        ]
        if app.jurisdiction:
            lines.append(f"**Jurisdiction:** {app.jurisdiction}")
        if app.capital_range:
            lines.append(f"**Capital range:** {app.capital_range}")
        if app.experience:
            lines.append(f"**Experience:** {app.experience}")
        if app.strategy_interest:
            lines.append(f"**Strategy:** {app.strategy_interest}")
        if app.duplicate_flag:
            lines.append(f"**Duplicate flag:** {app.duplicate_reason or 'yes'}")
        if app.comments:
            safe = re.sub(r"[\r\n]+", " ", app.comments)[:500]
            lines.append(f"**Comments:** {safe}")
        return "\n".join(lines)

    async def sync_application(self, app: ApplicationORM, *, event: str) -> dict[str, str]:
        """
        Idempotent sync: create person+company on first call, PATCH stage on updates.
        Returns {person_id, company_id} for persistence on ApplicationORM.
        """
        if not self.configured:
            return {"skipped": "not_configured"}

        stage = STAGE_BY_STATUS.get(app.status, app.status)
        person_id = app.twenty_crm_id
        company_id = app.twenty_company_id

        if person_id:
            await self.update_person_stage(
                person_id, app, stage=stage, company_id=company_id
            )
        else:
            if not company_id:
                company_id = await self.create_company(app)
            person_id = await self.create_person(app, company_id=company_id, stage=stage)

        await self.add_note(
            person_id,
            title=f"Apex — {event}",
            body=self._note_body(app, event),
        )

        return {"person_id": person_id, "company_id": company_id or ""}


twenty_crm_client = TwentyCrmClient()
