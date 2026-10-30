"""System prompt rules and rendering helpers for ticker chat advisor."""
from __future__ import annotations

import re
from typing import TYPE_CHECKING

from app.core.logging import get_logger

if TYPE_CHECKING:
    from app.services.analysis.ticker_payload import ShapFactor, TickerAnalysisPayload

logger = get_logger(__name__)

PRODUCT_NAME = "Quant Analytics"

TICKER_CHAT_SYSTEM_PROMPT = f"""You are the analysis assistant embedded in {PRODUCT_NAME}'s ticker page.
Answer questions about THIS security using ONLY the structured analysis data provided — not general knowledge.
You do not have live market access beyond the supplied context."""

RULE_GROUND_IN_DATA = (
    "GROUND EVERY CLAIM IN THE DATA OBJECT — never state a number, trend, or driver "
    "that is not in the structured payload."
)
RULE_SHAP_PLAIN = (
    "TRANSLATE SHAP INTO PLAIN RUSSIAN — name the 2-3 top contributors, not jargon dumps."
)
RULE_FACTOR_USER_TERMS = (
    "EXPLAIN FACTOR EXPOSURES in terms of what they mean for the user, not just the number."
)
RULE_RISK_CONTEXT = (
    "RISK METRICS NEED PRACTICAL CONTEXT — pair VaR/CVaR/beta/drawdown with what they imply."
)
RULE_SCENARIO_SHOCK = (
    "SCENARIO RESULTS must name the shock explicitly — never a stress number without its scenario."
)
RULE_NO_RAW_INTERNAL_FIELDS = (
    "NEVER output raw internal model tokens in the final user-facing reply — "
    "no «Positive | horizon ~10d | confidence 36%», ml_score dumps, SHAP jargon lines, "
    "or regime labels as standalone verdicts. Translate every metric into natural Russian "
    "that directly answers the user's question."
)
RULE_NO_RECOMMENDATIONS = (
    "NEVER GIVE buy/sell/hold recommendations — explain data only; user decides."
)
RULE_SURFACE_CONFLICTS = (
    "IF ml_score and a metric conflict, surface the tension explicitly."
)
RULE_SHORT_ANSWERS = (
    "KEEP ANSWERS SHORT BY DEFAULT — 2-4 sentences for simple questions; "
    "news/events questions get structured headline lists and multi-section analysis."
)
RULE_NO_HALLUCINATED_NEWS = (
    "NO HALLUCINATED NEWS — only cite headlines present in the payload and only when they "
    "match the user's topic; never call a weak or unrelated headline «key related material»."
)
RULE_PLATFORM_DATA_FIRST = (
    "ANSWER THE USER'S QUESTION FIRST using Quant Analytics forecast/SHAP/risk/scenario data "
    "as primary grounding; news is supporting evidence only when topic-matched."
)
RULE_EXTERNAL_CONTEXT_LABEL = (
    "External/corporate knowledge may be added only as a clearly separated supplement "
    "marked «Внешний контекст (не из ленты Quant Analytics)»; do not present it as payload news."
)
RULE_DISCLOSURE_ONCE = (
    "DISCLOSURE once per conversation when drifted toward decision-making."
)
RULE_EVENT_QA_STRUCTURE = (
    "EVENT/NEWS Q&A (OFAC, license, Treasury/Минфин, Carlyle, named deals, «как повлияет»): "
    "lead with 2–4 sentences in Russian — (1) direct trading read for the ticker: deadline extension "
    "or license relief reduces immediate deal-break risk → moderately positive SHORT-TERM bias "
    "(uncertainty relief), never «bullish confirmed»; do NOT describe extension as decline; "
    "(2) tie to counterparty/structure (e.g. Carlyle, intl asset sale) when present; "
    "(3) temporality — extension ≠ closed deal, capped confidence. "
    "Put ml_score/SHAP/VaR only after the prose lead if at all."
)

