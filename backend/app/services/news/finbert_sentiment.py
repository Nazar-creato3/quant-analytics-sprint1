"""FinBERT sentiment scoring (ProsusAI/finbert, Apache-2.0).

Runs on the existing news feed text at ingest time. Falls back to VADER when
transformers/torch are unavailable (e.g. minimal Celery pipeline venv).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache

from app.core.logging import get_logger

logger = get_logger(__name__)

FINBERT_MODEL_ID = "ProsusAI/finbert"
MAX_CHARS = 512
_BATCH_SIZE = 16


@dataclass(frozen=True, slots=True)
class SentimentResult:
    score: float  # -1..1 signed confidence
    label: str  # positive | negative | neutral
    confidence: float  # 0..1 max class probability
    engine: str  # finbert | vader | keyword


def finbert_available() -> bool:
    if (os.getenv("FINBERT_ENABLED") or "1").strip().lower() in ("0", "false", "no", "off"):
        return False
    try:
        import torch  # noqa: F401
        from transformers import AutoModelForSequenceClassification  # noqa: F401

        return True
    except Exception:
        return False


@lru_cache(maxsize=1)
def _load_finbert():
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    import torch

    tokenizer = AutoTokenizer.from_pretrained(FINBERT_MODEL_ID)
    model = AutoModelForSequenceClassification.from_pretrained(
        FINBERT_MODEL_ID,
        use_safetensors=True,
    )
    model.eval()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device)
    return tokenizer, model, device


def _results_from_probs(probs_row: list[float]) -> SentimentResult:
    labels = ("positive", "negative", "neutral")
    best_idx = max(range(len(probs_row)), key=lambda i: probs_row[i])
    label = labels[best_idx]
    confidence = float(probs_row[best_idx])
    signed = confidence if label == "positive" else (-confidence if label == "negative" else 0.0)
    return SentimentResult(
        score=round(signed, 4),
        label=label,
        confidence=round(confidence, 4),
        engine="finbert",
    )


def score_finbert_batch(texts: list[str]) -> list[SentimentResult | None]:
    """Score multiple texts in one forward pass (much faster than per-article calls)."""
    cleaned = [(t or "").strip() for t in texts]
    out: list[SentimentResult | None] = [None] * len(cleaned)
    if not finbert_available():
        return out

    indexed: list[tuple[int, str]] = [
        (idx, text[:MAX_CHARS]) for idx, text in enumerate(cleaned) if len(text) >= 8
    ]
    if not indexed:
        return out

    try:
        import torch

        tokenizer, model, device = _load_finbert()
        for batch_start in range(0, len(indexed), _BATCH_SIZE):
            chunk = indexed[batch_start : batch_start + _BATCH_SIZE]
            batch_texts = [text for _, text in chunk]
            inputs = tokenizer(
                batch_texts,
                return_tensors="pt",
                truncation=True,
                padding=True,
                max_length=128,
            )
            inputs = {k: v.to(device) for k, v in inputs.items()}
            with torch.no_grad():
                logits = model(**inputs).logits
                probs = torch.softmax(logits, dim=-1).cpu().tolist()
            for (orig_idx, _), prob_row in zip(chunk, probs, strict=True):
                out[orig_idx] = _results_from_probs(prob_row)
    except Exception as exc:
        logger.debug("FinBERT batch scoring failed", error=str(exc))
    return out


def score_finbert(text: str) -> SentimentResult | None:
    """Score text with FinBERT; return None if model unavailable or text empty."""
    results = score_finbert_batch([text])
    return results[0] if results else None


def score_text_sentiment(text: str) -> SentimentResult:
    """Primary sentiment entry — FinBERT when available, else VADER/keyword."""
    finbert = score_finbert(text)
    if finbert is not None:
        return finbert
    from app.services.news.client import score_sentiment_vader

    score, label = score_sentiment_vader(text)
    confidence = abs(float(score))
    return SentimentResult(
        score=float(score),
        label=label,
        confidence=round(confidence, 4),
        engine="vader",
    )
