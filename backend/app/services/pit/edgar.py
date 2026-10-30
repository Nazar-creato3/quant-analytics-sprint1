"""EDGAR 10-K risk-factor light parse + hashed embedding. No Brain Language."""
from __future__ import annotations

import hashlib
import re
from typing import Any, Iterable, Mapping

from app.services.pit.clock import as_day, latest_visible, observation

_ITEM_1A = re.compile(r"item\s+1a[\.\s:]*risk\s+factors", re.IGNORECASE)
_ITEM_1B = re.compile(r"item\s+1b[\.\s:]", re.IGNORECASE)
_ITEM_2 = re.compile(r"item\s+2[\.\s:]", re.IGNORECASE)


def extract_risk_factors(text: str, *, max_chars: int = 12_000) -> str:
    blob = str(text or "")
    if not blob.strip():
        return ""
    start = _ITEM_1A.search(blob)
    if not start:
        return blob[:max_chars]
    rest = blob[start.end() :]
    end = _ITEM_1B.search(rest) or _ITEM_2.search(rest)
    chunk = rest[: end.start()] if end else rest
    return chunk.strip()[:max_chars]


def hashed_embedding(text: str, *, dim: int = 32) -> list[float]:
    """Signed hashing trick. Offline, deterministic, not a paid language model."""
    vec = [0.0] * max(8, int(dim))
    tokens = re.findall(r"[a-z]{3,}", (text or "").lower())
    if not tokens:
        return vec
    for tok in tokens:
        digest = hashlib.sha256(tok.encode("utf-8")).digest()
        idx = int.from_bytes(digest[:2], "little") % len(vec)
        sign = 1.0 if digest[2] % 2 == 0 else -1.0
        vec[idx] += sign
    norm = sum(x * x for x in vec) ** 0.5
    if norm <= 1e-12:
        return vec
    return [round(x / norm, 6) for x in vec]


def _finbert_mean_pool(text: str) -> list[float] | None:
    try:
        from app.services.news.finbert_sentiment import finbert_available, _load_finbert
        import torch
    except Exception:
        return None
    if not finbert_available():
        return None
    blob = (text or "").strip()[:512]
    if len(blob) < 8:
        return None
    tokenizer, model, device = _load_finbert()
    inputs = tokenizer(blob, return_tensors="pt", truncation=True, max_length=128)
    inputs = {k: v.to(device) for k, v in inputs.items()}
    with torch.no_grad():
        out = model.bert(**inputs) if hasattr(model, "bert") else model(**inputs, output_hidden_states=True)
        hidden = getattr(out, "last_hidden_state", None)
        if hidden is None:
            states = getattr(out, "hidden_states", None)
            hidden = states[-1] if states else None
        if hidden is None:
            return None
        vec = hidden.mean(dim=1).squeeze(0).detach().cpu().tolist()
    norm = sum(x * x for x in vec) ** 0.5
    if norm <= 1e-12:
        return [float(x) for x in vec]
    return [round(float(x) / norm, 6) for x in vec]


def risk_factor_embedding(text: str) -> tuple[list[float], str]:
    """FinBERT hidden mean if the local model is loaded; else hashing trick. Never Brain."""
    chunk = extract_risk_factors(text)
    semantic = _finbert_mean_pool(chunk)
    if semantic:
        return semantic, "finbert"
    return hashed_embedding(chunk), "hash"


def fact_rows_to_observations(series_id: str, rows: Iterable[Mapping[str, Any]]) -> list:
    """XBRL `end` is event_time; `filed` is knowledge_time. Never sort by end alone."""
    out = []
    for row in rows:
        if not isinstance(row, dict) or row.get("val") is None:
            continue
        try:
            val = float(row["val"])
        except (TypeError, ValueError):
            continue
        event = row.get("end") or row.get("instant")
        filed = row.get("filed") or row.get("accepted")
        out.append(observation(series_id, val, event_time=event, released=filed))
    return out


def latest_fact_as_of(rows: Iterable[Mapping[str, Any]], as_of: Any, *, series_id: str = "SEC_FACT") -> float | None:
    last = latest_visible(fact_rows_to_observations(series_id, rows), as_of)
    return None if last is None else last.value