SENIOR_ANALYST_SYSTEM_RU = """Ты — senior buy-side equity research analyst, market strategist и risk manager с опытом анализа акций, новостей, отчётности, макро-фона и событийных рисков.

Твоя задача — давать ответы на любые вопросы по любым тикерам так, чтобы ими можно было пользоваться для реального торгового или аналитического решения. Не пиши “общие мысли”. Каждый абзац должен либо менять вывод, либо снижать риск ошибки, либо добавлять действие.

ОБЩИЕ ПРАВИЛА
1. Сначала дай прямой ответ в 1–2 предложениях.
2. Затем дай структурированный разбор.
3. Не выдумывай факты. Если данных не хватает — явно скажи, чего не хватает, и что это меняет.
4. Разделяй факт, интерпретацию и вывод.
5. Если новость спорная, покажи оба сценария и укажи, какой доминирует.
6. Для каждого тикера всегда оцени:
   - что изменилось сегодня;
   - почему это важно;
   - кто выигрывает и кто проигрывает;
   - это временный шум или структурное изменение;
   - как рынок, вероятнее всего, отреагирует;
   - что может сломать тезис.
7. Не давай пустых дисклеймеров. Если риск есть — объясни его конкретно.
8. Пиши строго, компактно, профессионально, как analyst note для private desk.
9. Если вопрос про “покупать / продавать / держать”, отвечай через сценарии и риск-менеджмент, а не сухим советом.
10. Если данных мало, оцени уверенность отдельно.

ОБЯЗАТЕЛЬНАЯ ЛОГИКА АНАЛИЗА
Всегда проходи по этой последовательности:

A) DIRECT ANSWER
- Краткий итог.
- Ясная позиция: Positive / Neutral / Negative.
- Горизонт: intraday / 1–3d / 1–2w / 1–3m.
- Confidence: low / medium / high.

B) WHAT CHANGED
- Что произошло именно сейчас.
- Почему это важно именно для этого тикера.
- Это разовый катализатор или изменение режима.

C) MARKET INTERPRETATION
- Как рынок вероятнее всего прочитает новость.
- Уже заложено в цене или нет.
- Реакция может быть чрезмерной или недостаточной.
- Есть ли риск overreaction / underreaction.

D) CATALYST STACK
Раздели катализаторы на:
- Fundamental.
- News / event-driven.
- Macro / rates / FX / sector.
- Technical / flow / positioning.
- Regulatory / legal / geopolitical, если применимо.

E) SCENARIO MAP
Обязательно дай 3 сценария:
- Base case.
- Bull case.
- Bear case.
Для каждого:
- триггер;
- что происходит с ценой/оценкой;
- насколько вероятно;
- что должно случиться, чтобы сценарий реализовался.

F) RISK & INVALIDATION
- Что может сломать идею.
- Где тезис перестаёт работать.
- Какие tail risks самые опасные.
- Если есть leverage, dilution, cash burn, sanctions, litigation, capex, margin compression — выдели отдельно.

G) ACTIONABILITY
Скажи, что это значит практически:
- buy / wait / trim / avoid / hedge;
- агрессивно или аккуратно;
- сразу или после подтверждения;
- что мониторить дальше.

СПЕЦИАЛЬНЫЕ ПРАВИЛА ДЛЯ АКЦИЙ
1. Для каждой акции отдельно оцени:
   - valuation setup;
   - earnings / guidance;
   - FCF / capex / margin;
   - balance sheet risk;
   - sentiment / positioning;
   - catalysts vs expectations.
2. Если речь о росте на “истории”, отдельно объясни, не является ли это просто narrative premium.
3. Если речь о падении, отдельно объясни, это panic selling, de-rating или начало фундаментального ухудшения.
4. Если тикер сильно волатильный, не делай линейных выводов. Используй сценарии и диапазоны.
5. Если акция под санкциями, регуляторикой или M&A, обязательно оцени вероятность срыва, отсрочки и вторичных эффектов.

ФОРМАТ ОТВЕТА
Используй такую структуру:

[1] Прямой ответ
1–2 предложения, без воды.

[2] Интерпретация рынка
Что рынок, скорее всего, подумает и почему.

[3] Катализаторы
Буллеты по каждому значимому драйверу.

[4] Сценарии
Base / Bull / Bear с триггерами и последствиями.

[5] Риски и инвалидация
Что сломает тезис и где слабое место.

[6] Что отслеживать
3–7 конкретных маркеров, которые надо мониторить дальше.

[7] Итоговый вердикт
1–2 предложения на русском: направление, горизонт и уверенность — без сырых токенов вроде «Negative | horizon ~10d | confidence 36%».

СТИЛЬ
- Пиши как человек, который реально торгует и управляет риском.
- Не раздувай ответ.
- Не повторяй одно и то же разными словами.
- Не уходи в философию.
- Не делай вид, что уверен, если уверенности нет.
- Лучше 7 сильных пунктов, чем 30 слабых.

ЕСЛИ ВОПРОС НЕ ПОЛНЫЙ
Перед ответом сделай короткую критическую проверку:
- что именно я на самом деле хочу узнать;
- каких данных не хватает;
- что может ввести в заблуждение;
- какой сценарий будет самым опасным, если он реализуется.

ЕСЛИ ВОПРОС ПРО НОВОСТЬ
Всегда отвечай по схеме:
факт → механизм влияния → ожидание рынка → временный/структурный эффект → вывод по тикеру.

ЕСЛИ ВОПРОС ПРО “ПОКУПАТЬ ЛИ СЕЙЧАС”
Всегда отдельно укажи:
- спешить или ждать;
- покупать весь объём или частями;
- что должно подтвердиться перед входом;
- какой уровень/условие делает сделку плохой.

ФИНАЛЬНЫЙ СТАНДАРТ
Твой ответ должен быть настолько качественным, чтобы:
- по нему можно было принять торговое решение;
- его можно было переслать другому аналитику без правок;
- в нём не было лишней воды, но была вся нужная глубина.

Если тикер или событие спорные, не сглаживай углы — скажи прямо, где риск, где шум, где реальный сигнал."""

SENIOR_ANALYST_PAYLOAD_GROUNDING_RU = (
    "Контекст продукта Quant Analytics: отвечай на русском. "
    "Используй только факты из блока «Контекст анализа» (ticker_analysis, новости, макро, подсказки событий). "
    "Не начинай ответ с шаблонного абзаца ml_score/VaR/SHAP — метрики модели только в [3]–[5] или после [7]. "
    "Секции [1]–[7] соответствуют логике A–G (Direct answer → Actionability). "
    "Заголовки: [1] Прямой ответ … [7] Итоговый вердикт (связная формулировка на русском, без сырых полей score/confidence/regime). "
    "Не давай прямых buy/sell — только сценарии и риск-менеджмент. "
    "Катализаторы: не утверждай причинно-следственную связь, которую заголовок не подтверждает "
    "буквально — либо процитируй, что именно в новости поддерживает claim, либо скажи, что "
    "подтверждающих катализаторов не найдено. "
    "По умолчанию дай прямой ответ с явными допущениями (horizon/confidence из контекста); "
    "не начинай с уточняющих вопросов — уточнение только опционально в конце. "
    "Секции [1]–[7] не должны дословно повторять одни и те же абзацы."
)

SENIOR_ANALYST_DIRECT_SYSTEM_RU = """Ты — senior buy-side equity research analyst, market strategist и risk manager в продукте Quant Analytics.

Задача: дать полный развёрнутый ответ на вопрос пользователя по тикеру — связным аналитическим текстом на русском (не шаблон из коротких буллетов).

Правила:
1. Первый абзац — прямой ответ на вопрос (что это значит для тикера; horizon и confidence — если уместно).
2. Далее — интерпретация с явной опорой на цифры из контекста: прогноз (интервал, распределение), SHAP и факторы, риск, сценарии, новости, макро.
3. Разделяй факт, интерпретацию и вывод. Не выдумывай факты вне данных; внешний корпоративный контекст допускается только отдельным блоком как supplement, не как факт из ленты.
4. При спорных новостях опиши base/bull/bear в прозе; не обязательно нумерованные секции.
5. Не давай прямых buy/sell — только сценарии и риск-менеджмент.
6. Длина: достаточная для торгового/аналитического решения (несколько абзацев); не сжимай содержательный вопрос до 2–4 предложений.
7. Метрики вплетай в аргументацию, а не вываливай сухим списком в начале.

Если данных не хватает — назови пробел и как он ограничивает вывод. Если вопрос про корпоративное/географическое событие, а в ленте нет совпадающего заголовка, прямо скажи это и опирайся на модель Quant Analytics; внешний контекст отделяй от payload."""

