"""Terminal data health / freshness checks — compact, actionable."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from app.core.config import settings
from app.core.http_proxy import redacted_proxy_status
from app.core.logging import get_logger
from app.services.terminal_platform.factory import get_terminal_router
from app.services.terminal_platform.types import Timeframe

logger = get_logger(__name__)

# Key tickers the Terminal Market view depends on.
_FRESHNESS_TICKERS: list[tuple[str, str]] = [
    ("SPX", "^GSPC"),
    ("NDX", "^NDX"),
    ("DJI", "^DJI"),
    ("IMOEX", "IMOEX.ME"),
    ("BTC", "BTC-USD"),
    ("GOLD", "GC=F"),
]

_OPTIONAL_KEY_PROVIDERS = frozenset(
    {
        "fred",
        "alpaca",
        "polygon",
        "twelvedata",
        "tiingo",
        "marketstack",
        "finnhub",
        "coingecko",
    }
)
_REQUIRED_KEY_PROVIDERS = frozenset({"alpha_vantage", "fmp"})

# Core Terminal path — only these raise warn/critical when truly broken.
_CORE_RUNTIME_PROVIDERS = frozenset(
    {"binance_public", "moex_iss", "yfinance", "fmp", "alpha_vantage", "cbr"}
)
# Optional / best-effort — soft rate-limit / plan / proxy issues are info only.
_OPTIONAL_RUNTIME_PROVIDERS = frozenset(
    {
        "alpaca",
        "polygon",
        "twelvedata",
        "tiingo",
        "marketstack",
        "finnhub",
        "coingecko",
        "ccxt_binance",
        "ccxt_bybit",
        "ccxt_okx",
        "fred",
        "imf",
        "world_bank",
        "rosstat",
    }
)

_STALE_SECONDS = 15 * 60  # 15 minutes


def _mask(value: Optional[str]) -> str:
    if not value:
        return "(empty)"
    v = value.strip()
    if len(v) <= 6:
        return "***"
    return f"{v[:3]}…{v[-2:]} (len={len(v)})"


def _key_status() -> dict[str, Any]:
    from app.services.market_data.http_providers import configured_provider_flags

    flags = configured_provider_flags()
    fmp = bool((settings.FMP_API_KEY or "").strip())
    av = bool((settings.ALPHA_VANTAGE_API_KEY or "").strip())
    fred = bool((settings.FRED_API_KEY or "").strip())
    return {
        "fmp": {"configured": fmp, "required": True, "hint": None if fmp else "Set FMP_API_KEY in container env"},
        "alpha_vantage": {
            "configured": av,
            "required": True,
            "hint": None if av else "Set ALPHA_VANTAGE_API_KEY in container env",
        },
        "fred": {
            "configured": fred,
            "required": False,
            "hint": None if fred else "Optional — macro FRED series; IMF/WB used as fallback",
        },
        "alpaca": {
            "configured": flags["alpaca"],
            "required": False,
            "hint": None if flags["alpaca"] else "Optional — equity quotes/bars/order book",
        },
        "polygon": {
            "configured": flags["polygon"],
            "required": False,
            "hint": None if flags["polygon"] else "Optional — equity quotes/bars/order book",
        },
        "twelvedata": {
            "configured": flags["twelvedata"],
            "required": False,
            "hint": None if flags["twelvedata"] else "Optional — TWELVEDATA_API_KEY / TWELVE_DATA_API_KEY",
        },
        "tiingo": {
            "configured": flags["tiingo"],
            "required": False,
            "hint": None if flags["tiingo"] else "Optional — TIINGO_API_KEY",
        },
        "marketstack": {
            "configured": flags["marketstack"],
            "required": False,
            "hint": None if flags["marketstack"] else "Optional — MARKETSTACK_API_KEY",
        },
        "finnhub": {
            "configured": flags["finnhub"],
            "required": False,
            "hint": None if flags["finnhub"] else "Optional — calendar + equity quotes",
        },
        "coingecko": {
            "configured": flags["coingecko"],
            "required": False,
            "hint": None if flags["coingecko"] else "Optional — COINGECKO_API_KEY (public tier works)",
        },
    }


async def run_data_health(*, reset_circuits: bool = False, refresh: bool = True) -> dict[str, Any]:
    """
    On-demand health + freshness probe.

    - Reports provider circuit / key status (never echoes full secrets)
    - Optionally resets stuck circuits (half-open recovery)
    - Optionally refreshes key ticker quotes and reports freshness
    """
    router = get_terminal_router()
    as_of = datetime.now(timezone.utc).isoformat()

    if reset_circuits:
        reset = router.reset_all_circuits()
    else:
        reset = router.reset_open_circuits(min_open_seconds=30.0)

    health = await router.providers_health()
    keys = _key_status()
    from app.utils.secret_redact import redact_secrets

    alerts: list[dict[str, str]] = []
    for name, info in keys.items():
        if info["configured"]:
            continue
        if info["required"]:
            alerts.append(
                {
                    "severity": "warn",
                    "title": f"{name} key missing",
                    "body": info["hint"] or "configure API key",
                }
            )
        else:
            alerts.append(
                {
                    "severity": "info",
                    "title": f"Optional {name} key missing",
                    "body": info["hint"] or "optional",
                }
            )

    degraded: list[str] = []
    soft_degraded: list[str] = []
    for h in health:
        # Don't cry key-missing when settings say keyed (stale provider status).
        if h.name in ("fmp", "alpha_vantage") and keys.get(h.name, {}).get("configured"):
            if h.requires_api_key and not h.api_key_configured:
                # Re-check after reload — providers_health already reloads; still flag mismatch.
                alerts.append(
                    {
                        "severity": "warn",
                        "title": f"{h.name} key not visible to provider",
                        "body": "Key in settings but provider.api_key_configured=false — rebuild container env",
                    }
                )
                continue
        st = (h.status or "").lower()
        circuit = (h.circuit_state or "").lower()
        if h.requires_api_key and not h.api_key_configured:
            continue  # already covered by keys block
        if circuit == "closed" and st in {"active", "rate_limited"}:
            continue
        if circuit == "open" or st in {"degraded", "circuit_open", "unavailable", "rate_limited"}:
            is_optional = h.name in _OPTIONAL_RUNTIME_PROVIDERS or h.name not in _CORE_RUNTIME_PROVIDERS
            err = (h.last_error or "").lower()
            soft_err = any(
                x in err
                for x in (
                    "429",
                    "too many",
                    "rate limit",
                    "400",
                    "bad request",
                    "403",
                    "forbidden",
                    "unsupported",
                    "no module named",
                    "proxy",
                    "timeout",
                    "could not connect",
                )
            )
            if is_optional or soft_err or st == "rate_limited":
                soft_degraded.append(h.name)
                # Never surface ccxt_* optional skips as user-facing alerts (missing dep / unused).
                if h.name.startswith("ccxt_"):
                    continue
                # Info only — expected off-hours / plan limits / wrong-symbol skips.
                if len([x for x in soft_degraded if not x.startswith("ccxt_")]) <= 3:
                    alerts.append(
                        {
                            "severity": "info",
                            "title": f"{h.name} soft-skip",
                            "body": "optional/rate-limit/unsupported — fallbacks cover; not an outage",
                        }
                    )
                continue
            hint = {
                "circuit_open": "auto half-open after cooldown; POST ?reset_circuits=1 to force",
                "rate_limited": "backoff — use yfinance/binance_public fallbacks",
                "degraded": "check last_error; fallbacks should cover",
                "unavailable": "provider offline or misconfigured",
            }.get(st if st != "circuit_open" else "circuit_open", "check provider")
            if circuit == "open":
                hint = "auto half-open after cooldown; POST ?reset_circuits=1 to force"
            degraded.append(h.name)
            alerts.append(
                {
                    "severity": "warn",
                    "title": f"{h.name} {circuit if circuit == 'open' else st}",
                    "body": hint,
                }
            )

    tickers: list[dict[str, Any]] = []
    stale_count = 0
    if refresh:
        from app.services.terminal_platform.market.quotes import fetch_quote_safe

        for ui, api in _FRESHNESS_TICKERS:
            preferred = None
            if ui == "BTC":
                preferred = "binance_public"
            elif ui == "IMOEX":
                preferred = "moex_iss"
            q = await fetch_quote_safe(api, preferred_provider=preferred)
            age_s: Optional[float] = None
            as_of_q = q.get("as_of")
            if as_of_q:
                try:
                    ts = datetime.fromisoformat(str(as_of_q).replace("Z", "+00:00"))
                    age_s = (datetime.now(timezone.utc) - ts).total_seconds()
                except Exception:
                    age_s = None
            is_stale = q.get("status") != "ok" or (age_s is not None and age_s > _STALE_SECONDS)
            if is_stale:
                stale_count += 1
            tickers.append(
                {
                    "symbol": ui,
                    "api_symbol": api,
                    "status": q.get("status"),
                    "price": q.get("price"),
                    "change_pct": q.get("change_pct"),
                    "provider": q.get("provider"),
                    "as_of": as_of_q,
                    "age_seconds": round(age_s, 1) if age_s is not None else None,
                    "stale": is_stale,
                    "reason": q.get("reason"),
                }
            )

        # Also probe OHLCV for BTC (chart path)
        try:
            end = datetime.now(timezone.utc)
            begin = end.replace(hour=0, minute=0, second=0, microsecond=0)
            # 4 days of hourly bars
            from datetime import timedelta

            begin = end - timedelta(days=4)
            ohlcv = await router.get_ohlcv("BTC-USD", Timeframe.H1, begin, end, use_cache=False)
            bars = ohlcv.data if ohlcv.success and isinstance(ohlcv.data, list) else []
            closes = []
            for b in bars[-32:]:
                c = getattr(b, "close", None) if not isinstance(b, dict) else b.get("close")
                try:
                    closes.append(float(c))
                except (TypeError, ValueError):
                    pass
            sinusoidal = False
            if len(closes) >= 16:
                # Detect near-perfect sine: high autocorrelation at lag ~6-8 of sin(i/4)
                import math

                mid = sum(closes) / len(closes)
                amp = max(abs(c - mid) for c in closes) or 1.0
                err = 0.0
                for i, c in enumerate(closes):
                    expected = mid + math.sin(i / 4) * min(amp, 200)
                    err += abs(c - expected)
                sinusoidal = (err / len(closes)) < (amp * 0.15) and 65000 < mid < 70000
            tickers.append(
                {
                    "symbol": "BTC_OHLCV",
                    "api_symbol": "BTC-USD",
                    "status": "ok" if ohlcv.success and bars else "no_data",
                    "provider": ohlcv.provider,
                    "bar_count": len(bars) if bars else 0,
                    "last_close": closes[-1] if closes else None,
                    "sinusoidal_mock": sinusoidal,
                    "stale": not ohlcv.success or not bars or sinusoidal,
                    "reason": None if ohlcv.success else (ohlcv.error or ohlcv.error_code),
                }
            )
            if sinusoidal:
                alerts.append(
                    {
                        "severity": "critical",
                        "title": "BTC OHLCV looks like sine mock",
                        "body": "Clear frontend mock cache; prefer binance_public provider",
                    }
                )
        except Exception as exc:
            logger.warning("btc ohlcv health probe failed", error=str(exc))
            tickers.append(
                {
                    "symbol": "BTC_OHLCV",
                    "status": "no_data",
                    "stale": True,
                    "reason": str(exc),
                }
            )

    ok_tickers = sum(1 for t in tickers if not t.get("stale"))
    overall = "ok"
    if any(a["severity"] == "critical" for a in alerts) or stale_count >= 3:
        overall = "degraded"
    elif degraded or stale_count:
        overall = "partial"
    elif soft_degraded and not degraded:
        # Optional soft-skips alone → still ok/partial-lite
        overall = "ok" if ok_tickers >= max(1, len(tickers) - 1) else "partial"

    return {
        "as_of": as_of,
        "overall": overall,
        "circuits_reset": reset,
        "egress_proxy": redacted_proxy_status(),
        "keys": keys,
        "providers": [
            {
                **h.model_dump(mode="json"),
                "last_error": redact_secrets(h.last_error),
            }
            for h in health
        ],
        "tickers": tickers,
        "fresh_count": ok_tickers,
        "stale_count": stale_count,
        "degraded_core": degraded,
        "soft_degraded": soft_degraded,
        "alerts": alerts[:12],
        "policy": {
            "no_data": "only after all providers + fallback + last-good fail",
            "never_fake_zero_pct": True,
            "optional_keys": sorted(_OPTIONAL_KEY_PROVIDERS),
            "required_keys": sorted(_REQUIRED_KEY_PROVIDERS),
            "core_runtime": sorted(_CORE_RUNTIME_PROVIDERS),
            "foreign_proxy": "FOREIGN_HTTPS_PROXY for Alpaca/Polygon/TwelveData/… only; MOEX/Binance direct",
        },
    }
