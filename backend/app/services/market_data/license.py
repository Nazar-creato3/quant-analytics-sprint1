"""License tags for quotes. Policy file is the switch (Prompt 04 / 42)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

LicenseTag = Literal["display_allowed", "internal_only", "beta", "awaiting", "forbidden", "owner_only"]

_POLICY_PATH = Path(__file__).with_name("license_policy.json")

_SOURCE_ALIAS = {
    "yahoo_chart": "yahoo",
    "eod_local": "yahoo",
    "stooq_local": "yahoo",
    "binance": "binance_public",
    "binance_ws": "binance_public",
    "binance_rest": "binance_public",
}

ISS_DELAY_LABEL = "Источник: Московская биржа, задержка 15 минут"

_DELAY_MINUTES = {
    "iss_moex": 15,
    "yahoo": 15,
    "stooq_local": 1440,
    "eod_local": 1440,
    "binance_public": 0,
    "bybit_public": 0,
}


def load_policy() -> dict[str, LicenseTag]:
    return json.loads(_POLICY_PATH.read_text(encoding="utf-8"))


def tag_for_source(source: str) -> LicenseTag:
    policy = load_policy()
    canonical = _SOURCE_ALIAS.get(source, source)
    return policy.get(canonical, "internal_only")  # type: ignore[return-value]


def may_display(tag: LicenseTag, *, audience: Literal["owner", "public", "internal"]) -> bool:
    if tag == "owner_only":
        return False
    if tag == "display_allowed":
        return True
    if tag == "beta" and audience in {"owner", "public"}:
        return True
    if tag == "internal_only":
        return audience == "internal"
    return False


def token_owner_may_display(*, viewer_user_id: str | None, token_owner_id: str | None) -> bool:
    """Token data is shown only when the viewer is that token's owner."""
    viewer = (viewer_user_id or "").strip()
    owner = (token_owner_id or "").strip()
    if not viewer or not owner:
        return False
    return viewer == owner


def freshness_label(*, delayed: bool, delay_minutes: int, has_price: bool) -> str:
    if not has_price:
        return "нет данных"
    if delayed and delay_minutes > 0:
        return f"с задержкой {delay_minutes} минут"
    return "в реальном времени"


def quote_envelope(
    *,
    symbol: str,
    price: str | None,
    source: str,
    as_of: str,
    delayed: bool,
    audience: Literal["owner", "public", "internal"] = "internal",
    delay_minutes: int | None = None,
    viewer_user_id: str | None = None,
    token_owner_id: str | None = None,
    trusted_price: bool = True,
) -> dict:
    if not trusted_price:
        minutes = delay_minutes if delay_minutes is not None else (_DELAY_MINUTES.get(_SOURCE_ALIAS.get(source, source), 15) if delayed else 0)
        return {
            "symbol": symbol,
            "price": None,
            "source": source,
            "as_of": as_of,
            "delayed": delayed,
            "delay_minutes": minutes,
            "license_tag": "нет данных",
            "display_allowed": False,
            "freshness_label": "нет данных",
        }
    canonical = _SOURCE_ALIAS.get(source, source)
    tag = tag_for_source(source)
    minutes = delay_minutes if delay_minutes is not None else (_DELAY_MINUTES.get(canonical, 15) if delayed else 0)
    iss_delayed = canonical == "iss_moex" and delayed and minutes == 15
    if iss_delayed:
        visible = True
        shown = price
        label = ISS_DELAY_LABEL if shown is not None else "нет данных"
        tag = "display_allowed"
    elif canonical == "iss_moex":
        visible = audience == "internal"
        shown = price if visible else None
        label = freshness_label(delayed=False, delay_minutes=0, has_price=shown is not None)
        tag = "internal_only"
    elif tag == "owner_only":
        visible = audience != "public" and token_owner_may_display(
            viewer_user_id=viewer_user_id,
            token_owner_id=token_owner_id,
        )
        shown = price if visible else None
        label = freshness_label(delayed=delayed, delay_minutes=minutes, has_price=shown is not None)
    else:
        visible = may_display(tag, audience=audience)
        shown = price if visible else None
        label = freshness_label(delayed=delayed, delay_minutes=minutes, has_price=shown is not None)
    return {
        "symbol": symbol,
        "price": shown,
        "source": source,
        "as_of": as_of,
        "delayed": delayed,
        "delay_minutes": minutes,
        "license_tag": tag,
        "display_allowed": visible,
        "freshness_label": label,
    }


def stamp_quote(
    quote: dict[str, Any],
    *,
    audience: Literal["owner", "public", "internal"] = "internal",
    viewer_user_id: str | None = None,
) -> dict[str, Any]:
    """Attach license + freshness; hide price when display is not allowed."""
    out = dict(quote)
    source = str(out.get("source") or "yahoo")
    symbol = str(out.get("symbol") or out.get("ticker") or "")
    price = out.get("price")
    price_s = None if price is None else str(price)
    delayed_flag = out.get("delayed")
    canonical = _SOURCE_ALIAS.get(source, source)
    minutes = _DELAY_MINUTES.get(canonical, 15)
    if delayed_flag is None:
        delayed = minutes > 0
    else:
        delayed = bool(delayed_flag)
    owner_raw = out.get("token_owner_id")
    env = quote_envelope(
        symbol=symbol,
        price=price_s,
        source=source,
        as_of=str(out.get("as_of") or out.get("timestamp") or ""),
        delayed=delayed,
        audience=audience,
        delay_minutes=minutes if delayed else 0,
        viewer_user_id=viewer_user_id,
        token_owner_id=None if owner_raw is None else str(owner_raw),
    )
    out.update(env)
    if not env["display_allowed"]:
        out["price"] = None
        out["last"] = None
        out["close"] = None
    return out