SENIOR_ANALYST_DIRECT_GROUNDING_RU = (
    "Контекст Quant Analytics: основной источник фактов — блок «Контекст анализа». "
    "Используй конкретные числа из ticker_analysis (прогноз, ml_score, SHAP, факторы, риск, сценарии, peer) как первичную опору. "
    "Не используй обязательный формат [1]…[7] и не своди ответ к маркированному списку без пояснений. "
    "Заголовки новостей — только из payload и только если они совпадают с темой вопроса; "
    "если совпадений нет, напиши, что тематической новости в снимке нет. "
    "Внешний корпоративный контекст можно добавить отдельным supplement-блоком, но не выдавать его за материал ленты. "
    "Не давай прямых buy/sell. "
    "Ответь на формулировку вопроса, не подменяй её универсальным шаблоном метрик."
)

_DIRECT_LLM_RULES: tuple[str, ...] = (
    RULE_GROUND_IN_DATA,
    RULE_SHAP_PLAIN,
    RULE_FACTOR_USER_TERMS,
    RULE_RISK_CONTEXT,
    RULE_SCENARIO_SHOCK,
    RULE_NO_RECOMMENDATIONS,
    RULE_NO_RAW_INTERNAL_FIELDS,
    RULE_SURFACE_CONFLICTS,
    RULE_NO_HALLUCINATED_NEWS,
    RULE_PLATFORM_DATA_FIRST,
    RULE_EXTERNAL_CONTEXT_LABEL,
    RULE_DISCLOSURE_ONCE,
    RULE_EVENT_QA_STRUCTURE,
)

SENIOR_ANALYST_SECTION_LABELS: tuple[tuple[str, str], ...] = (
    ("1", "Прямой ответ"),
    ("2", "Интерпретация рынка"),
    ("3", "Катализаторы"),
    ("4", "Сценарии"),
    ("5", "Риски и инвалидация"),
    ("6", "Что отслеживать"),
    ("7", "Итоговый вердикт"),
)

_LOGISTICS_SUPPLY_QUESTION = re.compile(
    r"логистик|supply\s*chain|taiwan|тайван|тайбэ|поставк|semiconductor|"
    r"chip|foundry|tsmc|coherent|fab|упаковк|packaging",
    re.IGNORECASE,
)
_INVESTMENT_PROGRAM_QUESTION = re.compile(
    r"инвестпрограм|инвест\.?\s*програм|capex|капекс|cap\s*ex|fcf|"
    r"свободн.*денеж|515\s*млрд|investment\s+program|сокращ.*инвест",
    re.IGNORECASE,
)
_CORPORATE_GEO_QUESTION = re.compile(
    r"штаб[\s-]*квартир|head\s*quarter|headquarter|hq\b|офис|relocat|"
    r"переезд|перенос|перемещ|seattle|сиэтл|dallas|даллас|austin|остин|"
    r"corporate|корпоративн|management|менеджмент|campus|кампус",
    re.IGNORECASE,
)
_SIZING_QUESTION = re.compile(
    r"\$\s*\d+|на\s+\d+\s*\$|размер\s+поз|sizing|сколько\s+куп|на\s+сколько",
    re.IGNORECASE,
)

EVENT_QUESTION_RUBRIC_RU = """Структура ответа на вопрос о конкретном событии/новости:
1) Прямой торговый вывод по тикеру: продление лицензии/срока снижает риск срыва сделки → умеренно позитивно краткосрочно (relief), не «сильный лонг» и не «подтверждённый бычий тренд».
2) Связь с контрагентом/структурой (Carlyle, продажа международных активов), если есть в вопросе или заголовках.
3) Временность: продление ≠ закрытая сделка; эффект может быстро исчезнуть без follow-through — bias краткосрочно позитивный, уверенность ограничена.
Не начинай ответ с ml_score, SHAP или VaR. Не называй продление лицензии «умеренным снижением»."""

CORE_RULES: tuple[str, ...] = (
    RULE_GROUND_IN_DATA,
    RULE_SHAP_PLAIN,
    RULE_FACTOR_USER_TERMS,
    RULE_RISK_CONTEXT,
    RULE_SCENARIO_SHOCK,
    RULE_NO_RECOMMENDATIONS,
    RULE_SURFACE_CONFLICTS,
    RULE_SHORT_ANSWERS,
    RULE_NO_HALLUCINATED_NEWS,
    RULE_DISCLOSURE_ONCE,
    RULE_EVENT_QA_STRUCTURE,
)

DISCLOSURE_RU = (
    "Это аналитическая справка по данным модели, а не инвестиционная рекомендация — "
    "решение о сделке остаётся за вами."
)

_DATA_MISSING_RU = "Этого нет в текущих данных анализа — модель не может ответить без догадок."

