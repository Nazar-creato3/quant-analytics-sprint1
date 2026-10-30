# ADR 0014 — uv.lock продукта и pip-audit без установки torch

Статус: принято как исполнение D-01-2 (вариант а), 2026-10-06. D-01-2 этим не закрыт.

## Контекст

Протокол качества требует lock uv. В репозитории уже был `backend/requirements-ci.lock` (`uv pip compile`, шаг 01A). Полный `backend/requirements.txt` содержит диапазоны и `torch`. `pip-audit --disable-pip` отказывается читать файл без хешей. Ставить torch и CUDA-колёса на GitHub-раннер нельзя.

Документация uv: проект и `uv.lock` живут рядом с `pyproject.toml` — https://docs.astral.sh/uv/concepts/projects/layout/ (раздел Projects, uv 0.11).

## Решение

Один менеджер: uv 0.11.21. Второй менеджер не добавляется.

- Прямые пины продукта остаются в `requirements.txt`. Их копия для `uv lock` — `[project].dependencies` в `backend/pyproject.toml`, группа `ci` — пакеты, которые есть только в `requirements-ci.txt` (`greenlet`, `testcontainers`, `pip-audit`).
- `requires-python` проекта lock: `>=3.13,<3.14`. Образ и CI — CPython 3.13.
- `backend/uv.lock` — транзитивный lock с хешами. Раннер его не устанавливает.
- CI Backend Tests по-прежнему ставит `requirements-ci.lock`. Шаг аудита: `uv export --frozen --offline --no-emit-project --group ci` и `pip-audit --disable-pip`. Экспорт с хешами удовлетворяет `--disable-pip` и не скачивает колёса.

Три строки `requirements.txt` в lock не вошли, версии не подменялись: `darts==0.30.0`, `mlflow==2.16.2`, `financetoolkit>=1.9.0`. Точные границы — OQ-01-2.

## Откат

Вернуть шаг CI на `pip-audit -r requirements-ci.txt`, удалить `backend/uv.lock` и вернуть прежний `backend/pyproject.toml`. `requirements.txt` этот PR не меняет.

## Последствия

Аудит разрешимого набора 2026-10-06 не чистый (42 записи, 8 пакетов). Игноры CVE не добавлялись. `python-jose` в lock нет.
