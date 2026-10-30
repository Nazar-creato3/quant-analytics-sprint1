"""Rebuild Nasdaq order books from a TotalView-ITCH 5.0 session file.

Nasdaq publishes full-day ITCH 5.0 recordings on its public server
(https://emi.nasdaq.com/ITCH/Nasdaq%20ITCH/). Each file is every order event of
one trading day on Nasdaq: add, cancel, delete, execute, replace. Replaying them
gives the real order book at any moment of that day.

We stream the gzip file once (no 30 GB on disk), keep the live orders of a few
tracked symbols only, and write a 10-level snapshot every ``step`` seconds of the
regular session (09:30–16:00 New York). Output per symbol, one JSON line per
snapshot::

    {"t": 34200, "b": [[189.52, 300], ...], "a": [[189.54, 200], ...]}

``t`` is seconds since midnight, New York time. Prices in dollars, sizes in shares.

Spec: Nasdaq TotalView-ITCH 5.0 (all integers big-endian, prices ×10 000,
timestamps in nanoseconds since midnight). In the file every message is
prefixed by a 2-byte big-endian length.
"""
from __future__ import annotations

import gzip
import json
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import BinaryIO, Iterable

SESSION_OPEN = 9 * 3600 + 30 * 60
SESSION_CLOSE = 16 * 3600
LEVELS = 10

_H = struct.Struct(">H")
_LOC = struct.Struct(">H")
_ADD = struct.Struct(">HH6sQcI8sI")  # locate, tracking, ts, ref, side, shares, stock, price
_EXE = struct.Struct(">HH6sQI")  # locate, tracking, ts, ref, shares (E: + match; C: + match, printable, price)
_DEL = struct.Struct(">HH6sQ")  # D
_REP = struct.Struct(">HH6sQQII")  # U: locate, tracking, ts, old ref, new ref, shares, price
_DIR = struct.Struct(">HH6s8s")  # R (first fields): locate, tracking, ts, stock
_BOOK_TYPES = frozenset(b"AFECXDU")


def _ts(raw: bytes) -> int:
    return int.from_bytes(raw, "big")


@dataclass
class Book:
    bids: dict[int, int] = field(default_factory=dict)
    asks: dict[int, int] = field(default_factory=dict)

    def add(self, side: bytes, price: int, shares: int) -> None:
        lvl = self.bids if side == b"B" else self.asks
        lvl[price] = lvl.get(price, 0) + shares

    def take(self, side: bytes, price: int, shares: int) -> None:
        lvl = self.bids if side == b"B" else self.asks
        left = lvl.get(price, 0) - shares
        if left > 0:
            lvl[price] = left
        else:
            lvl.pop(price, None)

    def top(self, n: int = LEVELS) -> tuple[list[list[float]], list[list[float]]]:
        bids = sorted(self.bids.items(), key=lambda kv: -kv[0])[:n]
        asks = sorted(self.asks.items(), key=lambda kv: kv[0])[:n]
        return [[p / 10_000, s] for p, s in bids], [[p / 10_000, s] for p, s in asks]


class Replayer:
    """Feed raw ITCH messages (without the length prefix); collect snapshots."""

    def __init__(self, symbols: Iterable[str], *, step: int = 2) -> None:
        self.wanted = {s.strip().upper() for s in symbols if s.strip()}
        self.step = max(1, int(step))
        self.locate: dict[int, str] = {}
        self.books: dict[int, Book] = {}
        # ref -> (locate, side, price, shares)
        self.orders: dict[int, list] = {}
        self.next_snap = SESSION_OPEN
        self.frames: dict[str, list[str]] = {s: [] for s in self.wanted}
        self.messages = 0
        self.seen_system = False

    # ---- snapshots -----------------------------------------------------------
    def _snapshot_until(self, sec: int) -> None:
        while self.next_snap <= sec and self.next_snap <= SESSION_CLOSE:
            for loc, book in self.books.items():
                b, a = book.top()
                if b or a:
                    # Kept as compact JSON text: a day of 2-second frames for a dozen
                    # symbols stays ~50 MB instead of ~300 MB of Python lists.
                    self.frames[self.locate[loc]].append(json.dumps({"t": self.next_snap, "b": b, "a": a}, separators=(",", ":")))
            self.next_snap += self.step

    def finish(self) -> None:
        self._snapshot_until(SESSION_CLOSE)

    # ---- messages ------------------------------------------------------------
    def feed(self, msg: bytes | memoryview) -> None:
        self.messages += 1
        kind = msg[0]  # int
        if kind == 83:  # S
            self.seen_system = True
            return
        if kind == 82:  # R stock directory
            loc, _tr, _t, stock = _DIR.unpack_from(msg, 1)
            sym = stock.decode("ascii", "replace").strip().upper()
            if sym in self.wanted:
                self.locate[loc] = sym
                self.books[loc] = Book()
            return
        if kind not in _BOOK_TYPES:
            return
        (loc,) = _LOC.unpack_from(msg, 1)
        if loc not in self.books:
            return
        if kind == 65 or kind == 70:  # A, F
            _l, _tr, t, ref, side, shares, _stock, price = _ADD.unpack_from(msg, 1)
            self._clock(t)
            self.orders[ref] = [loc, side, price, shares]
            self.books[loc].add(side, price, shares)
        elif kind == 69 or kind == 67 or kind == 88:  # E, C, X
            _l, _tr, t, ref, shares = _EXE.unpack_from(msg, 1)
            self._clock(t)
            self._reduce(ref, shares)
        elif kind == 68:  # D
            _l, _tr, t, ref = _DEL.unpack_from(msg, 1)
            self._clock(t)
            o = self.orders.pop(ref, None)
            if o:
                self.books[o[0]].take(o[1], o[2], o[3])
        else:  # U
            _l, _tr, t, old, new, shares, price = _REP.unpack_from(msg, 1)
            self._clock(t)
            o = self.orders.pop(old, None)
            if o:
                self.books[o[0]].take(o[1], o[2], o[3])
                self.orders[new] = [o[0], o[1], price, shares]
                self.books[o[0]].add(o[1], price, shares)

    def _clock(self, raw_ts: bytes) -> None:
        sec = _ts(raw_ts) // 1_000_000_000
        if sec >= self.next_snap:
            self._snapshot_until(sec)

    def _reduce(self, ref: int, shares: int) -> None:
        o = self.orders.get(ref)
        if not o:
            return
        take = min(shares, o[3])
        self.books[o[0]].take(o[1], o[2], take)
        o[3] -= take
        if o[3] <= 0:
            self.orders.pop(ref, None)


