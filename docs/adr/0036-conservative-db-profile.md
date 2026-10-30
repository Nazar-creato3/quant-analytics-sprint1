# ADR 0036 — Conservative DB profile for the old server

Статус: принято 2026-10-08 (решение основателя).

## Контекст

Текущий сервер ограничен по RAM/CPU. Агрессивные настройки PostgreSQL
и Timescale ухудшают стабильность беты.

## Решение

1. Профиль `conservative` по умолчанию на старом сервере:
   - `shared_buffers` ≤ 256MB
   - `work_mem` ≤ 16MB
   - `max_parallel_workers_per_gather` = 0
   - Timescale hypertable DDL пропускается, если расширение отсутствует.
2. Профиль `standard` — только после переезда и явной команды основателя.
3. Миграции не должны падать без Timescale.

Откат: вернуть `standard` в compose/env после переезда.
