from app.services.risk.human_copy import build_position_rationale, market_beat_explanation


def test_rationale_is_plain_language():
    text = build_position_rationale(
        strategy="trend_following",
        direction="short",
        confidence=0.75,
        regime="trending_down",
        features={"rsi_14": 72, "sma_cross_5_20": 0, "price_vs_sma20": -0.04, "volume_ratio": 1.4},
        is_fallback=False,
        risk_reward=1.8,
        sentiment=-0.4,
    )
    assert "следование за трендом" in text
    assert "R:R" not in text
    assert "ML-модель" not in text
    assert "MACD" not in text


def test_market_beat_untrusted_is_plain():
    text = market_beat_explanation(score20=5, p20=0.5, trusted=False)
    assert "ECE" not in text
    assert "нейтральная оценка 5 из 10" in text


COLLOQUIAL = ("монет", "нервн", "дёрга", "разогнал", "надавил", "целится", "пятёрк", "лучше не входить", "держим сторону")


def test_texts_use_business_language():
    texts = [
        market_beat_explanation(score20=5, p20=0.5, trusted=True),
        market_beat_explanation(score20=5, p20=0.5, trusted=False),
        build_position_rationale(
            strategy="momentum", direction="long", confidence=0.6, regime="volatile",
            features={"rsi_14": 75, "volume_ratio": 0.5}, is_fallback=True, risk_reward=2.0, sentiment=0.5,
        ),
    ]
    joined = " ".join(texts).lower()
    for word in COLLOQUIAL:
        assert word not in joined, word
    assert "50 на 50" in texts[0]