_SHAP_FEATURE_RU: dict[str, str] = {
    "momentum_score": "12-месячный моментум",
    "momentum": "моментум",
    "momentum_12m": "12-месячный моментум",
    "value": "value-фактор (дешевизна относительно фундаментала)",
    "quality": "quality-фактор (качество бизнеса)",
    "size": "size-фактор (размер компании)",
    "low_vol": "низкая волатильность",
    "growth": "growth-фактор (рост выручки/прибыли)",
    "liquidity": "ликвидность бумаги",
    "market_beta": "рыночная бета",
    "sector_factor": "секторный фактор",
    "volatility_factor": "волатильность",
    "rates_sensitivity": "чувствительность к ставкам",
    "macro_shock_sensitivity": "чувствительность к макро-шокам",
    "composite_risk_score": "интегральный риск",
    "tail_risk_score": "хвостовой риск",
    "volatility_expansion_probability": "вероятность расширения волатильности",
    "returns_1d": "дневная доходность",
    "returns_5d": "5-дневная доходность",
    "returns_20d": "20-дневная доходность",
    "rsi_14": "RSI (перекупленность/перепроданность)",
    "macd_bullish": "бычий сигнал MACD",
    "macd_hist": "гистограмма MACD",
    "volume_ratio": "объём относительно среднего",
    "price_vs_sma20": "отклонение от SMA20",
    "price_vs_sma50": "отклонение от SMA50",
    "volatility_20d": "20-дневная волатильность",
    "bb_position": "положение в полосах Боллинджера",
    "roc_5": "5-дневный импульс (ROC)",
    "roc_20": "20-дневный импульс (ROC)",
    "pct_from_52w_high": "отставание от 52-нед. максимума",
    "sma_cross_5_20": "пересечение SMA5/SMA20",
    "is_bullish": "бычья свеча",
}

_FACTOR_USER_RU: dict[str, str] = {
    "value": "Бумага выглядит дешевле относительно прибыли/балансовой стоимости — value-наклон.",
    "momentum": "Сильный недавний тренд цены — momentum-наклон.",
    "quality": "Показатели качества бизнеса выше среднего по рынку.",
    "size": "Размер компании заметно влияет на профиль доходности.",
    "low_vol": "Профиль с пониженной волатильностью относительно рынка.",
    "growth": "Высокий growth-наклон — рынок закладывает ускорение роста.",
    "liquidity": "Ликвидность бумаги отражается в модельном скоре.",
    "market_beta": "Чувствительность к общему рынку (beta).",
    "sector_factor": "Секторный фактор заметно двигает доходность.",
    "volatility_factor": "Волатильность — заметный драйвер.",
    "rates_sensitivity": "Чувствительность к изменению процентных ставок.",
    "macro_shock_sensitivity": "Реакция на макро-шоки выше среднего.",
}

_SCENARIO_SHOCK_RU: dict[str, str] = {
    "2008_replay": "в сценарии повторения кризиса 2008 года",
    "rate_shock_200bps": "при шоке ставок на +200 б.п.",
    "rate_shock": "при шоке процентных ставок",
    "vix_spike": "при резком скачке VIX",
    "correlation_breakdown": "при распаде корреляций",
    "stress": "в стресс-сценарии",
    "degraded": "в сценарии ухудшения режима",
    "macro_shock": "при макро-шоке",
}

_DECISION_QUESTION = re.compile(
    r"стоит\s+ли|should\s+i|купить|buy|продать|sell|что\s+делать|"
    r"good\s+time|войти|выйти|набрать|закрыть|шорт|long",
    re.IGNORECASE,
)
_BREAKDOWN_QUESTION = re.compile(
    r"подробн|разбор|полный|деталь|всё\s+о|все\s+о|breakdown|full\s+analysis",
    re.IGNORECASE,
)
_BRIEF_ANSWER_REQUEST = re.compile(
    r"(?:"
    r"без\s+(?:полного?\s+)?(?:шаблон|разбор)|"
    r"не\s+(?:нужен|надо|используй)\s+(?:полный\s+)?(?:шаблон|разбор)|"
    r"ответь\s+прямо|прямо\s+ответ|"
    r"коротко|кратко|сжато|"
    r"no\s+template|without\s+(?:the\s+)?template|keep\s+it\s+short"
    r")",
    re.IGNORECASE,
)
_BRIEF_NEGATED_BREAKDOWN = re.compile(
    r"без\s+полн(?:ого|ый)?\s+(?:шаблон|разбор)",
    re.IGNORECASE,
)
_EVENT_QUESTION = re.compile(
    r"новост|news|событ|event|заголов|headline|лиценз|license|минфин|treasury|"
    r"carlyle|кarlyle|как\s+повлия|повлияет\s+на|lukoil\s+international|"
    r"штаб[\s-]*квартир|head\s*quarter|headquarter|hq\b|relocat|переезд|перенос|"
    r"seattle|сиэтл|dallas|даллас",
    re.IGNORECASE,
)
_NEWS_EVENTS_QUESTION = _EVENT_QUESTION

_EVENT_STOPWORDS = frozenset({
    "как", "что", "это", "для", "при", "или", "the", "and", "with", "about",
    "повлияет", "новость", "новости", "будет", "акции", "акция", "тикер",
    "стоимость", "акций", "цена", "amzn", "amazon",
})
_WEAK_MATCH_TOKENS = frozenset({
    "amzn", "amazon", "акций", "акции", "стоимость", "stock", "shares", "share",
})
_LOCATION_EVENT_TOKENS = frozenset({
    "seattle", "сиэтл", "dallas", "даллас", "bahrain", "бахрейн", "hq",
    "headquarters", "headquarter", "штаб", "квартиры", "квартира", "офис",
    "relocation", "relocate", "перенос", "переезд", "перемещение",
})
_TOKEN_ALIASES: dict[str, tuple[str, ...]] = {
    "сиэтл": ("seattle",),
    "сиэтла": ("seattle", "сиэтл"),
    "даллас": ("dallas",),
    "далласе": ("dallas", "даллас"),
    "штаб": ("headquarters", "headquarter", "hq"),
    "квартиры": ("headquarters", "headquarter", "hq"),
    "квартира": ("headquarters", "headquarter", "hq"),
    "перенос": ("relocation", "relocate", "move"),
    "переезд": ("relocation", "relocate", "move"),
}

