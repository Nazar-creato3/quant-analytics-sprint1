"""GA16-309: live reject reason must not name the feature flag."""

from unittest.mock import patch

from app.services.bot_core import service


def test_live_reject_does_not_name_flag():
    service._bots["b1"] = {"user_id": "u1", "live": False}
    with patch.object(service, "is_enabled", return_value=False), patch.object(
        service, "_cfg", return_value={"paper_days_before_live": 14}
    ):
        out = service.request_live("b1")
    assert out["status"] == "rejected"
    assert "qa_act_live" not in out["reason"]
    assert "флаг" not in out["reason"].lower()
