"""Cross-sectional long-short book + absolute long-only sleeve for a retail cap."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from app.core.config import settings
from app.services.alpha.neutralization import neutralize_cs
from app.services.risk.portfolio_sizing import capped_conviction_weights


@dataclass(frozen=True, slots=True)
class BookSleeve:
    name: str
    holdings: tuple[dict[str, float | str | int], ...]
    gross: float
    net: float
    note: str


@dataclass(frozen=True, slots=True)
class DualBook:
    as_of: str
    cross_sectional: BookSleeve
    retail_long_only: BookSleeve


def _rank_score(row: Mapping[str, object]) -> float:
    for key in ("cs_score", "neutral_z", "score_21", "score_5", "score_1", "score_20", "p_beat_21", "p_beat_20"):
        v = row.get(key)
        if v is None:
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return 0.0


def _abs_score(row: Mapping[str, object]) -> float:
    for key in ("score_21", "score_5", "score_1", "score_20", "p_beat_21", "p_beat_5", "p_beat_20"):
        v = row.get(key)
        if v is None:
            continue
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return _rank_score(row)


def cross_sectional_ls(
    rows: Sequence[Mapping[str, object]],
    *,
    long_frac: float = 0.3,
    short_frac: float = 0.3,
    sectors: Sequence[str] | None = None,
    size: Sequence[float] | None = None,
    beta: Sequence[float] | None = None,
) -> BookSleeve:
    """Dollar-neutral long-short inside the universe after CS neutralization."""
    n = len(rows)
    if n < 4:
        return BookSleeve("cross_sectional", (), 0.0, 0.0, "universe_too_small")
    raw = [_rank_score(r) for r in rows]
    neu = neutralize_cs(raw, sectors=sectors, size=size, beta=beta)
    ranked = sorted(range(n), key=lambda i: neu.z[i], reverse=True)
    n_long = max(1, int(round(n * long_frac)))
    n_short = max(1, int(round(n * short_frac)))
    longs = ranked[:n_long]
    shorts = ranked[-n_short:]
    # Guard against overlap on tiny universes.
    overlap = set(longs) & set(shorts)
    shorts = [i for i in shorts if i not in overlap]
    if not longs or not shorts:
        return BookSleeve("cross_sectional", (), 0.0, 0.0, "no_ls_split")
    w_l = 0.5 / len(longs)
    w_s = -0.5 / len(shorts)
    holdings: list[dict[str, float | str | int]] = []
    for i in longs:
        holdings.append(
            {
                "symbol": str(rows[i].get("symbol") or "").upper(),
                "side": "long",
                "weight": round(w_l, 6),
                "neutral_z": round(neu.z[i], 6),
            }
        )
    for i in shorts:
        holdings.append(
            {
                "symbol": str(rows[i].get("symbol") or "").upper(),
                "side": "short",
                "weight": round(w_s, 6),
                "neutral_z": round(neu.z[i], 6),
            }
        )
    gross = sum(abs(float(h["weight"])) for h in holdings)
    net = sum(float(h["weight"]) for h in holdings)
    return BookSleeve(
        "cross_sectional",
        tuple(holdings),
        round(gross, 6),
        round(net, 6),
        "cs_neutral_long_short",
    )


def retail_long_only(
    rows: Sequence[Mapping[str, object]],
    *,
    cap_usd: float,
    min_score: float = 6.0,
) -> BookSleeve:
    """Absolute long-only: conviction weights, leftover cash, operator cap."""
    picked = [
        r
        for r in rows
        if _abs_score(r) >= min_score and str(r.get("symbol") or "").strip()
    ]
    picked.sort(key=_abs_score, reverse=True)
    n = len(picked)
    if n == 0 or cap_usd <= 0:
        return BookSleeve("retail_long_only", (), 0.0, 0.0, "empty_or_zero_cap")
    raw = []
    for r in picked:
        p = r.get("p_beat_21", r.get("p_beat_5", r.get("p_beat_20")))
        try:
            p_f = float(p) if p is not None else 0.5
        except (TypeError, ValueError):
            p_f = 0.5
        sc = max(_abs_score(r), 1.0)
        raw.append(max((p_f - 0.5), 0.0) * sc + 1e-6)
    name_frac = float(settings.MAX_POSITION_PCT) / 100.0
    expo = float(settings.MAX_PORTFOLIO_EXPOSURE_PCT) / 100.0
    weights = capped_conviction_weights(raw, name_cap_frac=name_frac)
    total = sum(weights)
    if total > expo > 0:
        scale = expo / total
        weights = [w * scale for w in weights]
    holdings = [
        {
            "symbol": str(picked[i].get("symbol") or "").upper(),
            "side": "long",
            "weight": round(weights[i], 6),
            "notional_usd": round(weights[i] * float(cap_usd), 2),
        }
        for i in range(n)
    ]
    gross = sum(float(h["weight"]) for h in holdings)
    return BookSleeve(
        "retail_long_only",
        tuple(holdings),
        round(gross, 6),
        round(gross, 6),
        "long_only_retail_cap",
    )


def dual_books(
    rows: Sequence[Mapping[str, object]],
    *,
    as_of: str,
    cap_usd: float,
    sectors: Sequence[str] | None = None,
    size: Sequence[float] | None = None,
    beta: Sequence[float] | None = None,
    long_frac: float = 0.3,
    short_frac: float = 0.3,
    min_score: float = 6.0,
) -> DualBook:
    return DualBook(
        as_of=as_of,
        cross_sectional=cross_sectional_ls(
            rows,
            long_frac=long_frac,
            short_frac=short_frac,
            sectors=sectors,
            size=size,
            beta=beta,
        ),
        retail_long_only=retail_long_only(rows, cap_usd=cap_usd, min_score=min_score),
    )


def sleeve_to_dict(s: BookSleeve) -> dict:
    return {
        "name": s.name,
        "holdings": [dict(h) for h in s.holdings],
        "gross": s.gross,
        "net": s.net,
        "note": s.note,
        "count": len(s.holdings),
    }
