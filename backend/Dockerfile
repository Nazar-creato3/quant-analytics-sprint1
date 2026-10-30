# ── Stage 1: dependency builder ───────────────────────────────────────────────
FROM python:3.13-slim AS builder

WORKDIR /build

RUN printf 'Acquire::Retries "5";\n' > /etc/apt/apt.conf.d/80-retries \
    && apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libpq-dev curl build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-trading-engines.txt requirements-trading-engines-nodeps.txt requirements-prod.constraints ./

# One resolve for the app and all trading engines, pinned by requirements-prod.constraints
# (uv: fast and light on RAM). Torch comes from the CPU index - no CUDA on the server;
# if that index is unreachable, fall back to the default PyPI wheel.
RUN pip install --upgrade pip \
    && pip install --no-cache-dir uv==0.11.21 \
    && (uv pip install --system --no-cache --torch-backend cpu \
          -r requirements.txt -r requirements-trading-engines.txt -c requirements-prod.constraints \
        || uv pip install --system --no-cache \
          -r requirements.txt -r requirements-trading-engines.txt -c requirements-prod.constraints) \
    && uv pip install --system --no-cache --no-deps -r requirements-trading-engines-nodeps.txt \
    && NUMBA_CACHE_DIR=/tmp/numba python -c "import greenlet, torch, darts, vectorbt, nautilus_trader, finrl, lumibot, stable_baselines3"


# ── Stage 2: runtime image ────────────────────────────────────────────────────
FROM python:3.13-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    MODEL_DIR=/app/models

WORKDIR /app

RUN printf 'Acquire::Retries "5";\n' > /etc/apt/apt.conf.d/80-retries \
    && apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && addgroup --system appgroup \
    && adduser --system --ingroup appgroup appuser

# Copy installed Python deps from builder.
COPY --from=builder /usr/local /usr/local

# Copy application code
COPY . .

# Seed models baked into the image; runtime volume may override /app/models
RUN mkdir -p /app/models /app/model_seeds
COPY model_seeds/ /app/model_seeds/
# Ensure empty seed dir does not break builds when only .gitkeep is present
RUN chown -R appuser:appgroup /app

USER appuser

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -f "http://127.0.0.1:${PORT:-8000}/api/v1/health/live" || exit 1

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 2 --loop uvloop --http h11"]


# ── Stage 3: CI / e2e runtime (single stage; no /usr/local copy) ─────────────
# Versions come from uv.lock via `uv export --frozen`. requirements-ci.txt is
# the install set (no torch). A missing lock pin fails this RUN, not container start.
# Single stage avoids Docker Desktop Lchown hangs on COPY --from=/usr/local.
# Live keys are not baked in.
FROM python:3.13-slim AS ci-runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    MODEL_DIR=/app/models \
    MPLCONFIGDIR=/tmp/matplotlib \
    XDG_CACHE_HOME=/tmp

WORKDIR /app

RUN printf 'Acquire::Retries "5";\n' > /etc/apt/apt.conf.d/80-retries \
    && apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libpq-dev curl build-essential libgomp1 util-linux \
    && rm -rf /var/lib/apt/lists/* \
    && addgroup --system appgroup \
    && adduser --system --ingroup appgroup appuser

COPY pyproject.toml uv.lock requirements-ci.txt requirements-backend-minimal.txt ./

RUN pip install --upgrade pip \
    && pip install --no-cache-dir uv==0.11.21 \
    && uv export --frozen --offline --no-emit-project --group ci --no-hashes -o /tmp/uv-export.txt \
    && grep -qi '^pandas==' /tmp/uv-export.txt \
    && grep -qi '^opentelemetry-sdk==' /tmp/uv-export.txt \
    && grep -qi '^quantstats==' /tmp/uv-export.txt \
    && grep -qi '^ipython==' /tmp/uv-export.txt \
    && uv pip install --system --no-cache -r requirements-ci.txt -c /tmp/uv-export.txt \
    && python -c "import pandas, quantstats, IPython, opentelemetry.sdk, matplotlib, seaborn, reportlab, openpyxl"

COPY . .
RUN mkdir -p /app/models /tmp/equity_eod /tmp/matplotlib \
    && chown -R appuser:appgroup /app /tmp/equity_eod /tmp/matplotlib

USER appuser

EXPOSE 8000

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
