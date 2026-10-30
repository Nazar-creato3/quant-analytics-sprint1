"""User data map, export, erase, and pre-LLM redaction.

Secrets never appear in export or logs. External LLM stays off
(`qa_explanations_llm=0`) until [ЮРИСТ].
"""
from __future__ import annotations

import copy
import hashlib
import re
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from app.services.qa.feature_flags import is_enabled

PUBLIC_DATA_MAP: list[dict[str, str]] = [
    {"data": "Данные входа"},
    {"data": "Ключи подключения к площадкам"},
    {"data": "Позиции и сделки"},
    {"data": "Инвестиционный профиль"},
    {"data": "Пояснения"},
    {"data": "Идентификатор счёта"},
]

DATA_MAP: list[dict[str, str]] = [
    {
        "data": "Почта и вход в сервис",
        "store": "учётная запись",
        "leaves_rf": "нет",
        "ttl": "пока учётка не удалена",
    },
    {
        "data": "Ключи доступа к торговле",
        "store": "в зашифрованном виде",
        "leaves_rf": "нет",
        "ttl": "до отзыва или удаления учётки",
    },
    {
        "data": "Позиции, сделки и журнал действий",
        "store": "книга учёта",
        "leaves_rf": "нет",
        "ttl": "пока учётка не удалена",
    },
    {
        "data": "Инвестиционный профиль",
        "store": "анкета",
        "leaves_rf": "нет",
        "ttl": "пока учётка не удалена",
    },
    {
        "data": "Пояснения на экране",
        "store": "шаблоны в сервисе; при включённой языковой модели — ответ внешнего провайдера",
        "leaves_rf": "только обезличенные показатели, без имени, почты, телефона и номеров счетов",
        "ttl": "в сервисе не сохраняются",
    },
    {
        "data": "Имя и номер счёта в запросе к модели",
        "store": "не хранятся",
        "leaves_rf": "сырые значения не уходят",
        "ttl": "не сохраняются",
    },
]

# What may leave the process toward a model. See docs/architecture/llm-outbound-fields.md.
OUTBOUND_FIELD_TABLE: list[dict[str, str]] = [
    {
        "field": "account_id, broker_account_id, account_number, broker_account",
        "treatment": "replaced with sha256 hex prefix",
        "may_send": "hash only",
    },
    {
        "field": "name, client_name, full_name, first_name, last_name, holder_name, user_name",
        "treatment": "stripped when the value looks like a person (space or Cyrillic)",
        "may_send": "no",
    },
    {
        "field": "broker_token, token, api_token, tinkoff_token, access_token, authorization",
        "treatment": "stripped",
        "may_send": "no",
    },
    {
        "field": "email and api_key / api_secret / password assignments",
        "treatment": "stripped",
        "may_send": "no",
    },
    {
        "field": "ticker, price, quantity, percent, regime label, template text after redaction",
        "treatment": "kept",
        "may_send": "yes",
    },
    {
        "field": "tool or function name that is a single identifier",
        "treatment": "kept",
        "may_send": "yes",
    },
]

_ACCOUNT_KEYS = frozenset(
    {
        "account_id",
        "accountid",
        "broker_account",
        "broker_account_id",
        "account_number",
        "user_id",
        "userid",
        "owner_id",
        "email",
        "phone",
        "contact_email",
        "contact_phone",
    }
)
_NAME_KEYS = frozenset(
    {"name", "client_name", "full_name", "first_name", "last_name", "holder_name", "user_name"}
)
_TOKEN_KEYS = frozenset(
    {
        "broker_token",
        "token",
        "api_token",
        "tinkoff_token",
        "tinkoff_api_token",
        "access_token",
        "authorization",
        "bearer",
        "api_key",
        "api_secret",
        "password",
        "secret",
    }
)
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# +7 / 8 phone numbers in any common spacing
_PHONE = re.compile(r"(?<!\d)(?:\+7|8)[\s(-]*\d{3}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}(?!\d)")
# card / bank account numbers: 12+ digits in a row, or 16 digits in groups of 4
_LONG_DIGITS = re.compile(r"(?<!\d)(?<!\d[.,])(?:\d{12,}|\d{4}(?:[ -]\d{4}){3})(?!\d)(?![.,]\d)")
_UUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
_KEYISH = re.compile(r"(?i)(api[_-]?secret|api[_-]?key|token|password)\s*[:=]\s*\S+")
_LABELED_ACCOUNT = re.compile(
    r"(?i)\b(?:account(?:[_\s-]?id|[_\s-]?number)|broker[_\s-]?account(?:[_\s-]?id)?)\s*[:=]\s*([A-Za-z0-9._:-]{4,})"
)
_LABELED_TOKEN = re.compile(
    r"(?i)\b(?:broker[_\s-]?token|api[_\s-]?token|access[_\s-]?token|tinkoff[_\s-]?token|token)\s*[:=]\s*(\S+)"
)
_LABELED_NAME = re.compile(
    r"(?i)\b(?:client[_\s-]?name|full[_\s-]?name|first[_\s-]?name|last[_\s-]?name|"
    r"holder[_\s-]?name|user[_\s-]?name|name)\s*[:=]\s*"
    r"([A-Za-z\u0400-\u04FF]+(?:[ .'-][A-Za-z\u0400-\u04FF]+)+)"
)

