"""Does our MOEX account get real-time data and the order book? One answer per question.

    docker compose ... exec backend python -m app.scripts.moex_book_check
    docker compose ... exec backend python -m app.scripts.moex_book_check --ticker GAZP

Run during the trading session (10:00–18:40 MSK): outside it the order book is empty for
everyone. Read-only; prints no credentials.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone, timedelta

MSK = timezone(timedelta(hours=3))
MD_URL = "https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities/{t}.json"
OB_URL = "https://iss.moex.com/iss/engines/stock/markets/shares/boards/TQBR/securities/{t}/orderbook.json"


def main() -> None:
    from app.services.market_data.moex_iss_client import build_requests_session
    from app.services.trading_keys.platform_keys import platform_env, tinkoff_market_data_token

    ap = argparse.ArgumentParser()
    ap.add_argument("--ticker", default="SBER")
    t = ap.parse_args().ticker.upper()
    now = datetime.now(MSK)
    print(f"Сейчас {now:%H:%M} МСК. Стакан бывает только в торговую сессию (10:00–18:40, вечерняя до 23:50).", flush=True)

    has_login = bool(platform_env("MOEX_USERNAME") and platform_env("MOEX_PASSWORD"))
    s = build_requests_session()
    cert = "MicexPassportCert" in s.cookies
    print(f"1. Логин Мосбиржи: {'задан' if has_login else 'НЕ задан'}; вход {'выполнен' if cert else 'НЕ выполнен'}", flush=True)

    r = s.get(MD_URL.format(t=t), params={"iss.meta": "off", "iss.only": "marketdata"}, timeout=20)
    md = r.json().get("marketdata", {}) if r.ok else {}
    cols, rows = md.get("columns") or [], md.get("data") or []
    if rows:
        row = dict(zip(cols, rows[0]))
        upd = str(row.get("UPDATETIME") or "")
        sys_t = str(row.get("SYSTIME") or "")
        lag_note = ""
        try:
            upd_dt = datetime.strptime(f"{now:%Y-%m-%d} {upd}", "%Y-%m-%d %H:%M:%S").replace(tzinfo=MSK)
            lag = (now - upd_dt).total_seconds() / 60
            lag_note = f", отставание {lag:.0f} мин"
            realtime = lag < 5
        except ValueError:
            realtime = None
        print(f"2. Котировка {t}: последняя {row.get('LAST')}, время {upd}{lag_note} (системное {sys_t})", flush=True)
        if realtime is True:
            print("   → данные без задержки: подписка на реальное время есть", flush=True)
        elif realtime is False:
            print("   → задержка ~15 мин: у учётной записи нет подписки на реальное время (или биржа закрыта)", flush=True)
    else:
        print(f"2. Котировка {t}: нет данных (HTTP {r.status_code})", flush=True)

    r = s.get(OB_URL.format(t=t), params={"iss.meta": "off"}, timeout=20)
    if "html" in (r.headers.get("content-type") or "").lower():
        print("3. Стакан ISS: биржа ответила страницей входа — подписки на стакан нет", flush=True)
    else:
        ob = r.json().get("orderbook", {}) if r.ok else {}
        n = len(ob.get("data") or [])
        if n:
            print(f"3. Стакан ISS: OK, {n} строк (заявки на покупку и продажу)", flush=True)
        else:
            print(f"3. Стакан ISS: пустой (HTTP {r.status_code}). В сессию это значит — у учётной записи нет "
                  "подписки на стакан; вне сессии пустой у всех.", flush=True)

    print(f"4. Токен T-Invest (бесплатный стакан до 50 уровней): {'задан' if tinkoff_market_data_token() else 'НЕ задан'}", flush=True)


if __name__ == "__main__":
    main()
