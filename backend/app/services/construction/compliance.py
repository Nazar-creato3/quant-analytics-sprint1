"""Pre-trade compliance — free rules, not a vendor restricted-list feed."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True, slots=True)
class Breach:
    symbol: str
    rule: str
    detail: str


def screen(
    symbols: Sequence[str],
    *,
    restricted: Sequence[str] = (),
    adv: Sequence[float] = (),
    min_adv_usd: float = 0.0,
    countries: Sequence[str] = (),
    blocked_countries: Sequence[str] = (),
    long_only: bool = True,
    weights: Sequence[float] = (),
) -> tuple[list[bool], list[Breach]]:
    blocked = {str(x).upper() for x in restricted}
    geo = {str(x).upper() for x in blocked_countries}
    ok: list[bool] = []
    hits: list[Breach] = []
    for i, raw in enumerate(symbols):
        sym = str(raw).upper()
        allow = True
        if sym in blocked:
            allow = False
            hits.append(Breach(sym, "restricted", "operator restricted list"))
        if min_adv_usd > 0 and i < len(adv) and 0 < float(adv[i]) < min_adv_usd:
            allow = False
            hits.append(Breach(sym, "min_adv", f"adv {adv[i]:.0f} < {min_adv_usd:.0f}"))
        if i < len(countries) and str(countries[i] or "").upper() in geo:
            allow = False
            hits.append(Breach(sym, "country_block", str(countries[i])))
        if long_only and i < len(weights) and float(weights[i]) < -1e-12:
            allow = False
            hits.append(Breach(sym, "long_only", "short not allowed"))
        ok.append(allow)
    return ok, hits
