"""GA16-330: order errors must not expose str(exc) to the client."""

from pathlib import Path


def test_manual_order_handler_has_no_str_exc_in_http_detail():
    text = Path("app/api/v1/endpoints/orders.py").read_text(encoding="utf-8")
    # Narrow to submit_manual_order exception block.
    start = text.index('"""Submit a manual order')
    end = text.index("@router.get(\"\", response_model=list[ManualOrderOut])", start)
    block = text[start:end]
    assert "detail=str(exc)" not in block
    assert "detail=f\"Не удалось разместить ордер: {exc}\"" not in block
    assert "По этой бумаге заявку разместить нельзя." in block
