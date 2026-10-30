"""Map local FRED / Fama–French / Eurostat-style snapshots to a desk tilt.

QuantConnect datasets (Brain, Spectral, Benzinga, Quiver, …) live on LEAN.
Here we use the same *ideas* on data the VPS already caches: FRED, FF daily, ESI if present.
"""
from __future__ import annotations

from typing import Any


def _clip(x: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _mid(value: float | None, *, center: float, scale: float, invert: bool = False) -> float | None:
    if value is None or scale <= 0:
        return None
    z = (float(value) - center) / scale
    if invert:
        z = -z
    return _clip(z)


def fred_tilt(obs: dict[str, float]) -> tuple[float, dict[str, float]]:
    """Risk-on/off from levels. UNRATE high, VIX high, HY OAS high → risk-off."""
    parts: list[float] = []
    tagged: dict[str, float] = {}
    mapping = (
        ("UNRATE", _mid(obs.get("UNRATE"), center=5.0, scale=2.0, invert=True)),
        ("VIXCLS", _mid(obs.get("VIXCLS"), center=18.0, scale=10.0, invert=True)),
        ("BAMLH0A0HYM2", _mid(obs.get("BAMLH0A0HYM2"), center=4.0, scale=3.0, invert=True)),
        ("T10Y2Y", _mid(obs.get("T10Y2Y"), center=0.0, scale=1.0)),
        ("FEDFUNDS", _mid(obs.get("FEDFUNDS"), center=3.0, scale=3.0, invert=True)),
    )
    for name, val in mapping:
        if val is None:
            continue
        parts.append(val)
        tagged[name] = round(val, 4)
    if not parts:
        return 0.0, tagged
    tilt = sum(parts) / len(parts)
    return round(_clip(tilt), 4), tagged


def fama_french_tilt(row: dict[str, Any] | None) -> tuple[float, dict[str, float]]:
    if not isinstance(row, dict):
        return 0.0, {}
    def _g(*keys: str) -> float | None:
        for k in keys:
            if k in row and row[k] is not None:
                try:
                    return float(row[k])
                except (TypeError, ValueError):
                    continue
        return None
    mkt = _g("Mkt-RF", "Mkt_RF", "mkt-rf")
    mom = _g("Mom", "Mom   ", "momentum")
    hml = _g("HML", "hml")
    parts = []
    tagged: dict[str, float] = {}
    if mkt is not None:
        tagged["mkt_rf"] = mkt
        parts.append(_clip(mkt / 1.5))
    if mom is not None:
        tagged["mom"] = mom
        parts.append(_clip(mom / 1.5))
    if hml is not None:
        tagged["hml"] = hml
        parts.append(_clip(hml / 1.5) * 0.5)
    if not parts:
        return 0.0, tagged
    return round(_clip(sum(parts) / len(parts)), 4), tagged


def esi_tilt(consumer: float | None, industry: float | None, services: float | None) -> float:
    vals = [v for v in (consumer, industry, services) if v is not None]
    if not vals:
        return 0.0
    # ESI balances are typically around 0; ±20 is a strong swing.
    return round(_clip(sum(vals) / len(vals) / 20.0), 4)


def blend_macro(*tilts: float, weights: list[float] | None = None) -> float:
    xs = [float(t) for t in tilts]
    if not xs:
        return 0.0
    w = weights if weights and len(weights) == len(xs) else [1.0] * len(xs)
    s = sum(w) or 1.0
    return round(_clip(sum(a * b for a, b in zip(xs, w)) / s), 4)


def load_local_alt_macro() -> dict[str, Any]:
    """Read FRED cache + FF_DAILY_FACTORS. Missing files → zeros, never crash the pipeline."""
    from app.services.market_data.fred_bulk_store import latest_observation_as_of, bulk_root
    import json

    ids = ("UNRATE", "VIXCLS", "BAMLH0A0HYM2", "T10Y2Y", "FEDFUNDS", "CPIAUCSL", "PAYEMS", "PPIFIS", "DFII10")
    obs: dict[str, float] = {}
    for sid in ids:
        row = latest_observation_as_of(sid)
        if row and row.get("value") is not None:
            obs[sid] = float(row["value"])
    fred, fred_parts = fred_tilt(obs)
    ff_row = None
    try:
        path = bulk_root() / "current" / "FF_DAILY_FACTORS.json"
        if path.is_file():
            payload = json.loads(path.read_text(encoding="utf-8"))
            rows = payload.get("rows") or []
            if rows:
                ff_row = rows[-1]
    except Exception:
        ff_row = None
    ff, ff_parts = fama_french_tilt(ff_row)
    esi_c = esi_i = None
    cftc_share = None
    pub: dict[str, Any] = {}
    try:
        from app.services.quant_desk.public_alt import load_public_alt_cache

        pub = load_public_alt_cache() or {}
        if pub.get("esi_consumer") is not None:
            esi_c = float(pub["esi_consumer"])
        if pub.get("esi_industry") is not None:
            esi_i = float(pub["esi_industry"])
        if pub.get("cftc_es_lev_net_share") is not None:
            cftc_share = float(pub["cftc_es_lev_net_share"])
    except Exception:
        pub = {}
    esi = esi_tilt(esi_c, esi_i, None)
    cftc_t = round(max(-1.0, min(1.0, cftc_share * 2.0)), 4) if cftc_share is not None else 0.0

    def _opt(name: str) -> float | None:
        val = pub.get(name)
        if val is None:
            return None
        try:
            return float(val)
        except (TypeError, ValueError):
            return None

    brain_t = _opt("brain_tilt")
    bz_t = _opt("benzinga_tilt")
    qv_t = _opt("quiver_tilt")
    ms_t = _opt("morningstar_tilt")
    sp_t = _opt("spectral_tilt")
    pairs: list[tuple[float, float]] = [
        (fred, 0.40),
        (ff, 0.15),
        (esi, 0.10),
        (cftc_t, 0.08),
    ]
    for val, w in (
        (brain_t, 0.10),
        (bz_t, 0.07),
        (qv_t, 0.05),
        (ms_t, 0.05),
        (sp_t, 0.05),
    ):
        if val is not None:
            pairs.append((val, w))
    combined = blend_macro(*[p[0] for p in pairs], weights=[p[1] for p in pairs])
    return {
        "tilt": combined,
        "fred_tilt": fred,
        "ff_tilt": ff,
        "esi_tilt": esi,
        "cftc_tilt": cftc_t,
        "brain_tilt": brain_t,
        "benzinga_tilt": bz_t,
        "quiver_tilt": qv_t,
        "morningstar_tilt": ms_t,
        "spectral_tilt": sp_t,
        "fred_parts": fred_parts,
        "ff_parts": ff_parts,
        "obs": obs,
        "ff_as_of": (ff_row or {}).get("date"),
        "esi_consumer": esi_c,
        "esi_industry": esi_i,
        "cftc_es_lev_net_share": cftc_share,
    }
