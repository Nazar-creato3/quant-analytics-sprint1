"""Pre-demo check: is every data source the expert demo relies on alive and fresh?

Run on the server, inside the backend container:

    docker compose exec backend python -m app.scripts.stand_data_check
    docker compose exec backend python -m app.scripts.stand_data_check --llm   # + one tiny model call
    docker compose exec backend python -m app.scripts.stand_data_check --sync  # refresh demo prices first

Prints one line per source: OK / WARN / FAIL, the as-of date and what to do.
Read-only: it does not write to the database or the price store.
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import date, datetime, timezone
from typing import Any, Awaitable, Callable

DEMO_TICKERS = ["SBER", "LKOH", "GAZP", "YDEX", "MOEX", "LQDT", "SU26238RMFS4", "ROSN", "PLZL"]
MIN_BARS = 252  # VaR window: fewer bars and the risk page shows dashes
MAX_AGE_DAYS = 4  # weekend + one holiday

rows: list[tuple[str, str, str, str]] = []


def add(source: str, status: str, as_of: str, note: str) -> None:
    rows.append((source, status, as_of, note))


async def guard(name: str, fn: Callable[[], Awaitable[None]]) -> None:
    try:
        await fn()
    except Exception as exc:  # noqa: BLE001 — a check must never stop the others
        add(name, "FAIL", "—", f"{type(exc).__name__}: {str(exc)[:120]}")


async def check_db() -> None:
    from sqlalchemy import text

    from app.db.session import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        ver = (await db.execute(text("select version_num from alembic_version"))).scalar()
        has = (await db.execute(text("select to_regclass('public.legal_acceptances')"))).scalar()
    # Any revision from 0060 on is fine (0061_user_phone and later); a hard-coded id went stale.
    ok = bool(ver) and str(ver)[:4].isdigit() and str(ver)[:4] >= "0060" and has
    add("База данных, миграции", "OK" if ok else "FAIL", str(ver), "" if ok else "запустить deploy (alembic upgrade head)")


async def check_price_store() -> None:
    from app.services.price_history import service, store

    if not store.enabled():
        add("История цен (хранилище)", "FAIL", "—", "PRICE_HISTORY выключен: включить в .env")
        return
    import tempfile

    where = store.root()
    if str(where).startswith(tempfile.gettempdir()):
        add("История цен (хранилище)", "FAIL", str(where), "нет прав на /app/data/price_history: chown папки data на сервере, затем --sync")
        return
    today = date.today()
    bad = []
    newest: date | None = None
    for t in DEMO_TICKERS + ["IMOEX"]:
        closes = service.closes(t)
        if not closes:
            bad.append(f"{t}: нет данных")
            continue
        last_d = closes[-1][0]
        newest = max(newest or last_d, last_d)
        if len(closes) < MIN_BARS:
            bad.append(f"{t}: {len(closes)} дн. < {MIN_BARS}")
        elif (today - last_d).days > MAX_AGE_DAYS:
            bad.append(f"{t}: последняя цена {last_d}")
    status = "OK" if not bad else ("WARN" if len(bad) <= 2 else "FAIL")
    note = "; ".join(bad) if bad else f"{len(DEMO_TICKERS)} бумаг демо-портфеля, ≥{MIN_BARS} дней"
    add("История цен (хранилище)", status, str(newest or "—"), note + ("" if not bad else " → python -m app.scripts.stand_data_check --sync"))


async def check_moex_live() -> None:
    from app.services.price_history import moex

    where = await moex.locate("SBER")
    bars = await moex.history("SBER", where or {}, days=10) if where else []
    if not bars:
        add("Мосбиржа ISS (онлайн)", "FAIL", "—", "нет ответа ISS: проверить сеть сервера")
        return
    add("Мосбиржа ISS (онлайн)", "OK", str(bars[-1][0]), f"SBER, {len(bars)} торговых дней за 10 календарных")


async def check_moex_passport() -> None:
    import requests

    from app.core.http_proxy import httpx_ssl_verify
    from app.services.market_data.moex_iss_client import _moex_passport_login
    from app.services.trading_keys.platform_keys import platform_env

    user, password = platform_env("MOEX_USERNAME"), platform_env("MOEX_PASSWORD")
    if not (user and password):
        add("Мосбиржа, вход по логину", "WARN", "—", "логин не задан: данные без подписки (задержка 15 мин)")
        return
    s = requests.Session()
    s.verify = httpx_ssl_verify()
    ok = await asyncio.to_thread(_moex_passport_login, s, user, password)
    if ok and "MicexPassportCert" in s.cookies:
        add("Мосбиржа, вход по логину", "OK", "—", "passport.moex.com: вход выполнен")
    elif ok:
        add("Мосбиржа, вход по логину", "WARN", "—", "сервер ответил, но без сертификата входа: проверить логин/пароль")
    else:
        add("Мосбиржа, вход по логину", "FAIL", "—", "вход не выполнен: сертификаты (deploy-quant.sh) или логин/пароль (set-key.sh)")


async def check_fx() -> None:
    from app.services.price_history import service

    usd = service.fx_rate("USD")
    cny = service.fx_rate("CNY")
    ok = bool(usd and 50 < usd < 200)
    add("Курсы валют", "OK" if ok else "FAIL", "—", f"USD {usd}, CNY {cny}" if ok else "нет курса USD")


async def check_key_rate() -> None:
    from app.services.key_rate.service import current_key_rate

    rate = current_key_rate()
    pct = rate * 100 if rate and rate < 1 else rate
    add("Ключевая ставка ЦБ", "OK" if rate else "WARN", "data/cbr/meetings.yaml", f"{pct:.2f}%" if rate else "устарела: обновить current_rate_as_of")


async def check_futures() -> None:
    from app.services.futures_desk import service as fd

    board = await fd.board()
    if not board:
        add("Срочный рынок (FORTS)", "FAIL", "—", "пустая доска фьючерсов")
        return
    add("Срочный рынок (FORTS)", "OK", fd.freshness(board), f"{len(board)} контрактов")


async def check_moex_book() -> None:
    from app.services.orders.order_book import _fetch_moex_depth
    from app.services.trading_keys.platform_keys import tinkoff_market_data_token

    has_token = bool(tinkoff_market_data_token())
    book = await _fetch_moex_depth("SBER", levels=10)
    levels = min(len(book.bids or []), len(book.asks or []))
    if levels >= 5:
        add("Стакан Мосбиржи", "OK", str(book.source), f"SBER: {levels} уровней")
        return
    hint = (
        "вне торговой сессии стакан пуст — проверить в 10:00–18:40 МСК"
        if has_token
        else "нет токена T-Invest (бесплатный стакан): bash scripts/set-key.sh TINKOFF_API_TOKEN"
    )
    add("Стакан Мосбиржи", "WARN", str(book.source), f"SBER: уровней {levels}; {hint}")


async def check_us_book() -> None:
    from app.services.us_book_replay import store

    hit = store.latest_session()
    if not hit:
        add("Стакан США (запись Nasdaq)", "WARN", "—", "нет записи: стакан США покажет цены закрытия")
        return
    add("Стакан США (запись Nasdaq)", "OK", str(hit[1].get("session")), f"{len(hit[1].get('symbols') or {})} бумаг")


async def check_llm(call: bool) -> None:
    from app.core.config import settings
    from app.services.llm.llm_service import LLMService, llm_enabled, model_for_task

    provider = settings.LLM_PROVIDER
    model = model_for_task("inapp_chat")
    if not llm_enabled():
        add("ИИ-ассистент", "FAIL", "—", f"выключен: LLM_ENABLED / ключ ({provider})")
        return
    if not call:
        add("ИИ-ассистент", "OK", "—", f"{provider} · {model} (без вызова; --llm проверит ответ)")
        return
    out = await LLMService.complete("inapp_chat", "Ответь одним словом: работает?", max_tokens=20)
    add("ИИ-ассистент", "OK" if out.strip() else "FAIL", "—", f"{provider} · {model}: «{out.strip()[:40]}»")


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true", help="make one tiny model call (spends a few tokens)")
    ap.add_argument("--sync", action="store_true", help="first refresh price history of the demo tickers from MOEX ISS")
    args = ap.parse_args()
    if args.sync:
        from app.services.price_history.sync import sync, sync_fx

        res = await sync(DEMO_TICKERS + ["IMOEX"], force=True)
        await sync_fx(force=True)
        print("Обновление истории цен:", {k: v for k, v in res.items() if k in ("ok", "total", "failed")})
    started = datetime.now(timezone.utc)
    await guard("База данных, миграции", check_db)
    await guard("История цен (хранилище)", check_price_store)
    await guard("Мосбиржа ISS (онлайн)", check_moex_live)
    await guard("Мосбиржа, вход по логину", check_moex_passport)
    await guard("Курсы валют", check_fx)
    await guard("Ключевая ставка ЦБ", check_key_rate)
    await guard("Срочный рынок (FORTS)", check_futures)
    await guard("Стакан Мосбиржи", check_moex_book)
    await guard("Стакан США (запись Nasdaq)", check_us_book)
    await guard("ИИ-ассистент", lambda: check_llm(args.llm))
    w = max(len(r[0]) for r in rows)
    print(f"Проверка данных для демо · {started:%Y-%m-%d %H:%M} UTC\n")
    for src, st, asof, note in rows:
        print(f"{st:<5} {src:<{w}}  {asof:<22} {note}")
    fails = sum(1 for r in rows if r[1] == "FAIL")
    print(f"\nИтог: {'всё готово' if not fails else f'{fails} проблем(ы) — см. FAIL'}")
    raise SystemExit(1 if fails else 0)


if __name__ == "__main__":
    asyncio.run(main())
