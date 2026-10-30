# Технологический стек — инвентаризация и цель (Промпт 00A)

Дата сверки: **2026-10-03**. Код продукта в этом промпте не менялся.  
«Последняя стабильная» — версия с официального индекса на эту дату.  
`redis` в таблице Python — пакет **redis-py**, не сервер Redis.

Статусы: `факт` | `цель (D-00A-1, 2026-10-03)` | `шаг 01A`.  
Порядок 01A: Next 16.3.8 → uv → FastAPI/Pydantic/Celery → Python (макс. 3.13/3.14 с колёсами) → PG18/Timescale → pandas 3. Каждый шаг — отдельный PR.

## Менеджеры пакетов и lock

| Что | Факт | Доказательство |
|---|---|---|
| Python deps | `backend/requirements.txt` + `requirements-ci.txt` (урезанный CI) | `backend/uv.lock` (uv 0.11.21, 2026-10-06). Раннер ставит `requirements-ci.lock`, не полный lock |
| T-Invest connector | `backend/connectors/requirements-tinkoff.txt` (`grpcio>=1.39,<2`, без pin SDK) | PyPI meta-package отключён комментарием |
| Frontend | npm, `frontend/package-lock.json` lockfileVersion 3 | есть lock |
| Локальный Python агента | 3.14.6 | `python --version` |
| CI / Docker backend | Python **3.13** | `.github/workflows/ci.yml` `PYTHON_VERSION: "3.13"`; `FROM python:3.13-slim` |
| Локальный Node агента | v24.18.0 | `node --version` |
| CI / Docker frontend | Node **20** | `NODE_VERSION: "20"`; `FROM node:20-alpine` |

## Таблица компонент

