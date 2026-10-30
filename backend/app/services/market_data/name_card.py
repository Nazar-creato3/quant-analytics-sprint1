"""Карточка бумаги: цена, бизнес, новости, почему сторона — человеческим языком."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.logging import get_logger
from app.services.news.free_feeds import aggregate_free_news
from app.services.risk.human_copy import describe_trend

logger = get_logger(__name__)


def _short_bias(records: list[dict[str, Any]]) -> str | None:
    if not records:
        return None
    latest = records[0]
    days = latest.get("days_to_cover")
    try:
        dtc = float(days) if days is not None else None
    except (TypeError, ValueError):
        dtc = None
    if dtc is None:
        return None
    if dtc >= 5:
        return "короткие позиции раздуты: чтобы их закрыть, рынку нужно много дней торгов"
    if dtc >= 3:
        return "короткая позиция заметная, но не крайность"
    return "против бумаги стоит немного коротких позиций"


def _sma(closes: list[float], period: int) -> float | None:
    if len(closes) < period:
        return None
    window = closes[-period:]
    return sum(window) / period


def _rsi14(closes: list[float]) -> float | None:
    if len(closes) < 15:
        return None
    gains = 0.0
    losses = 0.0
    for i in range(1, 15):
        delta = closes[i] - closes[i - 1]
        if delta >= 0:
            gains += delta
        else:
            losses -= delta
    avg_gain = gains / 14.0
    avg_loss = losses / 14.0
    for i in range(15, len(closes)):
        delta = closes[i] - closes[i - 1]
        avg_gain = (avg_gain * 13 + max(delta, 0.0)) / 14.0
        avg_loss = (avg_loss * 13 + max(-delta, 0.0)) / 14.0
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def _form_label(form: str) -> str:
    mapping = {
        "10-K": "годовой отчёт",
        "10-Q": "квартальный отчёт",
        "8-K": "срочное сообщение компании",
        "6-K": "зарубежный отчёт",
        "20-F": "годовой отчёт иностранной компании",
        "4": "сделка инсайдера",
    }
    return mapping.get(form.upper(), f"документ {form}")


_SECTOR_RU: dict[str, str] = {
    "technology": "технологии",
    "financial services": "финансы",
    "financials": "финансы",
    "healthcare": "здравоохранение",
    "health care": "здравоохранение",
    "consumer cyclical": "циклическое потребление",
    "consumer defensive": "защитное потребление",
    "consumer staples": "товары первой необходимости",
    "energy": "энергетика",
    "industrials": "промышленность",
    "basic materials": "сырьё и материалы",
    "communication services": "связь и медиа",
    "utilities": "коммунальные услуги",
    "real estate": "недвижимость",
}

_INDUSTRY_RU: dict[str, str] = {
    "consumer electronics": "потребительская электроника",
    "software—infrastructure": "ПО / инфраструктура",
    "software—application": "прикладное ПО",
    "semiconductors": "полупроводники",
    "internet content & information": "интернет-контент",
    "banks—diversified": "банки (диверсифицированные)",
    "oil & gas integrated": "нефтегаз (интегрированный)",
    "auto manufacturers": "автопроизводители",
}


def _ru_label(value: str | None, table: dict[str, str]) -> str | None:
    if not value:
        return None
    key = str(value).strip().lower()
    if key in table:
        return table[key]
    # soft match: keep Latin only if no map — still Russian framing outside
    return str(value).strip()


def _looks_english(text: str) -> bool:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    latin = sum(1 for c in letters if ("a" <= c.lower() <= "z"))
    return (latin / len(letters)) > 0.55


def _ru_business_summary(summary: str, *, sector_ru: str | None, industry_ru: str | None) -> str:
    """Turn English longBusinessSummary into short Russian copy; keep brand/product names."""
    s = (summary or "").strip()
    if not s:
        return ""
    if not _looks_english(s):
        return s[:420]
    low = s.lower()
    brands: list[str] = []
    for token in (
        "iPhone",
        "Mac",
        "iPad",
        "AirPods",
        "Apple Watch",
        "Apple Vision Pro",
        "Apple TV",
        "HomePod",
        "Beats",
        "Windows",
        "Azure",
        "Office",
        "Xbox",
        "PlayStation",
        "Android",
        "Chrome",
        "YouTube",
        "AWS",
        "Tesla",
    ):
        if token.lower() in low or token in s:
            brands.append(token)
    brand_bits: list[str] = []
    seen_b: set[str] = set()
    for b in brands:
        if b not in seen_b:
            seen_b.add(b)
            brand_bits.append(b)

    head_bits = []
    if sector_ru:
        head_bits.append(f"сектор: {sector_ru}")
    if industry_ru:
        head_bits.append(f"отрасль: {industry_ru}")
    verbs = "разрабатывает, производит и продаёт"
    if "designs, manufactures, and markets" in low or "designs and manufactures" in low:
        verbs = "проектирует, производит и продаёт"
    elif "provides" in low or "offers" in low:
        verbs = "предоставляет и продаёт"
    products = "товары и услуги"
    if "smartphone" in low or "iphone" in low:
        products = "смартфоны, компьютеры, планшеты, носимую электронику и аксессуары"
    elif "software" in low:
        products = "программное обеспечение и связанные сервисы"
    elif "bank" in low or "financial" in low:
        products = "финансовые услуги"
    elif "oil" in low or "energy" in low:
        products = "энергию и связанные продукты"
    body = f"Компания {verbs} {products} по всему миру"
    if brand_bits:
        body += f" (в линейке: {', '.join(brand_bits[:8])})"
    body += "."
    lead = "; ".join(head_bits)
    if lead:
        return f"{lead}. {body}"
    return body


def _build_yf_business_read(info: dict[str, Any]) -> str:
    sector_ru = _ru_label(info.get("sector"), _SECTOR_RU)
    industry_ru = _ru_label(info.get("industry"), _INDUSTRY_RU)
    bits: list[str] = []
    if sector_ru:
        bits.append(f"сектор: {sector_ru}")
    if industry_ru:
        bits.append(f"отрасль: {industry_ru}")
    if isinstance(info.get("returnOnEquity"), (int, float)):
        bits.append(
            "отдача на капитал заметная"
            if float(info["returnOnEquity"]) > 0.12
            else "отдача на капитал умеренная"
        )
    summary = str(info.get("longBusinessSummary") or "").strip()
    if summary:
        return _ru_business_summary(summary, sector_ru=sector_ru, industry_ru=industry_ru)
    return "; ".join(bits) if bits else "профиль компании"


async def build_name_card(ticker: str, *, direction: str | None = None) -> dict[str, Any]:
    symbol = ticker.strip().upper()
    card: dict[str, Any] = {
        "ticker": symbol,
        "quote": {},
        "vs_market": None,
        "trend": None,
        "business": {},
        "business_read": None,
        "filings": [],
        "filings_read": None,
        "shorts": {"records": [], "read": None},
        "news": [],
        "why": None,
        "why_points": [],
        "horizons": None,
        "sources": [],
    }
    try:
        from app.services.market_data.client import get_latest_quote_resolved

        quote = await get_latest_quote_resolved(symbol)
        card["quote"] = {
            "price": quote.get("price"),
            "change_pct": quote.get("change_pct") or quote.get("changePercent"),
            "volume": quote.get("volume"),
            "source": quote.get("source"),
        }
        if quote.get("source"):
            card["sources"].append(str(quote["source"]))
        is_crypto = (
            symbol.endswith("-USD")
            or "/" in symbol
            or symbol in {"BTC", "ETH", "SOL", "BTCUSD", "ETHUSD"}
        )
        bench_sym = "BTC-USD" if is_crypto and symbol not in {"BTC-USD", "BTC", "BTCUSD"} else (
            "ETH-USD" if symbol in {"BTC-USD", "BTC", "BTCUSD"} else "SPY"
        )
        bench = await get_latest_quote_resolved(bench_sym)
        chg = card["quote"].get("change_pct")
        bench_chg = bench.get("change_pct") or bench.get("changePercent")
        if isinstance(chg, (int, float)) and isinstance(bench_chg, (int, float)):
            delta = chg - bench_chg
            ref = (
                "ETH" if bench_sym.startswith("ETH")
                else "BTC" if bench_sym.startswith("BTC")
                else "широким рынком"
            )
            if delta >= 0.8:
                card["vs_market"] = f"сегодня сильнее {ref} примерно на {delta:.1f} п.п."
            elif delta <= -0.8:
                card["vs_market"] = f"сегодня слабее {ref} примерно на {abs(delta):.1f} п.п."
            else:
                card["vs_market"] = f"сегодня идёт почти в ногу с {ref}"
    except Exception as exc:
        logger.debug("name_card_quote_failed", ticker=symbol, error=str(exc)[:160])

    closes: list[float] = []
    try:
        from app.services.market_data.client import get_bars_resolved

        end = datetime.now(timezone.utc)
        start = end - timedelta(days=160)
        bars = await get_bars_resolved(symbol, "1d", start, end)
        for bar in bars:
            try:
                closes.append(float(bar["close"]))
            except (KeyError, TypeError, ValueError):
                continue
        sma20 = _sma(closes, 20)
        last = closes[-1] if closes else None
        rsi = _rsi14(closes)
        if last is not None and sma20:
            if last > sma20 * 1.01:
                card["trend"] = "цена выше средней за последние недели — ход скорее вверх"
            elif last < sma20 * 0.99:
                card["trend"] = "цена ниже средней за последние недели — ход скорее вниз"
            else:
                card["trend"] = "цена ходит около своей средней — ясного тренда мало"
        features = {
            "price_vs_sma20": ((last / sma20) - 1.0) if last and sma20 else 0.0,
            "sma_cross_5_20": 1.0 if last and sma20 and last > sma20 else 0.0,
            "rsi_14": rsi if rsi is not None else 50.0,
            "volume_ratio": 1.0,
        }
        side = direction or ("long" if (card["quote"].get("change_pct") or 0) >= 0 else "short")
        card["trend_detail"] = describe_trend(features, str(side))
    except Exception as exc:
        logger.debug("name_card_bars_failed", ticker=symbol, error=str(exc)[:160])

    try:
        from app.services.fundamental_data.factory import get_fundamental_data_provider

        provider = get_fundamental_data_provider()
        filings = await provider.get_sec_filings(symbol, limit=8)
        if filings.success and filings.data:
            rows = filings.data.get("filings") or []
            card["filings"] = rows
            facts = filings.data.get("company_facts") or {}
            card["business"] = {
                "revenue": facts.get("revenue"),
                "net_income": facts.get("net_income"),
                "equity": facts.get("equity"),
                "shares_outstanding": facts.get("shares_outstanding"),
                "roe": facts.get("roe"),
                "profit_margin": facts.get("profit_margin"),
                "cik": facts.get("cik"),
            }
            roe = facts.get("roe")
            margin = facts.get("profit_margin")
            biz_bits = []
            if isinstance(roe, (int, float)):
                biz_bits.append(
                    "бизнес зарабатывает на капитал"
                    if roe > 0.12
                    else "отдача на капитал скромная"
                    if roe > 0
                    else "по последним цифрам капитал не приносит прибыли"
                )
            if isinstance(margin, (int, float)):
                biz_bits.append(
                    "маржа заметная" if margin > 0.15 else "маржа обычная или тонкая"
                )
            card["business_read"] = "; ".join(biz_bits) if biz_bits else "по открытой отчётности мало цифр"
            if rows:
                top = rows[0]
                card["filings_read"] = (
                    f"последнее: {_form_label(str(top.get('form_type') or ''))}"
                    + (f" от {top.get('filing_date')}" if top.get("filing_date") else "")
                )
            card["sources"].append("sec")
        # Soft yfinance profile when SEC facts are thin (no paid key required).
        if not card.get("business_read") or card.get("business_read") == "по открытой отчётности мало цифр":
            try:
                import asyncio
                from concurrent.futures import ThreadPoolExecutor

                def _yf_info() -> dict:
                    import yfinance as yf

                    info = yf.Ticker(symbol).info or {}
                    return {
                        "sector": info.get("sector"),
                        "industry": info.get("industry"),
                        "longBusinessSummary": (info.get("longBusinessSummary") or "")[:420],
                        "trailingPE": info.get("trailingPE"),
                        "profitMargins": info.get("profitMargins"),
                        "returnOnEquity": info.get("returnOnEquity"),
                        "marketCap": info.get("marketCap"),
                    }

                loop = asyncio.get_running_loop()
                with ThreadPoolExecutor(max_workers=1) as pool:
                    info = await asyncio.wait_for(loop.run_in_executor(pool, _yf_info), timeout=6.0)
                if isinstance(info.get("returnOnEquity"), (int, float)):
                    card["business"]["roe"] = float(info["returnOnEquity"])
                if isinstance(info.get("profitMargins"), (int, float)):
                    card["business"]["profit_margin"] = float(info["profitMargins"])
                blurb = _build_yf_business_read(info)
                if blurb:
                    card["business_read"] = blurb
                    card["sources"].append("yfinance_info")
            except Exception as yf_exc:
                logger.debug("name_card_yf_info_failed", ticker=symbol, error=str(yf_exc)[:120])
        shorts = await provider.get_finra_short_interest(symbol, limit=6)
        if shorts.success and shorts.data:
            records = shorts.data.get("records") or []
            card["shorts"] = {"records": records[:6], "read": _short_bias(records)}
            card["sources"].append("finra")
    except Exception as exc:
        logger.debug("name_card_reg_failed", ticker=symbol, error=str(exc)[:160])

    crypto = (
        symbol.endswith("-USD")
        or "/" in symbol
        or symbol in {"BTC", "ETH", "SOL", "BTCUSD", "ETHUSD"}
    )
    try:
        news = await aggregate_free_news(
            symbol.replace("-USD", "").replace("/", ""),
            crypto=crypto,
            limit=12,
        )
        card["news"] = news[:5]
        card["sources"].extend(sorted({str(n.get("source")) for n in news if n.get("source")}))
    except Exception as exc:
        logger.debug("name_card_news_failed", ticker=symbol, error=str(exc)[:160])

    if crypto:
        if not card.get("business_read"):
            vol = card.get("quote", {}).get("volume")
            vol_bit = ""
            if isinstance(vol, (int, float)) and vol > 0:
                vol_bit = f"; оборот дня ≈ {vol:,.0f}"
            card["business_read"] = (
                "криптоактив без SEC-отчётности: смотрим цену, ликвидность и сетевые новости"
                + vol_bit
            )
        if not card["shorts"].get("read"):
            card["shorts"]["read"] = (
                "FINRA short interest не применим — это не US equity; ориентир — фандинг/перпы на биржах"
            )
        if not card["news"]:
            card["news"] = []
            if not card.get("filings_read"):
                card["filings_read"] = "регуляторных filings по этой бумаге нет"
            card.setdefault(
                "news_read",
                "свежих заголовков по тикеру пока нет — смотрим цену и ликвидность",
            )
        else:
            card["news_read"] = None
    else:
        card["news_read"] = None

    side = str(direction or "").lower()
    if side == "long":
        lead = "Почему сегодня смотрим покупку"
    elif side == "short":
        lead = "Почему сегодня смотрим продажу"
    else:
        lead = "Что видно по бумаге сегодня"

    why: list[str] = []
    trend = str(card.get("trend") or "")
    detail = str(card.get("trend_detail") or "").strip()
    if closes:
        rsi = _rsi14(closes)
        if rsi is not None:
            if rsi >= 70:
                why.append(f"RSI≈{rsi:.0f}: бумага перегрета покупками — риск отката")
            elif rsi <= 30:
                why.append(f"RSI≈{rsi:.0f}: бумага перепродана — возможен отскок")
            elif side == "long" and rsi >= 55:
                why.append(f"RSI≈{rsi:.0f}: импульс ещё на стороне покупателей")
            elif side == "short" and rsi <= 45:
                why.append(f"RSI≈{rsi:.0f}: импульс ещё на стороне продавцов")

    if side == "long" and "вниз" in trend:
        why.append("покупка спорит с графиком: цена ниже своей средней")
    elif side == "short" and "вверх" in trend:
        why.append("продажа спорит с графиком: цена выше своей средней")
    elif detail and detail not in trend and detail not in why:
        why.append(detail)

    if card.get("filings_read"):
        # filings stay under «Бизнес» in the UI — skip why
        pass
    if card["shorts"].get("read") and not crypto:
        # shorts have their own block — skip why
        pass
    # business_read stays only in «Бизнес» — never duplicate into «Почему»

    for item in (card.get("news") or [])[:3]:
        title = str(item.get("title") or "").strip()
        src = str(item.get("source") or "").strip()
        if title:
            why.append(f"новость{f' ({src})' if src else ''}: {title}")

    # News already has its own block — keep at most one headline in why when empty otherwise
    news_why = [w for w in why if w.startswith("новость")]
    non_news = [w for w in why if not w.startswith("новость")]
    if non_news:
        why = non_news  # drop news duplicates when we already have chart/RSI reasons
    else:
        why = news_why[:1]

    if not why and crypto and card.get("business_read"):
        # crypto has no separate business block content otherwise
        why.append(str(card["business_read"]))

    price_bits = {str(card.get("trend") or "").strip(), str(card.get("vs_market") or "").strip()}
    why = [w for w in why if w and w not in price_bits]
    # de-dupe while preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for w in why:
        key = w.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(w)
    why = deduped[:6]
    if not why:
        why.append(
            "опора на цену и ликвидность — ждём более сильный новостной драйвер"
            if crypto
            else "картина ещё собирается — ждём больше данных по новости и отчётности"
        )
    card["why_points"] = why
    card["why"] = lead + ": " + "; ".join(why)
    card["horizons"] = {
        "быстро": "до полутора часов",
        "день": "до конца сессии",
        "несколько дней": "пока идея не сломается, обычно несколько дней",
        "долго": "недели",
    }
    card["as_of"] = datetime.now(timezone.utc).isoformat()
    return card
