"""ITCH 5.0 replay: messages built byte-for-byte to the Nasdaq spec."""
from __future__ import annotations

import gzip
import io
import struct
from datetime import datetime, timezone
from pathlib import Path

from app.services.us_book_replay import itch
from app.services.us_book_replay import store


def _ts(sec: float) -> bytes:
    return int(sec * 1_000_000_000).to_bytes(6, "big")


def _msg(body: bytes) -> bytes:
    return struct.pack(">H", len(body)) + body


def system(sec: float) -> bytes:
    return _msg(b"S" + struct.pack(">HH", 0, 0) + _ts(sec) + b"O")


def directory(loc: int, sym: str) -> bytes:
    body = b"R" + struct.pack(">HH", loc, 0) + _ts(3600) + sym.ljust(8).encode() + b"Q" + b"N" + struct.pack(">I", 100) + b"N" + b"C" + b"  " + b"P" + b"N" + b"N" + b"1" + b"N" + struct.pack(">I", 0) + b"N"
    assert len(body) == 39
    return _msg(body)


def add(loc: int, sec: float, ref: int, side: str, shares: int, price: float, mpid: bool = False) -> bytes:
    body = (b"F" if mpid else b"A") + struct.pack(">HH", loc, 0) + _ts(sec) + struct.pack(">Q", ref) + side.encode() + struct.pack(">I", shares) + b"AAPL    " + struct.pack(">I", round(price * 10_000))
    if mpid:
        body += b"GSCO"
    assert len(body) == (40 if mpid else 36)
    return _msg(body)


def execute(loc: int, sec: float, ref: int, shares: int) -> bytes:
    body = b"E" + struct.pack(">HH", loc, 0) + _ts(sec) + struct.pack(">QIQ", ref, shares, 1)
    assert len(body) == 31
    return _msg(body)


def cancel(loc: int, sec: float, ref: int, shares: int) -> bytes:
    body = b"X" + struct.pack(">HH", loc, 0) + _ts(sec) + struct.pack(">QI", ref, shares)
    assert len(body) == 23
    return _msg(body)


def delete(loc: int, sec: float, ref: int) -> bytes:
    body = b"D" + struct.pack(">HH", loc, 0) + _ts(sec) + struct.pack(">Q", ref)
    assert len(body) == 19
    return _msg(body)


def replace(loc: int, sec: float, old: int, new: int, shares: int, price: float) -> bytes:
    body = b"U" + struct.pack(">HH", loc, 0) + _ts(sec) + struct.pack(">QQII", old, new, shares, round(price * 10_000))
    assert len(body) == 35
    return _msg(body)


OPEN = itch.SESSION_OPEN


def _stream() -> bytes:
    return b"".join(
        [
            system(3 * 3600),
            directory(7, "AAPL"),
            directory(8, "MSFT"),  # not tracked
            add(7, OPEN - 10, 1, "B", 300, 189.50),
            add(7, OPEN - 9, 2, "B", 200, 189.49, mpid=True),
            add(7, OPEN - 8, 3, "S", 400, 189.52),
            add(8, OPEN - 8, 99, "S", 1, 410.0),  # other symbol, ignored
            execute(7, OPEN + 1, 1, 100),  # 300 → 200 at 189.50
            cancel(7, OPEN + 2, 3, 150),  # 400 → 250 at 189.52
            replace(7, OPEN + 3, 2, 4, 500, 189.51),  # 189.49 order moves to 189.51
            delete(7, OPEN + 5, 1),
        ]
    )


def test_rebuilds_book_from_itch_messages() -> None:
    r = itch.replay(io.BytesIO(_stream()), ["AAPL"], step=2)
    import json

    frames = [json.loads(x) for x in r.frames["AAPL"]]
    assert "MSFT" not in r.frames
    by_t = {f["t"]: f for f in frames}
    first = by_t[OPEN]
    assert first["b"] == [[189.5, 300], [189.49, 200]]
    assert first["a"] == [[189.52, 400]]
    later = by_t[OPEN + 4]  # after execute, cancel, replace
    assert later["b"] == [[189.51, 500], [189.5, 200]]
    assert later["a"] == [[189.52, 250]]
    after_delete = by_t[OPEN + 6]
    assert after_delete["b"] == [[189.51, 500]]
    assert frames[-1]["t"] == itch.SESSION_CLOSE


def test_rejects_non_itch_file() -> None:
    import pytest

    with pytest.raises(ValueError):
        itch.replay(io.BytesIO(_msg(b"Zgarbage")), ["AAPL"])


def test_store_serves_frame_for_clock(tmp_path: Path, monkeypatch) -> None:
    raw = tmp_path / "day.gz"
    raw.write_bytes(gzip.compress(_stream()))
    monkeypatch.setenv("US_BOOK_DIR", str(tmp_path / "out"))
    (tmp_path / "out").mkdir()
    meta = itch.build(str(raw), ["AAPL"], session="2026-05-18", out_root=tmp_path / "out", step=2)
    assert meta["symbols"]["AAPL"] > 10
    f = store.frame("AAPL", at=OPEN + 5)
    assert f and f["b"][0] == [189.51, 500] and f["session"] == "2026-05-18"
    assert store.available("aapl") and not store.available("MSFT")
    # 10:00 New York on a weekday maps to the same clock time
    ny_ten = datetime(2026, 10, 26, 14, 0, tzinfo=timezone.utc)
    assert store.replay_clock(ny_ten) == 10 * 3600