| Компонент | Текущая (репо) | Последняя стабильная (2026-10-03) | Целевая (предложение) | Обоснование | Источник | Статус |
|---|---|---|---|---|---|---|
| Python (runtime продукта) | **3.13** (Docker/CI, 01A-python) | 3.14 линия есть, колёс torch/asyncpg-0.30/psycopg2-2.9.10/hmmlearn нет | **3.13** | D-00A-1 п.5; numpy 1.26.4→2.2.6 (нет cp313) | https://pypi.org/project/numpy/1.26.4/ | **внедрено (01A-python)** |
| FastAPI | **0.142.2** | 0.142.2 | 0.142.2 | D-00A-1 шаг 3 | https://pypi.org/project/fastapi/0.142.2/ | **внедрено (01A-fastapi)** |
| Pydantic | **2.13.5** | 2.13.5 | 2.13.5 | settings 2.15.0 | https://pypi.org/project/pydantic/2.13.5/ | **внедрено (01A-fastapi)** |
| SQLAlchemy | 2.0.36 | 2.1.3 | 2.0.x до отдельного ADR; затем 2.1 | 2.1 — мажор внутри 2.x | https://pypi.org/project/sqlalchemy/ | не обновлять сейчас → 2.1 |
| Alembic | 1.13.3 | 1.20.0 | вместе с SQLAlchemy | совместимость миграций | https://pypi.org/project/alembic/ | предложение |
| Celery | **5.6.3** | 5.6.3 | 5.6.3 | changelog 5.6 | https://docs.celeryq.dev/en/stable/history/changelog-5.6.html | **внедрено (01A-fastapi)** |
| redis-py | 5.1.1 | 8.1.0 | 5.x или 6.x сначала, не прыжок на 8 | мажор 5→8 | https://pypi.org/project/redis/ | не обновлять сейчас на 8 |
| httpx | 0.27.2 | 0.28.1 | 0.28.1 | минор | https://pypi.org/project/httpx/ | предложение |
| pandas | **3.0.6** | 3.0.6 | 3.0.6 | D-00A-1; CoW + string dtype | https://pandas.pydata.org/docs/whatsnew/v3.0.6.html | **внедрено (01A-pandas)** |
| NumPy | **2.2.6** | 2.5.3 | 2.2.6 (cp313) | 01A-python; 2.5 не трогать в этом шаге | https://pypi.org/project/numpy/2.2.6/ | **внедрено (01A-python)** |
| scikit-learn | 1.5.2 | 1.9.1 | 01A после эталонов | модели/pickle | https://pypi.org/project/scikit-learn/ | не обновлять сейчас |
| skfolio | **0.6.0** | новее на PyPI требуют sklearn≥1.6 | 0.6.0 при sklearn 1.5.2 | BSD-3; пин 65. Импорт пакета на CPython 3.13 ломает `skfolio.typing` × cvxpy (`cp.trace`); расчёт LW — sklearn до ADR на sklearn 1.6+ | https://pypi.org/project/skfolio/0.6.0/ | **внедрено (65)** |
| LightGBM | **4.6.0** (D-01-2 CVE review 2026-10-11; PYSEC-2024-231) | 4.7.0 | 4.7 после колёс на целевом Python | https://pypi.org/project/lightgbm/ | внедрено 4.6.0 |
| MAPIE | 0.9.0 | 1.5.0 | 1.x для 11B | набор 11B | https://pypi.org/project/mapie/ | предложение (11B) |
| SciPy | 1.18.1 в uv.lock | — | не добавлять прямой пин: уже зависимость scikit-learn 1.5.2 | SLSQP и HiGHS, ADR 0015; cvxpy не добавлялся | https://docs.scipy.org/doc/scipy/reference/optimize.html | транзитивная, промпт 36 |
| XGBoost | нет | — | не добавлять без ADR | — | — | факт |
| QuantLib | нет в lock (C++ wheel на CPython 3.13 не ставился) | 1.36+ | формулы Actual/365F в `bonds.analytics`; QuantLib — если появится колесо | https://www.quantlib.org/ | 56, без нового pin |
| T-Invest | grpcio unpinned range; REST без SDK в app | актуальный gRPC — сверять developer.tbank.ru | pin grpcio + app_name из Settings | https://developer.tbank.ru/invest/intro/developer/protocols/grpc | предложение pin |
| PostgreSQL + Timescale | **`timescale/timescaledb:2.30.2-pg18`** | 2.30.2-pg18 | пин 2.30.2-pg18 | D-00A-1 п.3; https://hub.docker.com/r/timescale/timescaledb/tags | **внедрено (01A-pg18)** |
| Redis server | `redis:7-alpine` | 8.2 ориентир набора | остаться на 7.x pin; 8.2 после ADR | https://redis.io/docs/ | не обновлять сейчас |
| Next.js | **16.3.8** (ветка 01A-next) | 16.3.8 | 16.3.8 | D-00A-1 п.1; https://nextjs.org/blog/september-2026-security-release | **в этом PR** |
| React | **19.2.0** (ветка 01A-next) | 19.2 линия | вместе с Next 16 | https://react.dev | **в этом PR** |
| Tailwind | 3.4.14 | v4 ориентир | v3 до отдельного PR | ломающий v4 | https://tailwindcss.com | не обновлять сейчас |
| TanStack Query | 5.59.0 | 5.x latest не снимался отдельным запросом | остаться на v5 | уже v5 | факт |
| Zustand | 5.0.0 | — | оставить | — | факт |
| Графики | lightweight-charts ^4.2.2 (OHLC); recharts 2.12.7 (не цена) | — | **одна** OHLC-библиотека | ADR 0010 | **внедрено (промпт 42)** |
| Playwright | `e2e/@playwright/test` 1.55.1 | — | e2e gate | `e2e/package.json` | факт |
| Lighthouse CI | нет в lock продукта | 0.14.x | только CI `npx @lhci/cli@0.14.0` (ADR 0027) | https://github.com/GoogleChrome/lighthouse-ci | внедрено (промпт 47, не зависимость приложения) |
| OTel | **opentelemetry-api/sdk/exporter-otlp-proto-http 1.45.1** | 1.45.1 (PyPI 2026-10-08) | 1.45.1; без `instrumentation-*` 0.xxbN | промпт 29; обёртки FastAPI/SQLAlchemy/Celery/Redis/httpx/gRPC в `ops_observe.otel`; коллектор `otel/opentelemetry-collector:0.111.0`, 256 MiB | https://pypi.org/project/opentelemetry-sdk/1.45.1/ | **внедрено (промпт 29)** |
| uv | **0.11.21**, `backend/uv.lock` + `requirements-ci.lock` | 0.11.21 (локально 2026-10-06) | lock продукта — `uv lock`; CI install — `requirements-ci.lock` | https://docs.astral.sh/uv/concepts/projects/layout/ | **uv.lock есть; три пина не вошли (D-01-2)** |
| JWT сессий | **PyJWT 2.15.1** | 2.15.1 (pip index 2026-10-06) | 2.15.1 | D-01-1/D-01-3; python-jose снят | https://pyjwt.readthedocs.io/en/2.15.1/usage.html | **внедрено** |
| ruff / mypy | CI: ruff+mypy на 2 файлах account | — | расширять в 01 | `ci.yml` | факт |
| ty (Astral) | нет | бета | **не** в обязательный CI | набор 00A | не обновлять |

