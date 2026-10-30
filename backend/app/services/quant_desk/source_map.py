"""QuantConnect dataset catalog → what we actually run on this stack.

QC/LEAN datasets are not a dumpable warehouse. Practical use is: same *signal*,
public or already-licensed source, point-in-time as-of at digest time (not tick replay).
"""
from __future__ import annotations

from typing import Any

# status: wired | public_fetch | already | licensed_key | proprietary_skip
QC_TO_OURS: list[dict[str, Any]] = [
    {
        "qc": "Eurostat BCS / ESI",
        "problem": "LEAN zip + map files, not our REST cache",
        "ours": "Eurostat JSON-stat ei_bsco_m / ei_bsin_m (free)",
        "status": "public_fetch",
        "use": "ESI consumer/industry → desk tilt, nightly",
    },
    {
        "qc": "FRED + BLS",
        "problem": "QC redistributes FRED as LEAN files",
        "ours": "fred_bulk_store + extra series T10Y2Y/PAYEMS/PPIFIS/JTSJOL",
        "status": "wired",
        "use": "risk-on/off tilt from UNRATE, VIX, HY OAS, curve",
    },
    {
        "qc": "Fama–French daily",
        "problem": "QC computes from *their* US fundamentals PIT",
        "ours": "Ken French library via pandas_datareader (FF_DAILY_FACTORS)",
        "status": "wired",
        "use": "Mkt-RF / Mom / HML last row → equity factor tilt",
    },
    {
        "qc": "FINRA short + SEC EDGAR",
        "problem": "QC Security Master + FINRA tape is US-equity-only, LEAN maps",
        "ours": "NativeSecFinraProvider (EDGAR + FINRA REST)",
        "status": "already",
        "use": "per-ticker short squeeze / filings — not nightly universe dump",
    },
    {
        "qc": "CFTC COT",
        "problem": "QC weekly files keyed by LEAN future symbols",
        "ours": "CFTC Socrata publicreporting (TFF E-mini S&P)",
        "status": "public_fetch",
        "use": "leveraged-money net / OI → risk-on tilt",
    },
    {
        "qc": "VIX contango",
        "problem": "needs *their* VX continuous futures",
        "ours": "VIXCLS level + VXX daily % in digest (proxy, not term structure)",
        "status": "wired",
        "use": "fear proxy until we own a VX curve",
    },
    {
        "qc": "Tiingo news / Benzinga",
        "problem": "vendor license — not a QC zip",
        "ours": "QUANTCONNECT_DATA_DIR benzinga CSV, else BENZINGA_API_KEY",
        "status": "licensed_key",
        "use": "LEAN dump first; HTTP fills gaps",
    },
    {
        "qc": "Brain ML / language / sentiment",
        "problem": "Brain delivers S3/SFTP/custom REST, not LEAN files",
        "ours": "LEAN alternative/brain/*.csv or BRAIN_BSI.json / Brain REST",
        "status": "licensed_key",
        "use": "sentiment_7d on SPY/universe mean → desk tilt",
    },
    {
        "qc": "Quiver Congress / lobbying",
        "problem": "Quiver REST, not QC redistribution",
        "ours": "LEAN quiver/congresstrading CSV or QUIVER_API_KEY",
        "status": "licensed_key",
        "use": "congress flow tilt in digest",
    },
    {
        "qc": "Morningstar fundamentals",
        "problem": "enterprise URL varies by contract",
        "ours": "FMP free via FundamentalAnalysis/FinanceToolkit (MORNINGSTAR.json optional)",
        "status": "licensed_key",
        "use": "SPY PE tilt from FMP cache; Morningstar only if separately contracted",
    },
    {
        "qc": "Spectral Tick-Flow / US coarse ticks",
        "problem": "QC-computed flow; no public Spectral REST",
        "ours": "LEAN spectral daily CSV ≤8MiB or SPECTRAL_FLOW.json (ofi)",
        "status": "licensed_key",
        "use": "latest aggregate only — no tick warehouse replay",
    },
    {
        "qc": "US futures continuous",
        "problem": "LEAN map + factor files (roll rules)",
        "ours": "Stooq/Yahoo underlyings we already digest; no fake continuous",
        "status": "proprietary_skip",
        "use": "do not invent QC roll factors",
    },
]


def practical_status() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for row in QC_TO_OURS:
        out.setdefault(str(row["status"]), []).append(str(row["qc"]))
    return out