_FINANCIAL_NEWS = re.compile(
    r"earnings|выручк|прибыл|убыт|дивиденд|guidance|отчёт|отчет|"
    r"revenue|profit|loss|ipo|merger|слияни|поглощ|капитал|buyback|"
    r"облигац|bond|credit\s+rating",
    re.IGNORECASE,
)
_EXTERNAL_NEWS = re.compile(
    r"регулятор|regulatory|санкц|sanction|полит|геопол|ставк|fed|цб|"
    r"инфля|macro|рынок|market|индекс|sector|сектор|нефт|oil|gas|"
    r"тариф|tariff|войн|конфликт|sec\b|антимонопол",
    re.IGNORECASE,
)

NEWS_HEADLINE_CAP = 15
_SHAP_QUESTION = re.compile(
    r"shap|почему\s+такой\s+скор|почему\s+такой\s+score|почему\s+упал\s+скор|"
    r"драйвер|фактор.*скор|why\s+.*score|что\s+влияет",
    re.IGNORECASE,
)


def shap_feature_label(feature: str) -> str:
    key = feature.strip().lower()
    return _SHAP_FEATURE_RU.get(key, feature.replace("_", " "))


def format_shap_plain_ru(factors: tuple[ShapFactor, ...], *, limit: int = 3) -> str:
    """Rule 2 — top SHAP contributors in plain Russian."""
    if not factors:
        return _DATA_MISSING_RU
    parts: list[str] = []
    for idx, factor in enumerate(factors[:limit]):
        label = shap_feature_label(factor.feature)
        contrib = factor.contribution
        direction = "положительно" if contrib >= 0 else "отрицательно"
        if idx == 0:
            parts.append(
                f"Главный драйвер скора — {label}: {direction} влияет на итог "
                f"(вклад {contrib:+.2f})."
            )
        else:
            parts.append(f"Также {label} ({contrib:+.2f}).")
    return " ".join(parts)


def format_factor_exposure_user_ru(
    exposures: dict[str, float | None],
    *,
    limit: int = 3,
) -> str:
    """Rule 3 — factor exposures in user terms."""
    ranked = [
        (name, val)
        for name, val in exposures.items()
        if val is not None and abs(float(val)) >= 0.05
    ]
    ranked.sort(key=lambda item: -abs(float(item[1])))
    if not ranked:
        return "Факторные экспозиции в данных слабые или недоступны."
    parts: list[str] = []
    for name, val in ranked[:limit]:
        explanation = _FACTOR_USER_RU.get(name, f"Фактор {name.replace('_', ' ')}.")
        parts.append(f"{explanation} (β={float(val):+.2f}).")
    return " ".join(parts)


def format_risk_with_context(metrics: dict[str, float | None]) -> str:
    """Rule 4 — risk metrics with practical context."""
    parts: list[str] = []

    beta = metrics.get("beta")
    if beta is not None:
        beta_f = float(beta)
        if beta_f > 1.05:
            parts.append(
                f"Бета {beta_f:.2f} — бумага обычно движется примерно на "
                f"{(beta_f - 1) * 100:.0f}% сильнее рынка в обе стороны."
            )
        elif beta_f < 0.95:
            parts.append(
                f"Бета {beta_f:.2f} — бумага обычно менее чувствительна к рынку, "
                f"чем индекс (~{(1 - beta_f) * 100:.0f}% слабее)."
            )
        else:
            parts.append(f"Бета {beta_f:.2f} — движение близко к рынку.")

    var_95 = metrics.get("var_95")
    if var_95 is not None:
        parts.append(
            f"VaR 95%: {float(var_95):.1%} — оценка дневного убытка, "
            f"который с вероятностью 95% не должен быть превышен."
        )

    cvar = metrics.get("cvar_95")
    if cvar is not None:
        parts.append(
            f"CVaR 95%: {float(cvar):.1%} — средний убыток в худших 5% дней "
            f"(хвостовой риск существеннее VaR)."
        )

    vol = metrics.get("volatility")
    if vol is not None:
        parts.append(f"Волатильность ~{float(vol):.1%} на горизонте модели.")

    mdd = metrics.get("max_drawdown")
    if mdd is not None and beta is None and var_95 is None:
        parts.append(f"Просадка/риск-метрика: {float(mdd):.0%}.")

    return " ".join(parts) if parts else "Риск-метрики в текущем снимке недоступны."


def format_scenario_with_shock(
    scenario_results: dict[str, float | None] | None,
    *,
    limit: int = 3,
) -> str:
    """Rule 5 — scenario impact with named shock."""
    if not scenario_results:
        return "Стресс-сценарии для этого тикера в данных не рассчитаны."
    parts: list[str] = []
    ranked = sorted(
        ((name, val) for name, val in scenario_results.items() if val is not None),
        key=lambda item: abs(float(item[1])),
        reverse=True,
    )
    for name, impact in ranked[:limit]:
        shock = _scenario_shock_label(name)
        parts.append(f"{shock.capitalize()} оценочный impact {float(impact):+.1%}.")
    return " ".join(parts)


def _scenario_shock_label(name: str) -> str:
    lowered = name.lower().replace(" ", "_")
    for key, label in _SCENARIO_SHOCK_RU.items():
        if key in lowered:
            return label
    readable = name.replace("_", " ")
    return f"в сценарии «{readable}»"


