"""Smart order router across venues you already key. No new brokers."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from app.services.execution.scorecard import VenueCard, build_scorecards
from app.services.execution.symbol_mapping import resolve_symbol_route


@dataclass(frozen=True, slots=True)
class RoutePick:
    venue: str
    reason: str
    score: float
    fallbacks: tuple[str, ...]


def eligible_venues(ticker: str, *, keyed: Sequence[str], paper_ok: bool = True) -> list[str]:
    """Intersect symbol route with keys the user already has."""
    route = resolve_symbol_route(ticker)
    have = {str(v).lower() for v in keyed}
    out: list[str] = []
    primary = route.execution_venue
    if primary == "tinkoff" and "tinkoff" in have:
        out.append("tinkoff")
    elif primary == "binance" and "binance" in have:
        out.append("binance")
    elif primary == "tokenized_equity":
        if "tokenized_equity" in have or "bybit" in have or "mexc" in have:
            out.append("tokenized_equity")
        if "alpaca" in have:
            out.append("alpaca")
    if paper_ok and "paper" not in out:
        out.append("paper")
    # de-dupe preserve order
    seen: set[str] = set()
    uniq = []
    for v in out:
        if v not in seen:
            seen.add(v)
            uniq.append(v)
    return uniq


def pick_venue(
    ticker: str,
    *,
    keyed: Sequence[str],
    fills: Sequence[Mapping[str, Any]] = (),
    paper_ok: bool = True,
    cards: Mapping[str, VenueCard] | None = None,
) -> RoutePick:
    elig = eligible_venues(ticker, keyed=keyed, paper_ok=paper_ok)
    if not elig:
        return RoutePick("paper", "no_keyed_venue", 0.0, ())
    scorecards = cards or build_scorecards(list(fills))
    ranked: list[tuple[float, str]] = []
    for v in elig:
        card = scorecards.get(v)
        if card is None or card.n < 3:
            # unknown venue: slight preference for primary route, paper last
            base = 0.15 if v != "paper" else 0.05
        else:
            base = card.score
        ranked.append((base, v))
    ranked.sort(key=lambda x: (-x[0], 0 if x[1] != "paper" else 1))
    best_s, best = ranked[0]
    rest = tuple(v for _, v in ranked[1:])
    return RoutePick(best, "scorecard" if (scorecards.get(best) and scorecards[best].n >= 3) else "primary_or_cold", best_s, rest)
