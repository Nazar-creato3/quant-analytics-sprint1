"""What leaves for the language model: no identity, all the numbers the answer needs."""
from __future__ import annotations

from app.services.privacy.service import anonymize_for_external_llm, prepare_llm_outbound

UID = "3f2b8c1e-9a4d-4e7b-8c21-5d6f7a8b9c0d"


def _request() -> dict:
    return {
        "model": "any",
        "messages": [
            {"role": "system", "content": "Ты помощник по портфелю."},
            {
                "role": "user",
                "content": (
                    f"Пользователь {UID}, email ivan.petrov@mail.ru, тел. +7 (916) 123-45-67, "
                    "карта 4276 1234 5678 9012, счёт 40817810099910004312. "
                    "Портфель: SBER 120 шт по 312.45 ₽, GAZP 300 шт, доля облигаций 35%, "
                    "стоимость 1 250 000 ₽, VaR 95% = 2.4%, горизонт 2030-01-01. Почему просадка?"
                ),
            },
        ],
        "context": {
            "user_id": UID,
            "account_id": "2000123456",
            "full_name": "Иван Петров",
            "holdings": [
                {"ticker": "SBER", "name": "Сбербанк", "qty": 120, "price": 312.45},
                {"ticker": "GAZP", "name": "Газпром", "qty": 300, "price": 128.1},
            ],
            "nav_rub": 1250000,
        },
    }


def test_identity_is_removed() -> None:
    out = str(prepare_llm_outbound(_request()))
    for leaked in (UID, "ivan.petrov@mail.ru", "123-45-67", "4276 1234 5678 9012",
                   "40817810099910004312", "2000123456", "Иван Петров"):
        assert leaked not in out, leaked


def test_numbers_and_securities_survive() -> None:
    out = prepare_llm_outbound(_request())
    text = out["messages"][1]["content"]
    for kept in ("SBER 120 шт по 312.45 ₽", "GAZP 300 шт", "35%", "1 250 000 ₽", "VaR 95% = 2.4%", "2030-01-01"):
        assert kept in text, kept
    holdings = out["context"]["holdings"]
    assert holdings[0] == {"ticker": "SBER", "name": "Сбербанк", "qty": 120, "price": 312.45}
    assert holdings[1]["name"] == "Газпром"
    assert out["context"]["nav_rub"] == 1250000
    assert out["messages"][0]["content"].startswith("Ты помощник по портфелю.")


def test_free_text_helper_keeps_finance() -> None:
    raw = "Номер 8 916 123 45 67. Доходность 12.5% за 2025 год, сумма 15000000 ₽."
    clean = anonymize_for_external_llm(raw)
    assert "916 123 45 67" not in clean
    assert "12.5%" in clean and "2025" in clean and "15000000" in clean
