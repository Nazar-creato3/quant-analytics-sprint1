"""Why are US quotes stale? One line per provider: key set, host reachable, real answer for AAPL.

    docker compose exec backend python -m app.scripts.us_quotes_check

Read-only. Prints no keys: only "задан / не задан".
"""
from __future__ import annotations

import asyncio
import time
from datetime import datetime, timedelta, timezone

# provider, host probed for reachability, how to obtain a key
PROVIDERS = [
    ("alpaca", "https://data.alpaca.markets", "alpaca.markets — бесплатный ключ (paper), ALPACA_API_KEY + ALPACA_SECRET_KEY"),
    ("polygon", "https://api.polygon.io", "polygon.io — бесплатно 5 запросов/мин, POLYGON_API_KEY"),
    ("twelvedata", "https://api.twelvedata.com", "twelvedata.com — бесплатно 800 запросов/день, TWELVE_DATA_API_KEY"),
    ("tiingo", "https://api.tiingo.com", "tiingo.com — бесплатно, TIINGO_API_KEY"),
    ("finnhub", "https://finnhub.io", "finnhub.io — бесплатно 60 запросов/мин, FINNHUB_API_KEY"),
    ("marketstack", "https://api.marketstack.com", "marketstack.com — бесплатно 100 запросов/мес, MARKETSTACK_API_KEY"),
    ("yfinance", "https://query1.finance.yahoo.com", "без ключа; Yahoo часто закрыт для российских IP"),
    ("stooq", "https://stooq.com", "без ключа"),
]


async def reach(url: str, proxy: str | None) -> str:
    import httpx

    t = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=8.0, proxy=proxy, follow_redirects=False) as c:
            r = await c.get(url)
        return f"HTTP {r.status_code}, {time.monotonic() - t:.1f} с"
    except httpx.TimeoutException:
        return "нет ответа (таймаут 8 с)"
    except Exception as exc:  # noqa: BLE001
        return f"{type(exc).__name__}: {str(exc)[:60]}"


def client_for(name: str):
    from app.services.market_data import client as mc
    from app.services.market_data import http_providers as hp

    return {
        "alpaca": lambda: mc.AlpacaClient(),
        "polygon": lambda: mc.PolygonClient(),
        "twelvedata": lambda: hp.TwelveDataClient(),
        "tiingo": lambda: hp.TiingoClient(),
        "finnhub": lambda: hp.FinnhubMarketClient(),
        "marketstack": lambda: hp.MarketStackClient(),
        "yfinance": lambda: mc.YFinanceClient(),
    }.get(name)


async def real_answer(name: str) -> str:
    make = client_for(name)
    if make is None:
        return "—"
    end = datetime.now(timezone.utc)
    t = time.monotonic()
    try:
        bars = await asyncio.wait_for(make().get_bars("AAPL", "1d", end - timedelta(days=14), end), timeout=25)
    except asyncio.TimeoutError:
        return "нет ответа за 25 с"
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)
        for code, hint in (("401", "ключ неверный"), ("403", "доступ запрещён (ключ/тариф/страна)"), ("429", "лимит запросов")):
            if code in msg:
                return f"ошибка {code}: {hint}"
        return f"{type(exc).__name__}: {msg[:80]}"
    if not bars:
        return "пустой ответ"
    last = bars[-1]
    ts = last.get("timestamp") if isinstance(last, dict) else getattr(last, "timestamp", "")
    close = last.get("close") if isinstance(last, dict) else getattr(last, "close", "")
    return f"OK: {len(bars)} баров, последний {str(ts)[:10]} close {close} ({time.monotonic() - t:.1f} с)"


async def db_last_bar() -> str:
    from sqlalchemy import text

    from app.db.session import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as db:
            rows = (
                await db.execute(
                    text(
                        "select timestamp, close, source from ohlcv_bars "
                        "where ticker = 'AAPL' and timeframe = '1d' order by timestamp desc limit 3"
                    )
                )
            ).all()
    except Exception as exc:  # noqa: BLE001
        return f"нет доступа к БД: {type(exc).__name__}"
    if not rows:
        return "В базе нет дневных баров AAPL"
    return "В базе, AAPL: " + "; ".join(f"{str(r[0])[:10]} close {r[1]:.2f} ({r[2]})" for r in rows)


async def main() -> None:
    from app.core.config import settings
    from app.core.http_proxy import foreign_https_proxy
    from app.services.market_data.http_providers import key_configured

    from app.core.http_proxy import configure_yfinance_proxy, redacted_proxy_status

    proxy = foreign_https_proxy()
    configure_yfinance_proxy()
    if proxy:
        st = redacted_proxy_status()
        print(f"Прокси: {st['scheme']}://{st['host']}:{st['port']}", flush=True)
    print(f"Прокси для зарубежных API (FOREIGN_HTTPS_PROXY): {'задан' if proxy else 'не задан'}", flush=True)
    print(f"Основной поставщик (MARKET_DATA_PROVIDER): {settings.MARKET_DATA_PROVIDER.value}", flush=True)
    print(await db_last_bar(), flush=True)
    print(flush=True)
    for name, host, how in PROVIDERS:
        has_key = key_configured(name)
        direct = await reach(host, None)
        via = await reach(host, proxy) if proxy else ""
        answer = await real_answer(name) if has_key else "не проверялся: нет ключа"
        print(f"{name:<11} ключ: {'задан' if has_key else 'НЕТ':<6} сеть: {direct}" + (f" | через прокси: {via}" if proxy else ""), flush=True)
        print(f"{'':<11} AAPL: {answer}", flush=True)
        if not has_key:
            print(f"{'':<11} где взять: {how}", flush=True)
    print("\nИтог: рабочий — тот, где «AAPL: OK» и свежая дата. Если у всех «нет ответа», сервер не выходит за рубеж: нужен прокси.", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
