"""Human-language explanations for strategies and market scores (RU primary)."""
from __future__ import annotations

from typing import Any, Mapping

STRATEGY_LABELS_RU: dict[str, str] = {
    "momentum": "импульс — расчёт на продолжение текущего движения цены",
    "mean_reversion": "возврат к среднему — цена значительно отклонилась от средней и может вернуться",
    "breakout": "пробой — цена выходит из длительного торгового диапазона",
    "grid": "сетка — набор заявок вокруг текущей цены без прогноза направления",
    "event_driven": "событие — новость или отчётность могут существенно изменить цену",
    "trend_following": "следование за трендом — позиция сохраняется, пока тренд не нарушен",
    "macro": "макро — решение основано на общей ситуации на рынке, а не только на динамике бумаги",
    "no_trade": "вход сейчас нецелесообразен",
}


def _f(features: Mapping[str, Any], key: str, default: float = 0.0) -> float:
    try:
        return float(features.get(key, default) or default)
    except (TypeError, ValueError):
        return default


def describe_trend(features: Mapping[str, Any], direction: str) -> str:
    vs_sma = _f(features, "price_vs_sma20")
    crossed = bool(_f(features, "sma_cross_5_20"))
    rsi = _f(features, "rsi_14", 50.0)
    vol = _f(features, "volume_ratio", 1.0)
    side = "покупки" if str(direction).lower() == "long" else "продажи"

    if vs_sma > 0.01 and crossed:
        trend = "цена выше 20-дневной средней, короткая средняя пересекла длинную снизу вверх — восходящее движение подтверждается"
    elif vs_sma < -0.01 and not crossed:
        trend = "цена ниже средней, короткая средняя не подтверждает рост — нисходящее движение устойчивее"
    elif abs(vs_sma) <= 0.01:
        trend = "цена находится около средней — выраженного тренда нет, вероятнее краткосрочное колебание"
    elif vs_sma > 0:
        trend = "цена выше средней, но пересечение средних слабое — восходящий тренд выражен неявно"
    else:
        trend = "цена ниже средней — преобладают продажи"

    heat = "нейтральна"
    if rsi >= 70:
        heat = "перекуплена (индекс относительной силы 70 и выше)"
    elif rsi <= 30:
        heat = "перепродана (индекс относительной силы 30 и ниже)"

    volume = "объём на среднем уровне"
    if vol > 1.2:
        volume = "объём выше среднего — движение подтверждено торговой активностью"
    elif vol < 0.8:
        volume = "объём ниже среднего — движение может быстро ослабнуть"

    return (
        f"Для {side}: {trend}. "
        f"По индикатору силы бумага сейчас {heat}. {volume.capitalize()}."
    )


def build_position_rationale(
    *,
    strategy: str,
    direction: str,
    confidence: float,
    regime: str,
    features: Mapping[str, Any],
    is_fallback: bool,
    risk_reward: float | None = None,
    sentiment: float = 0.0,
) -> str:
    source = (
        "модель оценивает историю этой бумаги и аналогичных ситуаций"
        if not is_fallback
        else "использован упрощённый расчёт, полная модель недоступна"
    )
    label = STRATEGY_LABELS_RU.get(str(strategy), "смешанный подход")
    side = "рост" if str(direction).lower() == "long" else "снижение"
    conf_pct = max(0, min(100, int(round(float(confidence) * 100))))
    trend = describe_trend(features, direction)
    news = ""
    if abs(sentiment) > 0.25:
        news = (
            " Новостной фон по бумаге скорее поддерживает идею."
            if sentiment > 0
            else " Новостной фон по бумаге скорее против этой идеи — размер позиции стоит ограничить."
        )
    rr = ""
    if risk_reward is not None and risk_reward > 0:
        rr = " Соотношение потенциальной прибыли к риску — около " + f"{risk_reward:.1f}".replace(".", ",") + " к 1."
    regime_h = {
        "trending_up": "рынок в целом растёт",
        "trending_down": "рынок в целом снижается",
        "range_bound": "рынок движется в диапазоне",
        "high_volatility": "волатильность рынка выше обычной",
        "bull": "общий фон позитивный",
        "bear": "общий фон негативный",
        "sideways": "рынок без выраженного направления",
        "volatile": "на рынке повышенная волатильность",
    }.get(str(regime), f"фон рынка: {regime}")
    return (
        f"Идея: {side}, стиль — {label}. Уверенность модели около {conf_pct}%. "
        f"Основа оценки: {source}. Сейчас {regime_h}. {trend}{news}{rr}"
    )


def market_beat_explanation(*, score20: int, p20: float, trusted: bool) -> str:
    if not trusted:
        return (
            "Оценка по этой бумаге сейчас недостаточно надёжна — "
            "показана нейтральная оценка 5 из 10, увеличивать позицию не предлагается."
        )
    return (
        f"Оценка {score20} из 10 на горизонте около 20 торговых дней: "
        "вероятность того, что бумага опередит свой рынок (для российских акций — индекс IMOEX, для акций США — фонд SPY). "
        f"Вероятность опережения по модели — около {p20:.0%}. "
        "5 — шансы 50 на 50; ближе к 10 — модель видит преимущество бумаги, ближе к 1 — вероятнее отставание от рынка."
    )
