# Метрики основателя

Расчёт: `docs/analytics/metrics.md` и `metrics.sql`.

Пустая страница `/admin/analytics` не подставляет долю. Ответ `GET /analytics/metrics` на пустом хранилище — «нет данных».

Сводка `GET /analytics/weekly` не содержит почту и не вызывает Slack.
