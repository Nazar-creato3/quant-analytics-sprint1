"""Prompt 16: wording filter, number check, template render."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.services.explanations.service import (
    FORBIDDEN,
    filter_wording,
    numbers_match,
    polish_with_model,
    render,
    term,
    trace_record,
)
from app.services.qa.feature_flags import reset_for_tests


def setup_function() -> None:
    reset_for_tests()


def teardown_function() -> None:
    reset_for_tests()


def test_filter_corpus_200():
    bad: list[str] = []
    for word in FORBIDDEN:
        for prefix in ("Пожалуйста ", "Сейчас ", "Итог: ", "Внимание, ", "Заметка — "):
            for suffix in (" актив", " позицию", " сейчас", " рынок", " портфель"):
                bad.append(f"{prefix}{word}{suffix}")
    while len(bad) < 100:
        bad.append(f"Мы рекомендуем сделку {len(bad)}")
    good = [
        f"HHI равен {i / 100}. Это описание состава, не прогноз."
        for i in range(100)
    ]
    assert len(bad) >= 100
    assert len(good) >= 100
    assert len(bad) + len(good) >= 200
    for text in bad:
        assert filter_wording(text)
    for text in good:
        assert filter_wording(text) == []


def test_fifty_renders_keep_numbers():
    reports = []
    for i in range(50):
        values = {
            "hhi": f"0.{i:02d}",
            "nav_clause": (
                f"Для портфеля {i * 1000} ₽ это значит, что крупные доли "
                "сильнее влияют на результат, чем мелкие."
            ),
            "enb": i + 1,
        }
        block = render("hhi", values)
        blob = f"{block['phrase']} {block['detail']} {block['learn']}"
        assert numbers_match(block["detail"], {"hhi": values["hhi"]})
        assert str(i * 1000) in block["detail"]
        assert polish_with_model(blob, values) == blob
        assert trace_record({"text": blob, "values": values})["numbers_ok"]
        assert "купите" not in blob.lower()
        reports.append(block)
    assert len(reports) == 50


def test_api_and_glossary():
    assert "квадратов" in term("HHI")
    client = TestClient(app)
    body = client.get("/api/v1/explanations", params={"key": "hhi", "hhi": "0.40"}).json()
    assert "0.40" in body["phrase"]
    assert body["source"] == "explanations"