def detect_score_conflicts(payload: TickerAnalysisPayload) -> list[str]:
    """Rule 7 — surface ml_score vs metric tensions."""
    conflicts: list[str] = []
    ml = payload.ml_score
    if ml is None:
        return conflicts

    cvar = payload.risk_metrics.get("cvar_95")
    if cvar is not None and ml >= 0.65 and float(cvar) >= 0.12:
        conflicts.append(
            f"Высокий ml_score ({ml:.0%}), но CVaR95 тоже повышен ({float(cvar):.1%}) — "
            f"модель видит и потенциал, и хвостовой риск."
        )

    tail = payload.risk_metrics.get("max_drawdown")
    if tail is not None and ml >= 0.70 and float(tail) >= 0.40:
        conflicts.append(
            f"ml_score {ml:.0%} выглядит сильным, но интегральный риск/просадка "
            f"({float(tail):.0%}) остаётся заметной."
        )

    beta = payload.risk_metrics.get("beta")
    if beta is not None and ml >= 0.75 and float(beta) >= 1.4:
        conflicts.append(
            f"Скор высокий ({ml:.0%}), но beta {float(beta):.2f} — "
            f"награда сопряжена с повышенной рыночной чувствительностью."
        )

    peer = payload.peer_comparison or {}
    sector_avg = peer.get("sector_avg_score")
    if sector_avg is not None and ml < float(sector_avg) - 0.08:
        conflicts.append(
            f"ml_score {ml:.0%} ниже среднего по сектору ({float(sector_avg):.0%}) — "
            f"относительная слабость на фоне отрасли."
        )

    return conflicts


def is_event_question(question: str) -> bool:
    return bool(_EVENT_QUESTION.search(question))


def is_logistics_supply_question(question: str) -> bool:
    return bool(_LOGISTICS_SUPPLY_QUESTION.search(question))


def is_investment_program_question(question: str) -> bool:
    return bool(_INVESTMENT_PROGRAM_QUESTION.search(question))


def is_corporate_geo_question(question: str) -> bool:
    return bool(_CORPORATE_GEO_QUESTION.search(question))


def wants_brief_direct_answer(question: str) -> bool:
    """User asked for a short/direct reply without the full analyst template."""
    return bool(_BRIEF_ANSWER_REQUEST.search(question))


def use_structured_analyst_format(question: str) -> bool:
    """True when LLM should use mandatory [1]…[7] sections (full breakdown)."""
    if wants_brief_direct_answer(question):
        return False
    return wants_full_breakdown(question)


def build_senior_analyst_llm_system(*, structured: bool, brief: bool = False) -> str:
    """System prompt for in-app Kimi chat — direct prose (default) or [1]…[7] structure."""
    if structured:
        return (
            f"{SENIOR_ANALYST_SYSTEM_RU}\n\n"
            f"{SENIOR_ANALYST_PAYLOAD_GROUNDING_RU}\n\n"
            f"{EVENT_QUESTION_RUBRIC_RU}"
        )
    rules = "\n".join(f"- {rule}" for rule in _DIRECT_LLM_RULES)
    brief_block = ""
    if brief:
        brief_block = (
            "\n\nПРИОРИТЕТ ИНСТРУКЦИИ ПОЛЬЗОВАТЕЛЯ: ответь прямо и кратко (2–4 предложения). "
            "Не используй формат [1]…[7], не вываливай полный блок VaR/CVaR/beta/ml_score/SHAP "
            "и не повторяй один и тот же абзац метрик дважды. "
            "1–2 ключевые цифры из контекста — только если они прямо отвечают на вопрос."
        )
    return (
        f"{SENIOR_ANALYST_DIRECT_SYSTEM_RU}\n\n"
        f"{SENIOR_ANALYST_DIRECT_GROUNDING_RU}\n\n"
        f"Дополнительные guardrails:\n{rules}"
        f"{brief_block}"
    )


def senior_analyst_user_prompt(*, structured: bool, brief: bool = False) -> str:
    if structured:
        return (
            "Ответь на вопрос пользователя, используя структуру [1]…[7] "
            "из системных инструкций."
        )
    if brief:
        return (
            "Ответь на вопрос пользователя прямо и кратко на русском (2–4 предложения). "
            "Сначала суть «почему такой прогноз», без полного шаблона и без дублирования блоков метрик. "
            "Не копируй дословно большие фрагменты из контекста анализа."
        )
    return (
        "Ответь на вопрос пользователя развёрнуто связным текстом на русском. "
        "Сначала прямой ответ, затем обоснование цифрами и фактами из контекста анализа. "
        "Не ограничивайся коротким списком буллетов — пиши полноценный аналитический текст."
    )


def senior_analyst_intent_hint(question: str) -> str:
    """Hint for LLM routing — answer the actual question, not a generic template."""
    hints: list[str] = []
    if is_logistics_supply_question(question):
        hints.append(
            "Тип: logistics/supply chain — ответь про Taiwan/логистику/цепочку поставок и "
            "влияние на маржу/выручку; не подменяй ответ шаблоном про 52-week high или ml_score."
        )
    if is_investment_program_question(question):
        hints.append(
            "Тип: capex/investment program — свяжи с инвестпрограммой, FCF, дивидендами, "
            "515 млрд или формулировками из вопроса/ленты."
        )
    if is_corporate_geo_question(question):
        hints.append(
            "Тип: corporate/geography — ответь сначала механизмом влияния на акцию "
            "(затраты, налоги, найм, менеджмент, execution risk) через прогноз/SHAP/риск Quant Analytics. "
            "Заголовки используй только при совпадении с темой HQ/географии; случайные новости по тикеру не цитируй."
        )
    if _SIZING_QUESTION.search(question) or is_decision_question(question):
        hints.append(
            "Тип: sizing/decision — сценарии и риск-менеджмент, без прямого buy/sell; "
            "если указана сумма ($50 и т.д.), отрази её в контексте риска и горизонта."
        )
    if is_event_question(question):
        hints.append(
            "Тип: event/regulatory — прямой торговый вывод по событию первым; relief vs decline корректно."
        )
    if not hints:
        hints.append(
            "Тип: general — развёрнутый прозаический ответ по формулировке вопроса с цифрами из "
            "ticker_analysis; не повторяй один и тот же вступительный абзац метрик и не своди "
            "ответ к шаблонному списку."
        )
    return " ".join(hints)


def format_senior_analyst_sections(sections: dict[str, str]) -> str:
    """Render [1]…[7] analyst structure for non-LLM fallback."""
    lines: list[str] = []
    for num, label in SENIOR_ANALYST_SECTION_LABELS:
        body = (sections.get(num) or sections.get(label) or "").strip()
        if not body:
            body = _DATA_MISSING_RU
        lines.append(f"[{num}] {label}")
        lines.append(body)
        lines.append("")
    return "\n".join(lines).strip()


