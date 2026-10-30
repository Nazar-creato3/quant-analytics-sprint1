"""Stooq bulk local store — parse + index + extract."""
from __future__ import annotations

import zipfile
from datetime import datetime, timezone
from pathlib import Path

from app.services.market_data.stooq_bulk_store import (
    StooqLocalClient,
    build_symbol_index,
    extract_zips_atomic,
    read_bars,
    read_latest_quote,
    resolve_symbol_file,
)


def _write_sample_txt(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "Date,Open,High,Low,Close,Volume\n"
        "2026-09-14,100.0,101.0,99.0,100.5,1000\n"
        "2026-09-15,100.5,102.0,100.0,101.5,1100\n",
        encoding="utf-8",
    )


def test_build_index_and_read_quote(tmp_path: Path) -> None:
    root = tmp_path / "stooq"
    current = root / "current" / "data" / "daily" / "us" / "nasdaq etfs"
    _write_sample_txt(current / "spy.us.txt")
    index = build_symbol_index(root / "current")
    assert index["spy.us"].endswith("spy.us.txt")

    # Seed manifest via extract path: write manifest manually through resolve after extract
    from app.services.market_data import stooq_bulk_store as store

    store.save_manifest(
        {
            "synced_at": datetime.now(timezone.utc).isoformat(),
            "packages": ["fixture"],
            "symbol_count": 1,
            "symbols": index,
        },
        root,
    )
    # Move files so current matches layout used by resolve
    assert resolve_symbol_file("SPY", root=root) is not None
    quote = read_latest_quote("SPY", root=root)
    assert quote["price"] == 101.5
    assert abs(float(quote["change_pct"]) - ((101.5 / 100.5) - 1) * 100) < 1e-6
    assert quote["source"] == "stooq_local"

    bars = read_bars("SPY", root=root)
    assert len(bars) == 2
    assert bars[-1]["close"] == 101.5


def test_extract_zip_atomic(tmp_path: Path) -> None:
    root = tmp_path / "stooq"
    inbox = root / "inbox"
    inbox.mkdir(parents=True)
    zip_path = inbox / "d_us_txt.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr(
            "data/daily/us/nasdaq etfs/qqq.us.txt",
            "Date,Open,High,Low,Close,Volume\n"
            "2026-09-15,200.0,201.0,199.0,200.5,500\n"
            "2026-09-16,200.5,202.0,200.0,201.0,600\n",
        )
    result = extract_zips_atomic([zip_path], root)
    assert result["ok"] is True
    assert result["symbols"] >= 1
    quote = read_latest_quote("QQQ", root=root)
    assert quote["price"] == 201.0


def test_overwrite_and_polish_csv(tmp_path: Path) -> None:
    from app.services.market_data.stooq_bulk_store import ingest_paths, store_status

    root = tmp_path / "stooq"
    # First sync: world-like zip
    z1 = tmp_path / "d_world_txt.zip"
    with zipfile.ZipFile(z1, "w") as zf:
        zf.writestr(
            "data/daily/world/cryptocurrencies/btc.v.txt",
            "Date,Open,High,Low,Close,Volume\n"
            "2026-09-15,100.0,101.0,99.0,100.5,10\n"
            "2026-09-16,100.5,102.0,100.0,101.0,12\n",
        )
    r1 = ingest_paths([z1], root=root)
    assert r1["ok"]
    assert read_latest_quote("BTC-USD", root=root)["price"] == 101.0

    # Overwrite with new world + Polish CSV
    z2 = tmp_path / "d_world_txt (1).zip"
    with zipfile.ZipFile(z2, "w") as zf:
        zf.writestr(
            "data/daily/world/cryptocurrencies/btc.v.txt",
            "Date,Open,High,Low,Close,Volume\n"
            "2026-09-16,101.0,103.0,100.0,102.5,20\n"
            "2026-09-17,102.5,104.0,102.0,103.0,22\n",
        )
    csv = tmp_path / "api_us_d.csv"
    csv.write_text(
        "Data,Otwarcie,Najwyzszy,Najnizszy,Zamkniecie,Wolumen\n"
        "2026-09-15,4.0,4.1,3.9,4.05,100\n"
        "2026-09-16,4.05,4.2,4.0,4.1,120\n",
        encoding="utf-8",
    )
    r2 = ingest_paths([z2, csv], root=root)
    assert r2["ok"]
    assert r2.get("overwrite") is True
    assert read_latest_quote("BTC-USD", root=root)["price"] == 103.0
    assert read_latest_quote("api_us_d", root=root)["price"] == 4.1
    st = store_status(root)
    assert st["symbol_count"] >= 2
    assert not list((root / "inbox").glob("*.zip"))
    assert not list((root / "inbox").glob("*.csv"))


def test_local_client_get_bars(tmp_path: Path) -> None:
    import asyncio

    root = tmp_path / "stooq"
    current = root / "current" / "data" / "daily" / "us" / "nyse etfs"
    _write_sample_txt(current / "dia.us.txt")
    from app.services.market_data import stooq_bulk_store as store

    store.save_manifest(
        {
            "synced_at": "x",
            "packages": [],
            "symbol_count": 1,
            "symbols": build_symbol_index(root / "current"),
        },
        root,
    )
    original = store.bulk_root
    store.bulk_root = lambda: root  # type: ignore[assignment]
    try:
        client = StooqLocalClient()
        end = datetime(2026, 9, 16, tzinfo=timezone.utc)
        start = datetime(2026, 9, 1, tzinfo=timezone.utc)

        async def _run():
            bars = await client.get_bars("DIA", "1d", start, end)
            q = await client.get_latest_quote("DIA")
            return bars, q

        bars, q = asyncio.run(_run())
        assert len(bars) == 2
        assert q["price"] == 101.5
    finally:
        store.bulk_root = original  # type: ignore[assignment]
