# Карта модуля: котировки и графики (Промпт 42)

| Поверхность | Источник | Лицензия / свежесть | Дубли запросов |
|---|---|---|---|
| `GET /market/quote/{ticker}` | `get_latest_quote_resolved` | `stamp_quote` → `license_tag`, `freshness_label` | watchlist React Query per ticker; сервер — `QuoteHub` на WS |
| `GET /market/quote-envelope` | сервис 04 | всегда `license_tag` + метка свежести | тестовый/юридический конверт |
| `GET /market/overview` | EOD / Stooq / Yahoo | теги на каждой строке группы | один overview cache |
| `GET /market/bars/{ticker}` | сервис 04 / провайдер | свечи; `adjust=split_adj` через `adjust_ohlc` | Redis TTL |
| `POST /market/indicators` | те же бары, формулы сервера | эталоны `docs/qa/golden/indicators.json` | один расчёт, не браузер |
| `/ws/prices` | `QuoteHub.fetch_many` | теги на каждом значении | один in-flight на набор тикеров |
| `/ws/cockpit` | quote client | теги | один канал `cockpit:{SYM}` |
| Стакан / лента | terminal providers | матрица 04 | не дублировать REST при открытом WS |
| Frontend OHLC | lightweight-charts (ADR 0010) | атрибуция TradingView | индикаторы только с `POST /market/indicators` |