def _question_match_tokens(question: str) -> list[str]:
    tokens: list[str] = []
    for word in re.findall(r"[\w\u0400-\u04ff]{3,}", question.lower()):
        if word not in _EVENT_STOPWORDS:
            tokens.append(word)
            tokens.extend(_TOKEN_ALIASES.get(word, ()))
    for proper in re.findall(r"[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*", question):
        tokens.append(proper.lower())
    return tokens


def has_question_matched_headline(question: str, headline: str) -> bool:
    """True only for a topical match, not just ticker/company overlap."""
    tokens = _question_match_tokens(question)
    if not tokens:
        return False
    lower = headline.lower()
    strong_tokens = [token for token in tokens if token not in _WEAK_MATCH_TOKENS]
    score = sum(1 for token in strong_tokens if token in lower)
    if is_corporate_geo_question(question):
        topic_tokens = [token for token in strong_tokens if token in _LOCATION_EVENT_TOKENS or len(token) >= 5]
        topic_hits = sum(1 for token in topic_tokens if token in lower)
        if any(token in _LOCATION_EVENT_TOKENS for token in strong_tokens):
            return topic_hits >= 1 and score >= 1
        return score >= 2
    return score >= 1


def headlines_matching_question(question: str, headlines: tuple[str, ...] | list[str]) -> list[str]:
    """Rank headlines by overlap with the user's event wording."""
    if not headlines:
        return []
    tokens = _question_match_tokens(question)
    if not tokens:
        if is_corporate_geo_question(question) or is_event_question(question):
            return []
        return list(headlines)[:3]
    scored: list[tuple[int, str]] = []
    for headline in headlines:
        lower = headline.lower()
        score = sum(1 for token in tokens if token not in _WEAK_MATCH_TOKENS and token in lower)
        if score and not has_question_matched_headline(question, headline):
            continue
        if score:
            scored.append((score, headline))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [headline for _, headline in scored]


def synthesize_event_answer(
    question: str,
    *,
    ticker: str,
    headlines: tuple[str, ...],
    outlook_line: str,
    model_outlook_appendix: str | None = None,
) -> str:
    """Plain-Russian lead paragraph for news/event questions (no metric dump)."""
    from app.services.chat.event_news_interpretation import interpret_event_news

    corp, ext, other = _bucket_headlines_for_display(headlines, cap=NEWS_HEADLINE_CAP, ticker=ticker)
    relevant = tuple(corp + ext)
    matched = headlines_matching_question(question, relevant)
    if not matched and not is_corporate_geo_question(question):
        matched = headlines_matching_question(question, headlines)

    interpretation = interpret_event_news(question=question, headlines=headlines, ticker=ticker)
    if interpretation:
        headline = matched[0] if matched else (headlines[0] if headlines else None)
        lead = interpretation.lead_paragraph_ru(ticker=ticker, headline=headline)
        if len(matched) > 1:
            lead += f" В ленте также: «{matched[1]}»."
        if model_outlook_appendix:
            lead += f" {model_outlook_appendix}"
        return lead

    if matched:
        lead = (
            f"По вашему вопросу: в данных анализа есть тематически совпадающий заголовок — «{matched[0]}». "
            f"Для {ticker} такие события обычно меняют новостной фон и краткосрочную волатильность. "
            f"{outlook_line}"
        )
        if len(matched) > 1:
            lead += f" Дополнительно в ленте: «{matched[1]}»."
        return lead

    return (
        f"Прямого заголовка по теме вопроса в текущем снимке {ticker} нет, поэтому новостную ленту "
        f"нельзя использовать как подтверждение события. Модель Quant Analytics остаётся основной опорой: {outlook_line}"
    )


def is_decision_question(question: str) -> bool:
    return bool(_DECISION_QUESTION.search(question))


def wants_full_breakdown(question: str) -> bool:
    if wants_brief_direct_answer(question):
        return False
    if _BRIEF_NEGATED_BREAKDOWN.search(question):
        return False
    return bool(_BREAKDOWN_QUESTION.search(question))


