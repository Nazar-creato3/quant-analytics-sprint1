"""Self-correcting layer: prediction log, review hooks, metrics."""
from __future__ import annotations

import threading
import time
import uuid
from contextvars import ContextVar, Token
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from app.services.terminal_platform.agents.schemas import AgentAnswer


_owner_ctx: ContextVar[str] = ContextVar("prediction_owner", default="")


class PredictionRecord(BaseModel):
    id: str
    agent_type: str
    query: str
    answer: AgentAnswer
    owner_id: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    outcome: str | None = None
    outcome_at: datetime | None = None
    review_notes: str | None = None
    correct: bool | None = None
    score: float | None = None  # 0..1 post-hoc quality


class PerformanceMetrics(BaseModel):
    total_predictions: int = 0
    scored: int = 0
    correct_count: int = 0
    accuracy: float | None = None
    mean_confidence: float | None = None
    mean_score: float | None = None
    by_agent: dict[str, dict[str, Any]] = Field(default_factory=dict)
    calibration_gap: float | None = None  # mean(confidence) - accuracy


@dataclass
class _StoreState:
    records: dict[str, PredictionRecord] = field(default_factory=dict)
    lock: threading.RLock = field(default_factory=threading.RLock)


class PredictionStore:
    """In-memory prediction/outcome log (swap for DB later)."""

    _instance: PredictionStore | None = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        self._state = _StoreState()

    @classmethod
    def instance(cls) -> PredictionStore:
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @classmethod
    def reset_instance(cls) -> PredictionStore:
        with cls._instance_lock:
            cls._instance = cls()
            return cls._instance

    @classmethod
    def bind_owner(cls, owner_id: str) -> Token[str]:
        return _owner_ctx.set(owner_id or "")

    @classmethod
    def reset_owner(cls, token: Token[str]) -> None:
        _owner_ctx.reset(token)

    def log_prediction(
        self,
        *,
        agent_type: str,
        query: str,
        answer: AgentAnswer,
        owner_id: str | None = None,
    ) -> str:
        pid = uuid.uuid4().hex
        rec = PredictionRecord(
            id=pid,
            agent_type=agent_type,
            query=query,
            answer=answer,
            owner_id=owner_id if owner_id is not None else _owner_ctx.get(),
        )
        with self._state.lock:
            self._state.records[pid] = rec
        return pid

    def record_outcome(
        self,
        prediction_id: str,
        *,
        outcome: str,
        correct: bool | None = None,
        score: float | None = None,
        review_notes: str | None = None,
    ) -> PredictionRecord:
        with self._state.lock:
            rec = self._state.records.get(prediction_id)
            if rec is None or not self._owned(rec, owner_id=_owner_ctx.get()):
                raise KeyError("unknown prediction")
            updated = rec.model_copy(
                update={
                    "outcome": outcome,
                    "outcome_at": datetime.now(timezone.utc),
                    "correct": correct,
                    "score": score,
                    "review_notes": review_notes,
                }
            )
            self._state.records[prediction_id] = updated
            return updated

    def get(self, prediction_id: str, *, owner_id: str | None = None) -> PredictionRecord | None:
        oid = owner_id if owner_id is not None else _owner_ctx.get()
        with self._state.lock:
            rec = self._state.records.get(prediction_id)
            if rec is None or not self._owned(rec, owner_id=oid):
                return None
            return rec

    def list_records(self, *, limit: int = 100, owner_id: str | None = None) -> list[PredictionRecord]:
        oid = owner_id if owner_id is not None else _owner_ctx.get()
        with self._state.lock:
            items = sorted(
                (r for r in self._state.records.values() if self._owned(r, owner_id=oid)),
                key=lambda r: r.created_at,
                reverse=True,
            )
            return items[:limit]

    @staticmethod
    def _owned(rec: PredictionRecord, *, owner_id: str) -> bool:
        if not owner_id:
            return True
        return rec.owner_id == owner_id

    def metrics(self, *, owner_id: str | None = None) -> PerformanceMetrics:
        oid = owner_id if owner_id is not None else _owner_ctx.get()
        with self._state.lock:
            records = [r for r in self._state.records.values() if self._owned(r, owner_id=oid)]

        total = len(records)
        scored = [r for r in records if r.correct is not None or r.score is not None]
        correct = [r for r in records if r.correct is True]
        confidences = [r.answer.confidence for r in records]
        scores = [r.score for r in records if r.score is not None]

        accuracy = (len(correct) / len(scored)) if scored else None
        mean_conf = (sum(confidences) / len(confidences)) if confidences else None
        mean_score = (sum(scores) / len(scores)) if scores else None
        calib = None
        if accuracy is not None and mean_conf is not None:
            calib = mean_conf - accuracy

        by_agent: dict[str, dict[str, Any]] = {}
        for r in records:
            bucket = by_agent.setdefault(
                r.agent_type,
                {"total": 0, "scored": 0, "correct": 0, "mean_confidence": 0.0, "_conf_sum": 0.0},
            )
            bucket["total"] += 1
            bucket["_conf_sum"] += r.answer.confidence
            if r.correct is not None or r.score is not None:
                bucket["scored"] += 1
            if r.correct is True:
                bucket["correct"] += 1

        for bucket in by_agent.values():
            t = bucket["total"] or 1
            bucket["mean_confidence"] = bucket.pop("_conf_sum") / t
            if bucket["scored"]:
                bucket["accuracy"] = bucket["correct"] / bucket["scored"]
            else:
                bucket["accuracy"] = None

        return PerformanceMetrics(
            total_predictions=total,
            scored=len(scored),
            correct_count=len(correct),
            accuracy=accuracy,
            mean_confidence=mean_conf,
            mean_score=mean_score,
            by_agent=by_agent,
            calibration_gap=calib,
        )


def self_review(
    record: PredictionRecord,
    *,
    outcome: str,
    expected_keywords: list[str] | None = None,
) -> dict[str, Any]:
    """Lightweight self-review hook: keyword overlap + confidence sanity."""
    answer_l = (record.answer.answer or "").lower()
    hits = 0
    expected = expected_keywords or []
    for kw in expected:
        if kw.lower() in answer_l or kw.lower() in outcome.lower():
            hits += 1
    overlap = (hits / len(expected)) if expected else None
    correct = None
    if overlap is not None:
        correct = overlap >= 0.5
    score = overlap if overlap is not None else record.answer.confidence
    notes = (
        f"keyword_overlap={overlap!s}; confidence={record.answer.confidence:.2f}; "
        f"reviewed_at={time.time():.0f}"
    )
    return {
        "correct": correct,
        "score": score,
        "review_notes": notes,
        "outcome": outcome,
    }