_lock = Lock()
_erased: set[str] = set()


def reset_privacy_state() -> None:
    with _lock:
        _erased.clear()


_PERSON_WORD = re.compile(r"^[A-ZА-ЯЁ][a-zа-яё]+(?:-[A-ZА-ЯЁ][a-zа-яё]+)?$")


def _looks_like_person(value: str) -> bool:
    """Two or three capitalised words, letters only: "Иван Петров", "Anna Smith".

    Security and company names ("Сбербанк", "Газпром нефть", "SBER") are kept so the
    model still knows what the portfolio holds.
    """
    words = value.strip().split()
    return 2 <= len(words) <= 3 and all(_PERSON_WORD.match(w) for w in words)


def _sensitive_kind(key: str, value: Any) -> str | None:
    name = key.strip().lower().replace("-", "_")
    if name in _ACCOUNT_KEYS and isinstance(value, str) and value.strip():
        return "account"
    if name in _TOKEN_KEYS and isinstance(value, str) and value.strip():
        return "token"
    if name in _NAME_KEYS and isinstance(value, str) and value.strip() and (
        name != "name" or _looks_like_person(value)
    ):
        return "name"
    return None


def _labeled_secrets(text: str) -> set[str]:
    found: set[str] = set()
    for pattern in (_LABELED_ACCOUNT, _LABELED_TOKEN, _LABELED_NAME):
        for match in pattern.finditer(text):
            value = match.group(1).strip()
            if len(value) >= 4:
                found.add(value)
    return found


def _scrub_text(text: str, secrets: set[str]) -> str:
    cleaned = text
    for secret in sorted(secrets, key=len, reverse=True):
        if len(secret) >= 4 and secret in cleaned:
            cleaned = cleaned.replace(secret, "[redacted]")
    cleaned = _EMAIL.sub("[redacted-email]", cleaned)
    cleaned = _PHONE.sub("[redacted-phone]", cleaned)
    cleaned = _UUID.sub("[id]", cleaned)
    cleaned = _LONG_DIGITS.sub("[redacted-number]", cleaned)
    return _KEYISH.sub(r"\1=[redacted]", cleaned)


def anonymize_for_external_llm(text: str) -> str:
    """Strip emails, labeled ids, person names, and tokens before any model."""
    return _scrub_text(text, _labeled_secrets(text))


def _account_hash(value: str) -> str:
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return f"sha256:{digest}"


def prepare_llm_outbound(payload: dict[str, Any]) -> dict[str, Any]:
    """Copy a model request and remove raw account ids, names, and broker tokens.

    Account ids are replaced with a sha256 prefix. Person names and broker
    tokens are removed. The same raw strings are scrubbed from free text.
    """
    secrets: set[str] = set()

    def collect(node: Any) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                kind = _sensitive_kind(str(key), value)
                if kind and isinstance(value, str):
                    secrets.add(value.strip())
                else:
                    collect(value)
        elif isinstance(node, list):
            for item in node:
                collect(item)
        elif isinstance(node, str):
            secrets.update(_labeled_secrets(node))

    collect(payload)

    def replace(node: Any) -> Any:
        if isinstance(node, dict):
            out: dict[str, Any] = {}
            for key, value in node.items():
                kind = _sensitive_kind(str(key), value)
                if kind == "account" and isinstance(value, str):
                    out[key] = _account_hash(value.strip())
                elif kind in {"name", "token"}:
                    out[key] = "[redacted]"
                else:
                    out[key] = replace(value)
            return out
        if isinstance(node, list):
            return [replace(item) for item in node]
        if isinstance(node, str):
            return _scrub_text(node, secrets)
        return node

    cloned = copy.deepcopy(payload)
    return replace(cloned)


def export_user_bundle(user_id: str) -> dict[str, Any]:
    if not is_enabled("qa_privacy"):
        raise RuntimeError("qa_privacy off")
    if not user_id:
        raise ValueError("user_id required")
    from app.services.act_desk.service import get_profile, journal_for
    from app.services.investment_profile.service import get_raw_profile as get_inv, history_for

    profile = get_profile(user_id) or {}
    try:
        inv = get_inv(user_id) or {}
    except Exception:
        inv = {}
    journal = journal_for(user_id)
    return {
        "user_id": user_id,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "data_map": PUBLIC_DATA_MAP,
        "profile": {k: v for k, v in profile.items() if k != "secrets"},
        "investment_profile": {k: v for k, v in inv.items() if k != "secrets"},
        "investment_profile_history": history_for(user_id) if inv else [],
        "act_journal": [{"name": i.get("name"), "at": i.get("at"), "hash": i.get("hash")} for i in journal],
        "secrets_included": False,
        "localization": "RU",
        "retention_note": "ключи и журнал удаляются запросом erase; бэкапы — по runbook Промпта 29",
    }


def erase_user_local(user_id: str) -> dict[str, Any]:
    if not is_enabled("qa_privacy"):
        raise RuntimeError("qa_privacy off")
    if not user_id:
        raise ValueError("user_id required")
    from app.services.act_desk.service import erase_user
    from app.services.investment_profile.service import erase_user as erase_inv

    erase_user(user_id)
    erase_inv(user_id)
    with _lock:
        _erased.add(user_id)
    return {"user_id": user_id, "erased": True, "secrets_included": False}


