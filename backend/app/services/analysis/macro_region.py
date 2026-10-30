"""Region-aware macro snippets for chat / analysis (US vs RU vs CA vs global)."""
from __future__ import annotations

from app.services.market_data.moex_spot import is_moex_ticker
from app.services.market_data.binance_spot import is_crypto_ticker


def macro_region_for_symbol(symbol: str) -> str:
    s = (symbol or "").strip().upper()
    if is_moex_ticker(s):
        return "ru"
    if is_crypto_ticker(s):
        return "global"
    if s.endswith(".TO") or s in {"CAD", "USDCAD"}:
        return "ca"
    return "us"


def format_macro_snippet_for_symbol(
    symbol: str,
    indicators: dict[str, float],
    *,
    stale_reason: str = "",
) -> str:
    """Build macro text using rates/unemployment matched to the ticker's primary market."""
    if not indicators:
        return ""

    region = macro_region_for_symbol(symbol)
    parts: list[str] = []

    vix = indicators.get("vix")
    if vix is not None:
        parts.append(f"VIX {vix:.1f}")

    if region == "ru":
        cpi = indicators.get("cpi")
        if cpi is not None:
            parts.append(f"инфляция (CPI) {cpi:.1f}%")
        rate = indicators.get("rate_cb")
        if rate is not None:
            parts.append(f"ключевая ставка ЦБ РФ {rate:.2f}%")
        oil = indicators.get("oil_brent")
        if oil is not None:
            parts.append(f"Brent {oil:.1f}")
    elif region == "ca":
        cpi = indicators.get("cpi_ca") or indicators.get("cpi")
        if cpi is not None:
            parts.append(f"инфляция Канады {cpi:.1f}%")
        rate = indicators.get("rate_cb_ca")
        if rate is not None:
            parts.append(f"ключевая ставка BoC {rate:.2f}%")
        unemp = indicators.get("unemployment_ca")
        if unemp is not None:
            parts.append(f"безработица Канады {unemp:.1f}%")
        usdcad = indicators.get("usdcad")
        if usdcad is not None:
            parts.append(f"USDCAD {usdcad:.4f}")
    else:
        cpi = indicators.get("cpi")
        if cpi is not None:
            parts.append(f"инфляция США (CPI) {cpi:.1f}%")
        rate = indicators.get("rate_cb_us")
        if rate is None and indicators.get("rate_cb") is not None:
            # Legacy rows stored only rate_cb — do not label CBR rate as Fed.
            pass
        elif rate is not None:
            parts.append(f"ключевая ставка ФРС {rate:.2f}%")
        unemp = indicators.get("unemployment")
        if unemp is not None:
            parts.append(f"безработица США {unemp:.1f}%")
        dxy = indicators.get("dxy")
        if dxy is not None:
            parts.append(f"индекс USD (DXY) {dxy:.2f}")
        gdp = indicators.get("wb_us_gdp_growth")
        if gdp is not None:
            parts.append(f"рост ВВП США {gdp:.1f}%")

    spread = indicators.get("credit_spread")
    if spread is not None:
        parts.append(f"кредитный спред HY {spread * 100:.0f} б.п.")
    elif indicators.get("hy_oas") is not None:
        parts.append(f"HY OAS {indicators['hy_oas']:.0f} б.п.")

    oil = indicators.get("oil_brent")
    if oil is not None and region != "ru":
        parts.append(f"Brent {oil:.1f}")

    eu_gdp = indicators.get("eu_gdp_yoy")
    if eu_gdp is not None and region == "global":
        parts.append(f"рост ВВП еврозоны {eu_gdp:.1f}%")

    if not parts:
        return ""

    label = {
        "ru": "Макро-фон (РФ)",
        "ca": "Макро-фон (Канада)",
        "us": "Макро-фон (США)",
        "global": "Макро-фон (глобальный)",
    }.get(region, "Макро-фон")
    snippet = f"{label}: " + "; ".join(parts) + "."
    if stale_reason:
        snippet += f" (часть данных устарела: {stale_reason})"
    return snippet
