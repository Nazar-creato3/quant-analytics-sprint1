"""An empty maneuver report must say why every idea was dropped, in Russian."""
from app.services.risk.maneuver_generator import ManeuverGenerator, _risk_reason_ru


def test_risk_reason_categories():
    assert _risk_reason_ru("Confidence 49.31% below threshold 50.00%") == "уверенность ниже порога"
    assert _risk_reason_ru("Max exposure reached: 95.0%") == "исчерпан бюджет на сделки"
    assert _risk_reason_ru(None) == "ограничения риска"


def test_summary_lists_top_reasons():
    gen = ManeuverGenerator(portfolio_size=10_000.0)
    assert gen._rejects_summary_ru() == "Подходящих сделок не найдено"
    for _ in range(3):
        gen._reject("рыночный режим не допускает новых позиций")
    gen._reject("нет направленного сигнала")
    text = gen._rejects_summary_ru()
    assert text.startswith("Сделки не предложены. Причины: рыночный режим не допускает новых позиций — 3")
    assert "нет направленного сигнала — 1" in text
