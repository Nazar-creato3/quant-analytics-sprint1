"""Labeled RU/EN financial headlines (Prompt 44). Rules: docs/models/news.md."""
from __future__ import annotations

from typing import Any

# (event, ticker, ru_or_en_template, sentiment) — expanded to ≥500 with variants.
_TEMPLATES: tuple[tuple[str, str, str, str], ...] = (
    ("dividend", "SBER", "Сбербанк объявил дивиденды {n} руб на акцию", "positive"),
    ("dividend", "SBER", "Sberbank sets dividend of {n} rubles", "positive"),
    ("earnings", "SBER", "Сбербанк отчитался по МСФО за квартал {n}", "neutral"),
    ("earnings", "GAZP", "Газпром опубликовал отчётность, прибыль {n} млрд", "positive"),
    ("sanctions", "GAZP", "США ввели санкции против Газпрома, пакет {n}", "negative"),
    ("sanctions", "GAZP", "New US sanctions hit Gazprom unit {n}", "negative"),
    ("cbr", "IMOEX", "Банк России сохранил ключевую ставку, решение {n}", "neutral"),
    ("cbr", "IMOEX", "ЦБ РФ повысил ключевую ставку на фоне инфляции {n}", "negative"),
    ("m_and_a", "YNDX", "Яндекс объявил слияние, сделка номер {n}", "positive"),
    ("m_and_a", "YNDX", "Yandex merger talks continue, round {n}", "neutral"),
    ("earnings", "LKOH", "ЛУКОЙЛ представил финансовые результаты {n}", "neutral"),
    ("dividend", "LKOH", "ЛУКОЙЛ рекомендовал дивиденды {n} руб", "positive"),
    ("other", "AAPL", "Apple store hours change in city {n}", "neutral"),
    ("other", "MSFT", "Microsoft campus tour {n} cancelled", "neutral"),
    ("earnings", "AAPL", "Apple quarterly results beat estimates {n}", "positive"),
    ("guidance", "MSFT", "Microsoft raises forecast after quarter {n}", "positive"),
    ("m_and_a", "NVDA", "NVIDIA acquisition rumor number {n}", "positive"),
    ("sanctions", "ROSN", "Санкции расширены на Роснефть, список {n}", "negative"),
    ("cbr", "SBER", "Решение Банка России по ставке, заседание {n}", "neutral"),
    ("dividend", "GAZP", "Газпром отменил дивиденды, год {n}", "negative"),
)


def labeled_news(n: int = 500) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    templates = _TEMPLATES
    while len(out) < n:
        i = len(out)
        event, ticker, tmpl, sent = templates[i % len(templates)]
        variant = i // len(templates)
        title = tmpl.format(n=variant + 1)
        out.append(
            {
                "id": f"lab-{i:04d}",
                "title": title,
                "ticker": ticker,
                "event": event,
                "sentiment": sent,
                "lang": "ru" if any("а" <= ch.lower() <= "я" for ch in title.lower()) else "en",
                "source": "rbc",
            }
        )
    return out[:n]
