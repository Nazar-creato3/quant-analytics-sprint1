# ADR 0026 — Указатель уже принятых решений

Статус: принято 2026-10-07 (промпт 31). Этот файл ничего не меняет в расчётах.

## Контекст

Промпт 31 просит ADR по справочнику, трём рядам цен, календарю, VaR, шине, книге, риск-проверке, paper/live и фильтру формулировок. Часть решений уже записана. Новое решение здесь не выбирается.

## Указатель

| Тема | Где зафиксировано |
|---|---|
| Справочник | `backend/app/services/catalog` |
| Три ряда цен | `backend/app/services/market_data/series.py` |
| Календарь среза | [ADR 0008](0008-mixed-calendars.md) |
| Метод VaR | [risk.md](../methodology/risk.md), версия `risk_engine.fhs.v1` |
| Шина | `backend/app/services/event_bus` |
| Книга и paper/live | `backend/app/services/portfolio_book` |
| Риск-проверка | `backend/app/services/pretrade` |
| Фильтр формулировок | `backend/app/services/explanations` |

Отдельного ADR на справочник, три ряда, шину, книгу и фильтр формулировок до этого шага не было. Указатель не заменяет их текст. Карта и словарь: [core-map.md](../architecture/core-map.md), [entity-dictionary.md](../architecture/entity-dictionary.md).

Откат: удалить документы этого шага и путь `/methodology` из публичных маршрутов. Новых зависимостей нет.
