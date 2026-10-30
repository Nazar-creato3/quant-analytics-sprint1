"""Map live FMP / news snapshots into forecast extras (0 if a field is missing)."""
from __future__ import annotations

import math
from typing import Any


def fundamentals_to_extras(raw: dict[str, Any] | None) -> dict[str, float]:
    if not raw:
        return {"fund_present": 0.0}
    pe = _f(raw.get("pe_ratio"))
    mcap = _f(raw.get("market_cap"))
    extras = {
        "fmp_pe_inv": (1.0 / pe) if pe and pe > 0 else 0.0,
        "fmp_roe": _f(raw.get("roe")),
        "fmp_roa": _f(raw.get("roa")),
        "fmp_de": _f(raw.get("debt_to_equity")),
        "fmp_cr": _f(raw.get("current_ratio")),
        "fmp_margin": _f(raw.get("profit_margin")),
        "fmp_beta": _f(raw.get("beta")),
        "fmp_div": _f(raw.get("dividend_yield")),
        "fmp_log_mcap": math.log(mcap) if mcap and mcap > 0 else 0.0,
        "fund_present": 0.0,
    }
    extras["fund_present"] = 1.0 if any(abs(v) > 1e-12 for k, v in extras.items() if k != "fund_present") else 0.0
    from app.services.pit.fundamentals import style_scores

    extras.update({f"style_{k}": v for k, v in style_scores(extras).items()})
    return extras


def _sec_candidate(symbol: str) -> bool:
    """SEC filings exist only for US issuers: skip MOEX, crypto and FX symbols."""
    try:
        from app.services.market_data.binance_spot import is_crypto_ticker
        from app.services.market_data.moex_spot import is_moex_ticker

        return not (is_moex_ticker(symbol) or is_crypto_ticker(symbol) or "=" in symbol)
    except Exception:
        return True


async def collect_symbol_extras(symbol: str) -> dict[str, float]:
    """FMP snapshot + dormant C slots. C vendors are not called from here."""
    extras = {"fund_present": 0.0}
    try:
        from app.services.market_data.fmp_provider import fetch_fmp_fundamentals

        raw = await fetch_fmp_fundamentals(symbol)
        extras = fundamentals_to_extras(raw)
    except Exception:
        extras = {"fund_present": 0.0}
    if extras.get("fund_present", 0.0) < 0.5 and _sec_candidate(symbol):
        try:
            from app.services.fundamental_data.native_sec_finra import NativeSecFinraProvider

            facts = await NativeSecFinraProvider().get_company_facts(symbol)
            sec_raw = {
                "pe_ratio": None,
                "market_cap": None,
                "roe": facts.get("roe"),
                "roa": None,
                "debt_to_equity": None,
                "current_ratio": None,
                "profit_margin": facts.get("profit_margin"),
                "beta": None,
                "dividend_yield": None,
            }
            extras = fundamentals_to_extras(sec_raw)
        except Exception:
            pass
    from app.services.forecast.tier_c_collect import collect_tier_c_extras

    extras.update(collect_tier_c_extras(symbol))
    try:
        from app.services.forecast.pit_snapshots import persist_pit_snapshot

        persist_pit_snapshot(symbol, extras)
    except Exception:
        pass
    try:
        from app.services.forecast.asof_store import persist_asof

        persist_asof(symbol, extras)
    except Exception:
        pass
    return extras


def _f(value: Any) -> float:
    try:
        if value is None:
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0
