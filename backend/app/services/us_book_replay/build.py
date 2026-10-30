"""One-off: build the replayed Nasdaq books from a public ITCH 5.0 day file.

    python -m app.services.us_book_replay.build \\
        --src "https://emi.nasdaq.com/ITCH/Nasdaq%20ITCH/itch50_05_18.gz" --session 2026-05-18

Streams and gunzips on the fly (nothing large is stored), keeps only the listed
symbols, writes 10-level snapshots every --step seconds into US_BOOK_DIR.
A full day is tens of GB uncompressed: expect 30–90 minutes on a small server.
"""
from __future__ import annotations

import argparse
import time

from app.services.us_book_replay.itch import build
from app.services.us_book_replay.store import root

DEFAULT_SYMBOLS = "AAPL,MSFT,NVDA,AMZN,GOOGL,META,TSLA,AMD,NFLX,SPY,QQQ"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--src", required=True, help="URL or local path of a TotalView-ITCH 5.0 file (.gz)")
    ap.add_argument("--session", required=True, help="trading date of the file, YYYY-MM-DD")
    ap.add_argument("--symbols", default=DEFAULT_SYMBOLS)
    ap.add_argument("--step", type=int, default=2, help="seconds between snapshots")
    args = ap.parse_args()
    started = time.time()
    out = root()
    out.mkdir(parents=True, exist_ok=True)
    meta = build(args.src, args.symbols.split(","), session=args.session, out_root=out, step=args.step)
    print(f"done in {time.time() - started:.0f} s → {out / args.session}")
    print(meta)


if __name__ == "__main__":
    main()
