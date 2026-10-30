# ── Stage 1: dependency builder ───────────────────────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ libpq-dev curl build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-trading-engines.txt ./

# Install deps in the builder stage and copy the resulting Python runtime
# environment into the final image. This avoids copying a large /wheels
# directory across stages, which can trigger Docker Desktop/containerd
# snapshotter issues on some hosts (seen as: "failed to Lchown ... no such file or directory").
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt \
    && (pip install --no-cache-dir -r requirements-trading-engines.txt \
        || echo "optional trading engines skipped (dependency conflict)")


# ── Stage 2: runtime image ────────────────────────────────────────────────────
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    MODEL_DIR=/app/models

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
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
