# Каталог сервисов

Промпт 31. Список пакетов, которые уже есть в репозитории. Описание не заменяет код.

| Пакет | Роль |
|---|---|
| `backend/app/services/catalog` | Справочник инструмента и признак доступности сделки |
| `backend/app/services/market_data` | Официальное закрытие и три ряда цен |
| `backend/app/services/portfolio_book` | Счета, операции, позиции, раздельно paper и live |
| `backend/app/services/returns` | Доходность по книге |
| `backend/app/services/benchmark_alt` | K1: RGBITR и денежный рынок на тех же потоках |
| `backend/app/services/risk_engine` | Риск, основной метод FHS |
| `backend/app/services/pretrade` | Одна проверка перед действием с деньгами |
| `backend/app/services/event_bus` | События между сервисами |
| `backend/app/services/forecast_core` | Прогноз по ряду, без ряда — нет данных |
| `backend/app/services/market_regime` | Метка режима рынка |
| `backend/app/services/explanations` | Тексты и фильтр формулировок |
| `backend/app/services/order_machine` | Состояния заявки, live не отправляет |
| `backend/app/services/bot_core` | Бумажный бот в книгу |
| `backend/app/services/subscription_billing` | Доступ без утверждённой цены |
| `backend/app/services/partners` | Партнёрский путь выключен |
| `backend/app/services/ops_observe` | Алерты, последнее известное значение, OpenTelemetry |
| `backend/app/services/perf_budget` | Бюджет 200×20 и 1000 сессий in-process |
| `backend/app/services/concentration` | Концентрация |
| `backend/app/services/model_risk` | Риск модели |
| `backend/app/services/investment_profile` | Анкета и лимиты |
| `backend/app/services/target_portfolio` | Целевая книга |
| `backend/app/services/bots` | Grid, DCA, momentum |

Старые grid, DCA и momentum в `backend/app/services/bots` остаются отдельно от `bot_core`.
