"""GigaChat (Sber) as a model provider: ``LLM_PROVIDER=gigachat``.

GigaChat speaks almost the OpenAI chat format, with three differences we bridge
here so the rest of the code keeps one shape:

* auth: a long-lived authorization key is exchanged for a 30-minute access token
  (``POST /api/v2/oauth``, Basic auth, a fresh ``RqUID`` per request);
* tools: GigaChat takes ``functions`` + ``function_call`` and answers with one
  ``function_call`` (arguments as an object), not ``tool_calls`` (arguments as text);
  the function result goes back as a ``function`` message;
* TLS: Sber's endpoints are signed by the Russian Trusted Root CA. Put that
  certificate on the server and point ``GIGACHAT_CA_BUNDLE`` at it.

Docs: https://developers.sber.ru/docs/ru/gigachat/api/overview
"""
from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_token: dict[str, Any] = {"value": "", "expires": 0.0}
_lock = asyncio.Lock()


class GigaChatError(RuntimeError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def gigachat_active() -> bool:
    return str(getattr(settings, "LLM_PROVIDER", "") or "").strip().lower() == "gigachat"


def gigachat_configured() -> bool:
    return bool((settings.GIGACHAT_AUTH_KEY or "").strip())


def _verify() -> str | bool:
    bundle = (settings.GIGACHAT_CA_BUNDLE or "").strip()
    return bundle or True


async def _access_token(client: httpx.AsyncClient, *, force: bool = False) -> str:
    async with _lock:
        if not force and _token["value"] and _token["expires"] - 60 > time.time():
            return str(_token["value"])
        resp = await client.post(
            settings.GIGACHAT_AUTH_URL,
            headers={
                "Authorization": f"Basic {(settings.GIGACHAT_AUTH_KEY or '').strip()}",
                "RqUID": str(uuid.uuid4()),
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
            data={"scope": settings.GIGACHAT_SCOPE},
        )
        if resp.status_code != 200:
            raise GigaChatError(f"авторизация GigaChat: HTTP {resp.status_code}")
        body = resp.json()
        value = str(body.get("access_token") or "")
        if not value:
            raise GigaChatError("авторизация GigaChat: пустой токен")
        expires_ms = body.get("expires_at")
        _token["value"] = value
        _token["expires"] = float(expires_ms) / 1000 if expires_ms else time.time() + 25 * 60
        return value


# ---- format bridge -----------------------------------------------------------


def _functions(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for t in tools or []:
        fn = t.get("function") if isinstance(t, dict) else None
        if not isinstance(fn, dict) or not fn.get("name"):
            continue
        item = {"name": fn["name"], "description": fn.get("description") or "", "parameters": fn.get("parameters") or {"type": "object", "properties": {}}}
        out.append(item)
    return out


def _args_obj(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        val = json.loads(raw or "{}")
    except (TypeError, ValueError):
        return {}
    return val if isinstance(val, dict) else {}


def to_gigachat_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """OpenAI-shaped history → GigaChat history."""
    names: dict[str, str] = {}
    out: list[dict[str, Any]] = []
    for m in messages:
        role = m.get("role")
        if role == "assistant" and m.get("tool_calls"):
            tc = m["tool_calls"][0]
            fn = tc.get("function") or {}
            names[str(tc.get("id") or fn.get("name"))] = str(fn.get("name") or "")
            msg: dict[str, Any] = {"role": "assistant", "content": m.get("content") or "", "function_call": {"name": fn.get("name"), "arguments": _args_obj(fn.get("arguments"))}}
            if m.get("functions_state_id"):
                msg["functions_state_id"] = m["functions_state_id"]
            out.append(msg)
        elif role == "tool":
            name = m.get("name") or names.get(str(m.get("tool_call_id")), "")
            content = m.get("content")
            text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
            try:  # GigaChat wants the result as a JSON object
                json.loads(text)
            except (TypeError, ValueError):
                text = json.dumps({"result": text}, ensure_ascii=False)
            out.append({"role": "function", "name": name, "content": text})
        else:
            out.append({"role": role, "content": m.get("content") or ""})
    return out


def to_openai_response(data: dict[str, Any]) -> dict[str, Any]:
    """GigaChat reply → the OpenAI shape the callers parse."""
    choices = []
    for ch in data.get("choices") or []:
        msg = dict(ch.get("message") or {})
        call = msg.pop("function_call", None)
        if call:
            msg["tool_calls"] = [
                {
                    "id": f"call_{uuid.uuid4().hex[:12]}",
                    "type": "function",
                    "function": {"name": call.get("name"), "arguments": json.dumps(call.get("arguments") or {}, ensure_ascii=False)},
                }
            ]
        choices.append({**ch, "message": msg})
    return {**data, "choices": choices}


def to_gigachat_payload(payload: dict[str, Any]) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": settings.GIGACHAT_MODEL,
        "messages": to_gigachat_messages(payload.get("messages") or []),
        "stream": False,
    }
    if payload.get("temperature") is not None:
        body["temperature"] = max(0.01, float(payload["temperature"]))
    if payload.get("max_tokens"):
        body["max_tokens"] = int(payload["max_tokens"])
    funcs = _functions(payload.get("tools") or [])
    if funcs:
        body["functions"] = funcs
        body["function_call"] = "auto"
    return body


async def post_completion(payload: dict[str, Any]) -> dict[str, Any]:
    if not gigachat_configured():
        raise GigaChatError("не задан GIGACHAT_AUTH_KEY")
    body = to_gigachat_payload(payload)
    async with httpx.AsyncClient(timeout=httpx.Timeout(settings.LLM_TIMEOUT_SECONDS), verify=_verify()) as client:
        for attempt in (0, 1):
            token = await _access_token(client, force=attempt == 1)
            resp = await client.post(
                f"{settings.GIGACHAT_BASE_URL.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json"},
                json=body,
            )
            if resp.status_code == 401 and attempt == 0:
                continue  # token expired early: refresh once
            break
    if resp.status_code != 200:
        logger.warning("gigachat_http_error", status=resp.status_code, body=resp.text[:200])
        raise GigaChatError(f"HTTP {resp.status_code}")
    return to_openai_response(resp.json())
