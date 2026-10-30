"""D-01B-1: live T-Bank golden lives outside the repo."""
from __future__ import annotations

from pathlib import Path

import pytest

TBANK = Path(r"C:\qa-private\golden")


@pytest.mark.xfail(
    not TBANK.exists() or not any(TBANK.iterdir()),
    reason="D-01B-1: dump not yet in C:\\qa-private\\golden\\",
    strict=True,
)
def test_tbank_real_account_golden_present():
    files = [p for p in TBANK.iterdir() if p.is_file()]
    assert files, "ожидалась выгрузка операций / брокерский отчёт Т-Банка"