def iter_messages(stream: BinaryIO, chunk: int = 1 << 22) -> Iterable[memoryview]:
    """Split a length-prefixed ITCH byte stream into messages."""
    buf = b""
    while True:
        data = stream.read(chunk)
        if not data:
            break
        buf = buf + data if buf else data
        view = memoryview(buf)
        pos = 0
        end = len(buf)
        while pos + 2 <= end:
            (n,) = _H.unpack_from(view, pos)
            if pos + 2 + n > end:
                break
            yield view[pos + 2 : pos + 2 + n]
            pos += 2 + n
        buf = bytes(view[pos:])


def replay(stream: BinaryIO, symbols: Iterable[str], *, step: int = 2, stop_after_close: bool = True) -> Replayer:
    r = Replayer(symbols, step=step)
    first = True
    for msg in iter_messages(stream):
        if first:
            first = False
            if msg[0] not in b"SRHLVWKJh":
                raise ValueError("this file is not a TotalView-ITCH 5.0 stream (unexpected first message)")
        r.feed(msg)
        if r.messages % 50_000_000 == 0:
            print(f"… {r.messages // 1_000_000} млн сообщений, торговое время {r.next_snap // 3600:02d}:{r.next_snap % 3600 // 60:02d}", flush=True)
        if stop_after_close and r.next_snap > SESSION_CLOSE:
            break
    r.finish()
    return r


def open_source(src: str) -> BinaryIO:
    """Local path (``.gz`` or raw) or an http(s) URL streamed and gunzipped on the fly."""
    if src.startswith(("http://", "https://")):
        import os

        import requests

        try:  # direct first; the foreign proxy only if Nasdaq is not reachable from the server
            resp = requests.get(src, stream=True, timeout=(15, 120))
            resp.raise_for_status()
        except requests.RequestException:
            proxy = os.environ.get("FOREIGN_HTTPS_PROXY", "").strip()
            if not proxy:
                raise
            resp = requests.get(src, stream=True, timeout=(15, 120), proxies={"http": proxy, "https": proxy})
            resp.raise_for_status()
        resp.raw.decode_content = False
        raw: BinaryIO = resp.raw  # type: ignore[assignment]
        return gzip.GzipFile(fileobj=raw) if src.endswith(".gz") else raw
    path = Path(src)
    return gzip.open(path, "rb") if path.suffix == ".gz" else open(path, "rb")


def write_frames(r: Replayer, out_dir: Path, *, session: str, source: str) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = {}
    for sym, frames in r.frames.items():
        if not frames:
            continue
        with gzip.open(out_dir / f"{sym}.jsonl.gz", "wt", encoding="utf-8") as fh:
            for f in frames:
                fh.write(f + "\n")
        written[sym] = len(frames)
    meta = {"session": session, "source": source, "step": r.step, "symbols": written, "messages": r.messages}
    (out_dir / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    return meta


def build(src: str, symbols: Iterable[str], *, session: str, out_root: Path, step: int = 2) -> dict:
    with open_source(src) as stream:
        r = replay(stream, symbols, step=step)
    if not r.seen_system and not r.locate:
        raise ValueError("no ITCH system or stock directory messages found")
    return write_frames(r, out_root / session, session=session, source=src)
