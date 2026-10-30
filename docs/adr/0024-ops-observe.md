# ADR 0024 — OpenTelemetry SDK и самостоятельно размещаемый коллектор

Статус: принято 2026-10-08 (промпт 29, полоса 3).

## Контекст

Промпт 29 требует трассы, метрики и логи OpenTelemetry для FastAPI, SQLAlchemy, Celery, Redis, httpx и gRPC-клиента Т-Банка, плюс стек в бюджете памяти хоста 8 ГиБ (промпт 02). Пакеты `opentelemetry-instrumentation-*` на PyPI остаются линией `0.xxbN`.

## Решение

1. Стабильный SDK `opentelemetry-api` / `sdk` / `exporter-otlp-proto-http` **1.45.1**. Обёртки вызовов — в `app.services.ops_observe.otel`, без beta-instrumentation.
2. Коллектор `otel/opentelemetry-collector:0.111.0`, профиль compose `monitoring`, `mem_limit: 256m`, конфиг `infrastructure/monitoring/otel-collector.yaml`. Экспорт по умолчанию — `debug`. Существующие Prometheus/Grafana не дублируются вторым стеком.
3. Если `OTEL_EXPORTER_OTLP_ENDPOINT` пуст или коллектор недоступен, экспорт идёт в память процесса; запрос не падает.
4. Пороги p95 API 500 мс и отчёт 180 с — из текста промпта. Таймаут синхронизации, доступность, бэкап и оплата инфраструктуры остаются «нет данных» (OQ-29-2, OQ-29-3).
5. Тренировка runbook — `drill`, не боевой инцидент.

Откат: `FF_QA_OPS_OBSERVE=0`; профиль `monitoring` не поднимать.

Источники: https://opentelemetry.io/docs/languages/python/ ; https://pypi.org/project/opentelemetry-sdk/1.45.1/