## Уязвимости

`pip-audit` и `npm audit` **в прогоне 00A не выполнены**. Зафиксировано: OPEN_QUESTIONS OQ-00A-1. Next 14.2.35 отстаёт от security-релиза 16.3.8 / 15.5.27 — риск известен по блогу Next, не по локальному npm audit того дня.

2026-10-11: `backend/uv.lock` — `torch==2.14.1` (`>=2.13,<3`), `transformers==5.19.0`, `chronos-forecasting==2.3.2`, `pytest==9.0.3` / `pytest-asyncio==1.4.0`, `ccxt==4.5.64` (`<4.5.65` из‑за pin multidict), `multidict==6.9.1`. CI-path `pip-audit --disable-pip`: **0 findings**. Полный `requirements.txt` по-прежнему не решается одной средой для `darts` / `mlflow` / `financetoolkit` (OQ-01-2).

## Что реально запускалось 2026-10-03

```
python --version          → Python 3.14.6
node --version            → v24.18.0
pytest app/tests/test_baseline_guards.py -q
                          → 10 passed, 371 warnings in 2.48s
```

Полный `pytest app/tests`, `npm test`, `npm run build`, `ruff check app` — **не прогнаны** в 00A (объём / время). CI на `main` после #45 был зелёный (7 checks).

## План обновления (для 01A, после утверждения)

Порядок от низкого риска к высокому:

1. `uv` + lock из текущего pin (поведение то же). Ломается: инструкции pip. Проверка: тот же pytest CI.
2. Pin образа Timescale (убрать `:latest-pg15`). Ломается: только если latest уже уехал. Проверка: compose up + alembic на копии.
3. FastAPI/Pydantic/httpx/Celery минор-мажор внутри совместимости. Ломается: OpenAPI, валидация, задачи. Проверка: backend tests + compileall.
4. Next security line (16.3.8) + React 19 — отдельный крупный PR. Ломается: App Router, eslint-config-next. Проверка: `npm run build`, vitest, e2e.
5. Python 3.12 в Docker/CI. Ломается: колёса torch/lgbm. Проверка: image build.
6. pandas 3.0.6 — внедрён в 01A-pandas (до VitR 01B: ядро VaR на numpy; эталоны 01B остаются обязательными).
7. PG18 + Timescale 2.30.2 — внедрён в 01A-pg18 на новом томе; dump пользователей нет.
8. Нельзя сейчас: live-флаги; PG18 на данных пользователей; ty в CI; Python 3.14 в образе; Redis 8 server; SQLAlchemy 2.1 пакетом с 01A шагом 1.

Каждый крупный шаг — отдельный PR внутри 01A.
