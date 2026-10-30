# Словарь сущностей

Промпт 31. У каждой сущности один источник. Если факта нет, пишется «нет данных».

| Сущность | Источник | Не делать |
|---|---|---|
| Инструмент | `backend/app/services/catalog` | Не заводить второй справочник в разделе |
| Цена оценки | `backend/app/services/market_data/eod.py` | Не подставлять последнюю сделку вместо официального закрытия |
| Три ряда | `backend/app/services/market_data/series.py` | Виды: raw, split_adj, total_return |
| Позиция | `backend/app/services/portfolio_book` | Не копировать позицию в боте или отчёте |
| Доходность | `backend/app/services/returns` | Методика: [returns.md](../methodology/returns.md) |
| Простая альтернатива | `backend/app/services/benchmark_alt` | Методика: [k1-simple-alternative.md](../methodology/k1-simple-alternative.md) |
| Риск | `backend/app/services/risk_engine` | Методика: [risk.md](../methodology/risk.md) |
| Прогноз | `backend/app/services/forecast_core` | Без ряда число не ставится |
| Режим | `backend/app/services/market_regime` | Метки trend_up, trend_down, range, high_vol, low_vol, unknown |
| Календарь среза | [ADR 0008](../adr/0008-mixed-calendars.md) | Срез 23:50 UTC, праздник площадки |
| Paper и live | книга, поле mode | Режимы не смешиваются. Live выключен |

Матрица потребителей: [WIRING_MATRIX.md](../qa/WIRING_MATRIX.md).
