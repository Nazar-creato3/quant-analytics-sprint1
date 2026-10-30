from app.api.v1.endpoints.forecast import _direction_from_sign, _signal_from_payload


def test_direction_from_sign():
    assert _direction_from_sign(1) == "up"
    assert _direction_from_sign(-1) == "down"
    assert _direction_from_sign(0) == "neutral"
    assert _direction_from_sign(None) == "neutral"


def test_signal_from_hierarchy_payload():
    payload = {
        "hierarchy_output": {
            "point_forecast": {"expected_return_sign": 1, "momentum_score": 0.72},
        },
        "calibrated_confidence": 0.41,
    }
    signal = _signal_from_payload("aapl", payload)
    assert signal is not None
    assert signal["symbol"] == "AAPL"
    assert signal["direction"] == "up"
    assert signal["confidence"] == 0.41
    assert signal["source"] == "forecast_engine"


def test_signal_prefers_calibrated_over_momentum():
    payload = {
        "hierarchy_output": {
            "point_forecast": {"expected_return_sign": -1, "momentum_score": 0.33},
            "calibrated_confidence": 0.9,
        },
        "calibrated_confidence": 0.41,
    }
    signal = _signal_from_payload("NVDA", payload)
    assert signal["direction"] == "down"
    assert signal["confidence"] == 0.9


def test_signal_from_explicit_direction():
    payload = {
        "hierarchy_output": {
            "point_forecast": {"direction": "down", "confidence": 0.61},
        }
    }
    signal = _signal_from_payload("MSFT", payload)
    assert signal["direction"] == "down"
    assert signal["confidence"] == 0.61