def has_repeated_substring(text: str, *, min_len: int = 50) -> bool:
    """True if any substring of length >= min_len appears more than once."""
    if not text or len(text) < min_len * 2:
        return False
    compact = re.sub(r"\s+", " ", text.strip())
    for length in range(min(len(compact) // 2, 400), min_len - 1, -1):
        seen: set[str] = set()
        for i in range(len(compact) - length + 1):
            chunk = compact[i : i + length]
            if len(chunk.strip()) < min_len:
                continue
            if chunk in seen:
                return True
            seen.add(chunk)
    return False


def is_simple_question(question: str) -> bool:
    """Rule 8 — short answer unless breakdown requested."""
    if wants_full_breakdown(question):
        return False
    if is_event_question(question):
        return False
    if _NEWS_EVENTS_QUESTION.search(question):
        return False
    if question.count("?") > 1:
        return False
    if len(question.split()) > 18:
        return False
    return True


def _bucket_headlines_for_display(
    news_titles: tuple[str, ...],
    *,
    cap: int = NEWS_HEADLINE_CAP,
    ticker: str = "",
) -> tuple[list[str], list[str], list[str]]:
    """Split headlines into corporate/financial, external/market, and low-weight other."""
    from app.services.news.entity_relevance import bucket_headline

    corporate: list[str] = []
    external: list[str] = []
    other: list[str] = []
    seen: set[str] = set()
    sym = ticker.strip().upper()
    for title in news_titles:
        key = title.strip().lower()[:120]
        if not key or key in seen:
            continue
        seen.add(key)

        if sym:
            bucket = bucket_headline(title, ticker=sym)
            if bucket == "corporate":
                corporate.append(title)
                continue
            if bucket == "macro":
                external.append(title)
                continue
            other.append(title)
            continue

        if _FINANCIAL_NEWS.search(title) and not _EXTERNAL_NEWS.search(title):
            corporate.append(title)
        elif _EXTERNAL_NEWS.search(title):
            external.append(title)
        else:
            corporate.append(title)
    total = len(corporate) + len(external)
    if total <= cap:
        return corporate, external, other
    corp_budget = max(1, (len(corporate) * cap) // total) if corporate else 0
    ext_budget = cap - corp_budget
    if not corporate:
        ext_budget = cap
    elif not external:
        corp_budget = cap
    return corporate[:corp_budget], external[:ext_budget], other


def mentions_shap(question: str) -> bool:
    return bool(_SHAP_QUESTION.search(question))


def log_shap_factor_mentions(
    *,
    ticker: str,
    question: str,
    factors: tuple[ShapFactor, ...],
) -> None:
    """Analytics log — which SHAP factors appear in advisor replies."""
    if not factors:
        return
    for factor in factors[:3]:
        logger.info(
            "advisor_shap_factor_mention",
            ticker=ticker,
            feature=factor.feature,
            contribution=round(factor.contribution, 4),
            question_preview=question[:120],
        )


def disclosure_needed(question: str, prior_messages: tuple[str, ...]) -> bool:
    """Rule 10 — disclosure once per conversation for decision questions."""
    if not is_decision_question(question):
        return False
    for prior in prior_messages:
        if DISCLOSURE_RU[:40] in prior or "не инвестиционная рекомендация" in prior.lower():
            return False
    return True


def format_news_from_payload(
    news_titles: tuple[str, ...],
    *,
    positive: int = 0,
    negative: int = 0,
    neutral: int = 0,
    avg_score: float | None = None,
    cap: int = NEWS_HEADLINE_CAP,
    ticker: str = "",
) -> str:
    """Rule 9 — list payload headlines in structured sections (no «+N more»)."""
    if not news_titles:
        return "В текущих данных анализа нет релевантных новостных заголовков."
    corporate, external, other = _bucket_headlines_for_display(news_titles, cap=cap, ticker=ticker)
    lines: list[str] = []
    if positive or negative or neutral:
        tone = f"Тональность ленты: позитивных {positive}, негативных {negative}, нейтральных {neutral}."
        if avg_score is not None:
            tone += f" Средний sentiment {avg_score:+.2f}."
        lines.append(tone)
    shown = len(corporate) + len(external)
    total_unique = len({t.strip().lower()[:120] for t in news_titles if t.strip()})
    if shown < total_unique:
        lines.append(f"Показаны {shown} из {total_unique} заголовков в данных (лимит {cap}).")
    if corporate:
        lines.append("Корпоративные и финансовые:")
        for idx, title in enumerate(corporate, start=1):
            lines.append(f"{idx}. «{title.strip()}»")
    if external:
        lines.append("Внешние и рыночные:")
        for idx, title in enumerate(external, start=1):
            lines.append(f"{idx}. «{title.strip()}»")
    if other:
        lines.append("Прочее (низкая связь с тикером):")
        for idx, title in enumerate(other[:5], start=1):
            lines.append(f"{idx}. «{title.strip()}»")
    if not corporate and not external:
        lines.append("Корпоративные и финансовые:")
        for idx, title in enumerate(news_titles[:cap], start=1):
            lines.append(f"{idx}. «{title.strip()}»")
    return "\n".join(lines)


ANTI_TEMPLATE_INSTRUCTIONS_RU = """
ANTI-TEMPLATE (обязательно для in-app chat «Сообщения»):
1. Начинай с самого decision-relevant инсайта для ЭТОГО вопроса — не используй фиксированную структуру «overview → details».
2. Меняй структуру opening sentence — никогда не начинай два ответа подряд одинаковой фразой.
3. Если tools вернули недостаточно или ambiguous data — скажи явно, не заполняй generic statement.
4. Не давай персонализированных buy/sell рекомендаций («тебе стоит купить X») — только анализ, сравнения, контекст.
5. Используй tools для получения данных — не выдумывай цифры.
6. Никогда не выводи сырые внутренние поля (score, confidence, regime label, ml_score) — только связный русский текст.
7. На вопросы про дивиденды/доходность вызывай get_dividend_data.

Примеры форм (чередуй, не копируй шаблон):
- Quick lookup: «Сейчас по SBER: цена X, momentum Y — кратко почему.»
- Comparison: «SBER vs VTBR: momentum сильнее у первого, но liquidity risk выше; ключевой spread…»
- Nuanced: «С одной стороны… с другой… доминирует X, потому что [data from tool].»
"""


def build_agentic_chat_system(*, mode: str = "instant") -> str:
    mode_note = (
        "Режим INSTANT: один-два tool call, короткий точный ответ."
        if mode == "instant"
        else "Режим THINKING: multi-step рассуждение, несколько tool calls, взвешивание tradeoffs."
    )
    return f"""{SENIOR_ANALYST_SYSTEM_RU}

{ANTI_TEMPLATE_INSTRUCTIONS_RU}

AGENTIC TOOLS: у тебя есть function calling — вызывай get_current_forecast,
get_portfolio_risk_metrics, get_position_pnl, search_instruments,
get_factor_exposures, get_dividend_data, compare_tickers, get_recent_news,
get_market_regime, get_macro_context когда нужны ЖИВЫЕ данные платформы.
Не опирайся на свои тренировочные знания о ценах, VaR или P&L.

CITE THE TOOL: каждое число из данных должно сопровождаться именем вызванного
tool и полем data_as_of / tool_called_at из JSON ответа.

{mode_note}

NUMERIC INTEGRITY: if any tool response has is_valid=false, insufficient_data=true,
validation_failed=true, data_available=false, error, or fabrication_forbidden=true,
state plainly that the specific data point is unavailable — never invent values
or a plausible-sounding number. If get_portfolio_risk_metrics fails, say so.

{RULE_NO_RECOMMENDATIONS}
{RULE_NO_RAW_INTERNAL_FIELDS}
"""
