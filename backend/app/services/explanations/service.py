"""Explanation templates + wording filter (Prompt 16). LLM off unless lawyer flag."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from app.services.qa.feature_flags import is_enabled

CONFIG_VERSION = "explanations.v1"
logger = logging.getLogger(__name__)

FORBIDDEN = (
    "купите",
    "продайте",
    "рекомендуем",
    "рекомендую",
    "советуем",
    "подходит вам",
    "соответствует вашему профилю",
    "гарантируем",
    "гарантия доходности",
    "обещаем",
    "обязательно заработаете",
    "без риска",
    "100% прибыль",
    "срочно купите",
    "не упустите",
)

_NUMBER = re.compile(r"-?\d+(?:[.,]\d+)?")


def load_pack() -> dict[str, Any]:
    return json.loads(Path(__file__).with_name("templates.json").read_text(encoding="utf-8"))


def render(key: str, values: dict[str, Any]) -> dict[str, str]:
    if not is_enabled("qa_explanations"):
        raise RuntimeError("qa_explanations off")
    pack = load_pack()
    tmpl = (pack.get("templates") or {}).get(key)
    if not tmpl:
        raise KeyError(key)
    out: dict[str, str] = {}
    for part in ("phrase", "detail", "learn"):
        raw = str(tmpl[part])
        text = _fill(raw, values)
        hits = filter_wording(text)
        if hits:
            logger.info("explanation_filter_block", extra={"key": key, "part": part, "hits": hits})
            raise ValueError(f"forbidden wording: {hits}")
        used = {name: values[name] for name in re.findall(r"\{(\w+)\}", raw) if name in values}
        if not numbers_match(text, used):
            logger.info("explanation_number_mismatch", extra={"key": key, "part": part})
            raise ValueError("number mismatch")
        out[part] = polish_with_model(text, used)
        trace_record({"text": out[part], "values": used})
    return {**out, "key": key, "config_version": CONFIG_VERSION, "source": "explanations"}


def _fill(template: str, values: dict[str, Any]) -> str:
    text = template
    for name, raw in values.items():
        text = text.replace("{" + name + "}", str(raw))
    return text


def filter_wording(text: str) -> list[str]:
    low = text.lower()
    return [w for w in FORBIDDEN if w in low]


def numbers_match(text: str, values: dict[str, Any]) -> bool:
    found = {_norm_num(m.group(0)) for m in _NUMBER.finditer(text)}
    for value in values.values():
        if _is_numeric(value) and _norm_num(value) not in found:
            return False
    return True


def _is_numeric(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        return bool(_NUMBER.fullmatch(value.replace(" ", "")))
    return False


def _norm_num(value: Any) -> str:
    if isinstance(value, float):
        return format(value, ".10g")
    text = str(value).replace(",", ".").replace(" ", "")
    try:
        return format(float(text), ".10g")
    except ValueError:
        return text


def term(name: str) -> str:
    return str((load_pack().get("terms") or {}).get(name) or "")


def polish_with_model(text: str, values: dict[str, Any]) -> str:
    """External model is off until [ЮРИСТ]. Always return the template text."""
    from app.services.privacy.service import anonymize_for_external_llm

    safe = anonymize_for_external_llm(text)
    if not is_enabled("qa_explanations_llm"):
        return text
    return safe


def trace_record(payload: dict[str, Any]) -> dict[str, Any]:
    """GenAI-shaped trace without PII. Prompt/response bodies only if flag on."""
    record = {
        "gen_ai.system": "none",
        "gen_ai.request.model": "template",
        "filter_ok": not filter_wording(str(payload.get("text") or "")),
        "numbers_ok": numbers_match(str(payload.get("text") or ""), payload.get("values") or {}),
    }
    if is_enabled("qa_explanations_trace_bodies"):
        record["text"] = payload.get("text")
    return record
