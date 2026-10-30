import json
from pathlib import Path

import pandas as pd

from app.services.futures_market.math import volume_profile

FIXTURE = Path(__file__).resolve().parents[2] / "data" / "futures_market" / "trades_mix_fixture.json"
FUTOI = Path(__file__).resolve().parents[2] / "data" / "futures_market" / "futoi.yaml"


def _pandas_profile(trades: list[dict]) -> dict:
    df = pd.DataFrame(trades)
    g = df.groupby("price", sort=True)["qty"].sum()
    poc = float(g.idxmax())
    buy = df[df["side"] == "buy"]["qty"].sum()
    sell = df[df["side"] == "sell"]["qty"].sum()
    return {"poc": poc, "delta": float(buy - sell), "total": float(g.sum())}


def test_volume_profile_matches_pandas() -> None:
    trades = json.loads(FIXTURE.read_text(encoding="utf-8"))
    got = volume_profile(trades, tick=1.0)
    exp = _pandas_profile(trades)
    assert got["poc"] == exp["poc"]
    assert got["delta"] == exp["delta"]
    assert got["total_volume"] == exp["total"]
    assert got["poc"] == 101
    assert got["delta"] == 37


def test_futoi_three_dates() -> None:
    text = FUTOI.read_text(encoding="utf-8")
    dates = [
        line.split(":", 1)[1].strip().strip('"')
        for line in text.splitlines()
        if line.strip().lstrip("- ").startswith("date:")
    ]
    assert dates == ["2024-03-01", "2024-03-04", "2024-03-05"]
