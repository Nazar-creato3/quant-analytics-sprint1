"""Deterministic event/news interpretation hints for ticker chat (regulatory relief)."""
from __future__ import annotations

import re
from dataclasses import dataclass

_EXTEND = re.compile(
    r"extend(?:s|ed|ing)?|extension|продл(?:и|е|ё|ен|ена|ение|ён|ённ)",
    re.IGNORECASE,
)
_LICENSE = re.compile(r"licen[cs]e?|лиценз", re.IGNORECASE)
_REGULATOR = re.compile(
    r"ofac|treasury|минфин|us\s+treasury|u\.s\.\s+treasury|department\s+of\s+treasury",
    re.IGNORECASE,
)
_CARLYLE = re.compile(r"carlyle|кarlyle|кarlyle", re.IGNORECASE)
_LUKOIL_INTL = re.compile(r"lukoil\s+international|lukoil\s+intl", re.IGNORECASE)
_ASSET_SALE = re.compile(
    r"international\s+gmbh|intl\s+assets?|asset\s+sale|продаж[аи]\s+актив|"
    r"structured\s+sale|stake|дол[яи]\s+в|foreign\s+block",
    re.IGNORECASE,
)
_ENERGY_TICKERS = frozenset({"LKOH", "ROSN", "SNGS", "SNGSP", "TATN", "TATNP", "BANE"})


@dataclass(frozen=True, slots=True)
class EventNewsInterpretation:
    """Structured read of a regulatory / deal headline for advisor replies."""

    kind: str
    short_term_bias: str
    trading_conclusion_ru: str
    counterparty_ru: str | None
    temporality_ru: str

    def lead_paragraph_ru(self, *, ticker: str, headline: str | None = None) -> str:
        trading = self.trading_conclusion_ru.replace("{ticker}", ticker)
        parts: list[str] = []
        if headline:
            snippet = headline.strip()
            if len(snippet) > 120:
                snippet = snippet[:117] + "…"
            parts.append(f"По материалу «{snippet}» — {trading[0].lower()}{trading[1:]}")
        else:
            parts.append(trading)
        if self.counterparty_ru:
            parts.append(self.counterparty_ru)
        parts.append(self.temporality_ru)
        return " ".join(parts)

    def llm_hints_block(self) -> str:
        lines = [
            f"event_kind: {self.kind}",
            f"short_term_bias: {self.short_term_bias}",
            f"trading_conclusion: {self.trading_conclusion_ru}",
        ]
        if self.counterparty_ru:
            lines.append(f"counterparty: {self.counterparty_ru}")
        lines.append(f"temporality: {self.temporality_ru}")
        lines.append(
            "Важно: для продления лицензии/OFAC relief не описывай эффект как "
            "«умеренное снижение» — краткосрочный bias умеренно позитивный (снижение "
            "tail-риска сделки), без сигнала «сильный лонг»."
        )
        return "\n".join(lines)


def _combined_corpus(question: str, headlines: tuple[str, ...] | list[str]) -> str:
    chunks = [question.strip()]
    chunks.extend(headlines)
    return "\n".join(chunks)


def is_ofac_license_extension_scenario(*, question: str, headlines: tuple[str, ...] | list[str]) -> bool:
    text = _combined_corpus(question, headlines)
    if not (_EXTEND.search(text) and _LICENSE.search(text)):
        return False
    return bool(_REGULATOR.search(text) or _LUKOIL_INTL.search(text))


def mentions_carlyle(*, question: str, headlines: tuple[str, ...] | list[str]) -> bool:
    return bool(_CARLYLE.search(_combined_corpus(question, headlines)))


def interpret_event_news(
    *,
    question: str,
    headlines: tuple[str, ...] | list[str],
    ticker: str = "",
) -> EventNewsInterpretation | None:
    """Infer structured trading read for known regulatory-relief patterns."""
    sym = ticker.strip().upper().split(".")[0]
    text = _combined_corpus(question, headlines)
    energy_relevant = sym in _ENERGY_TICKERS or bool(
        re.search(r"lukoil|лукойл|lkoh", text, re.IGNORECASE)
    )

    if not is_ofac_license_extension_scenario(question=question, headlines=headlines):
        return None
    if not energy_relevant:
        return None

    ticker_label = sym or "бумаге"
    trading = (
        f"Для {ticker_label} продление разрешительного окна снижает риск немедленного "
        f"разрыва сделки по зарубежным активам — краткосрочно это умеренно позитивный "
        f"сигнал (relief, снижение неопределённости), а не подтверждение сильного бычьего тренда."
    )

    counterparty: str | None = None
    if mentions_carlyle(question=question, headlines=headlines) or _ASSET_SALE.search(text):
        counterparty = (
            "Связка с Carlyle и структурированной продажей международных активов сохраняет "
            "опциональность на монетизацию — это поддерживает сценарий реализации стоимости "
            "и уменьшает хвост блокировки зарубежного контура."
        )

    temporality = (
        "Продление — временная мера, а не закрытая сделка: без follow-through эффект "
        "может быстро сойти на нет; bias краткосрочно позитивный, уверенность ограничена."
    )

    return EventNewsInterpretation(
        kind="ofac_license_extension",
        short_term_bias="moderately_positive_short_term",
        trading_conclusion_ru=trading,
        counterparty_ru=counterparty,
        temporality_ru=temporality,
    )
