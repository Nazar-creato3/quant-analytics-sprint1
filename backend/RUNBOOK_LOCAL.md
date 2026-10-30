# Локальный запуск Apex Intel (Windows / PowerShell)

Единый порядок ежедневного запуска, чтобы работали **живые новости** и
**маневры** (а не демо-данные). Все команды — из PowerShell.

> Ключевой принцип: **backend (uvicorn) и Celery worker запускаются из одного и
> того же Python 3.11 venv** (`backend/.venv-grid-bot-min2`) и **из папки
> `backend/`**. На Python 3.14 numpy/pandas/scikit-learn/lightgbm не ставятся —
> поэтому worker падал на `import numpy`.

---

## 0. Однократная подготовка venv (один раз)

```powershell
cd C:\Users\B.I.G\Desktop\quant_analytics\кванткод2\apex-intel\backend

# Полный стек для worker + pipeline (numpy/pandas/sklearn/lightgbm + celery + httpx)
.\.venv-grid-bot-min2\Scripts\python.exe -m pip install -r requirements-backend-minimal.txt
.\.venv-grid-bot-min2\Scripts\python.exe -m pip install -r requirements-pipeline.txt
```

Проверка, что тяжёлые зависимости встали:

```powershell
.\.venv-grid-bot-min2\Scripts\python.exe -c "import numpy, pandas, sklearn, lightgbm, celery, httpx; print('deps OK')"
```

---

## 1. Redis (Docker) — брокер задач Celery

Сейчас Redis **не запущен** (health показывает `redis: error`, порт 6379 не
слушается). Без Redis Celery не примет ни одной задачи. Запуск:

```powershell
docker run -d --name apex-redis -p 6379:6379 redis:7-alpine
# проверка
docker exec apex-redis redis-cli ping   # -> PONG
```

## 2. Postgres (Docker)

```powershell
cd C:\Users\B.I.G\Desktop\quant_analytics\кванткод2\apex-intel
docker compose -f docker-compose.local.yml up -d postgres
```

Миграции (один раз после чистой БД), из `backend/`:

```powershell
cd backend
.\scripts\run_migrate.ps1
```

## 3. Backend API (uvicorn) — из venv, из папки backend

```powershell
cd C:\Users\B.I.G\Desktop\quant_analytics\кванткод2\apex-intel\backend
.\.venv-grid-bot-min2\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Проверка здоровья (в новом окне):

```powershell
curl.exe -s http://localhost:8000/api/v1/health
# ожидаем: "db":"ok" и "redis":"ok"
```

## 4. Celery worker — из ТОГО ЖЕ venv, из папки backend

Важно: указываем `--pool=solo` (обязательно на Windows) и **все очереди**
через `-Q` — иначе задачи новостей/пайплайна не будут потребляться (они
маршрутизируются в очереди `ingestion` и `pipeline`, а не в `celery`).

```powershell
cd C:\Users\B.I.G\Desktop\quant_analytics\кванткод2\apex-intel\backend
.\.venv-grid-bot-min2\Scripts\python.exe -m celery -A app.tasks.celery_app worker `
    --pool=solo -l info -Q pipeline,execution,backtest,ingestion,celery
```

В логе worker при старте должно быть (без ошибок `ModuleNotFoundError`):

```
[tasks]
  . app.tasks.data_ingestion.ingest_news_task
  . app.tasks.pipeline.run_pipeline_task
  ...
celery@... ready.
```

---

## 5. Проверка, что новости и маневры «живые»

```powershell
# 1) Новости: дернуть загрузку (нужен валидный access_token в cookie/Bearer)
#    Проще — из UI: панель "Economic News" сама триггерит /news/fetch.

# 2) Убедиться, что worker выполнил задачу — смотрим лог worker:
#    "News ingestion complete articles=<N>"

# 3) Маневры: запустить пайплайн из UI (или POST /api/v1/pipeline/run),
#    в логе worker: "Pipeline complete ... maneuvers=10"
```

Быстрая проверка содержимого БД (число статей/отчётов) без UI — сохраните в
`backend/_counts.py` и запустите:

```python
import asyncio
from sqlalchemy import func, select
from app.db.session import AsyncSessionLocal
from app.db.models import NewsArticle, ManeuverReport

async def main():
    async with AsyncSessionLocal() as s:
        na = (await s.execute(select(func.count()).select_from(NewsArticle))).scalar_one()
        mr = (await s.execute(select(func.count()).select_from(ManeuverReport))).scalar_one()
        print("news_articles =", na, "| maneuver_reports =", mr)

asyncio.run(main())
```

```powershell
cd C:\Users\B.I.G\Desktop\quant_analytics\кванткод2\apex-intel\backend
.\.venv-grid-bot-min2\Scripts\python.exe _counts.py
```

(Либо просто ориентируйтесь по логам worker — они пишут итог каждой задачи:
`News ingestion complete articles=<N>`, `Pipeline complete ... maneuvers=10`.)

---

## Частые причины «всё ещё демо / 503»

| Симптом | Причина | Решение |
|---|---|---|
| `redis: error` в /health | Redis не запущен | Шаг 1 (docker run redis) |
| Worker падает `ModuleNotFoundError: numpy` | worker запущен на глобальном Python 3.14 | Запускать worker из venv 3.11 (шаг 4) + `requirements-pipeline.txt` |
| `/news/fetch` → 503 | Celery брокер (Redis) недоступен | Шаг 1 |
| Задачи «висят», не выполняются | worker без `-Q ingestion,pipeline,...` слушает только `celery` | Добавить `-Q` (шаг 4) |
| Новости пустые, `NEWS_API_KEY` в backend/.env | (ИСПРАВЛЕНО) Settings теперь грузит backend/.env при любом cwd | — |
| Новости пустые, ключ валиден, `totalResults=0` | (ИСПРАВЛЕНО) NewsAPI free-tier задержка ~24ч + окно 24ч. Теперь окно 72ч + fallback без `from` | — |
| pipeline → "No market data" / `Expecting value: line 1 column 1` | старый yfinance 0.2.x сломан о новый Yahoo crumb/cookie | (ИСПРАВЛЕНО) `yfinance==1.5.1` + `curl_cffi` — переустановить `requirements-pipeline.txt` |
| pipeline → "ML deps not installed" | numpy/pandas/sklearn/lightgbm не установлены | `pip install -r requirements-pipeline.txt` в venv |

---

## Заметка про `.env` (исправлено в коде)

`app/core/config.py` раньше читал `.env` относительно текущей папки. Если процесс
стартовал из корня репозитория — читался корневой `.env` (без `NEWS_API_KEY`), и
новости оставались демо. Теперь Settings всегда читает **и** корневой `.env`,
**и** `backend/.env` по абсолютным путям, причём `backend/.env` имеет приоритет.
То есть `NEWS_API_KEY` из `backend/.env` подхватывается независимо от того,
откуда запущен uvicorn/celery. Реальные переменные окружения (OS env) по-прежнему
имеют наивысший приоритет.
