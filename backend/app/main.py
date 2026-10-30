"""
FastAPI application factory.
"""
from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import structlog
from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from opentelemetry import trace
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.safe_json_response import SafeJSONResponse

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.logging import get_logger, setup_logging
from app.core.security import hash_password
from app.db.models import User
from app.db.session import check_db_connection, engine, get_db

logger = get_logger(__name__)


class DevResetPasswordRequest(BaseModel):
    email: str
    new_password: str


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup and shutdown lifecycle hooks."""
    setup_logging()
    from app.core.http_proxy import configure_yfinance_proxy

    configure_yfinance_proxy()
    logger.info(
        "Starting Apex Intel API",
        version=settings.APP_VERSION,
        env=settings.APP_ENV.value,
        trading_mode="live" if settings.live_trading_unlocked else "paper",
    )

    try:
        await check_db_connection()
        logger.info("Database connected")
    except Exception as exc:
        logger.error("Database connection failed on startup", error=str(exc))

    if settings.QA_E2E_DEMO:
        from app.services.bonds.ingest import ensure_fixtures as load_bond_fixture
        from app.services.e2e_demo.seed import load_demo_market
        from app.services.factor_lens.ingest import rebuild_from_fixture

        loaded = load_demo_market()
        load_bond_fixture()
        rebuild_from_fixture()
        logger.info("e2e demo market loaded", **loaded)

    yield

    logger.info("Shutting down Apex Intel API")
    await engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(
        title="Apex Intel API",
        description="Private investment analytics system. Paper trading by default.",
        version=settings.APP_VERSION,
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        openapi_url="/openapi.json" if not settings.is_production else None,
        lifespan=lifespan,
        default_response_class=SafeJSONResponse,
    )

    # ── Middleware ────────────────────────────────────────────────────────────

    from app.middleware.csrf import CsrfMiddleware
    from app.middleware.security_headers import SecurityHeadersMiddleware

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(CsrfMiddleware)

    app.add_middleware(GZipMiddleware, minimum_size=1000)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.get_cors_origins(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-Request-ID",
            "X-CSRF-Token",
        ],
        expose_headers=["X-Request-ID", "X-Process-Time", "Retry-After"],
    )

    # ── Request logging & timing ──────────────────────────────────────────────

    @app.middleware("http")
    async def request_logging_middleware(request: Request, call_next) -> Response:
        start = time.perf_counter()
        request_id = request.headers.get("X-Request-ID", "")

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            method=request.method,
            path=request.url.path,
        )

        from app.services.ops_observe.otel import start_otel_span, setup as setup_otel
        from app.services.ops_observe.service import log_event, record_error, record_latency, start_span

        setup_otel()
        span = start_otel_span("http.request", request_id)
        span.set_attribute("http.method", request.method)
        span.set_attribute("url.path", request.url.path)
        start_span("http.request", request_id)
        try:
            response = await call_next(request)
        except Exception:
            record_error("unhandled")
            span.set_status(trace.Status(trace.StatusCode.ERROR))
            span.end()
            raise

        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        record_latency(elapsed_ms)
        log_event(request_id, "http", method=request.method, path=request.url.path)
        response.headers["X-Process-Time"] = f"{elapsed_ms}ms"
        if request_id:
            response.headers["X-Request-ID"] = request_id
        span.set_attribute("http.status_code", response.status_code)
        span.end()

        logger.info(
            "Request",
            status=response.status_code,
            duration_ms=elapsed_ms,
        )
        return response

    # ── Exception handlers ────────────────────────────────────────────────────

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(PermissionError)
    async def permission_error_handler(request: Request, exc: PermissionError) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    @app.exception_handler(Exception)
    async def generic_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.error("Unhandled exception", error=str(exc), exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    # ── Prometheus metrics ────────────────────────────────────────────────────

    from app.utils.metrics import setup_metrics
    setup_metrics(app)
    from app.services.ops_observe.otel import instrument_fastapi

    instrument_fastapi(app)

    # ── Routes ────────────────────────────────────────────────────────────────

    app.include_router(api_router, prefix=settings.API_PREFIX)
    from app.api.health_check_aliases import router as health_aliases_router

    app.include_router(health_aliases_router, prefix="/api")

    @app.get("/", include_in_schema=False)
    async def root():
        return {
            "name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "docs": "/docs",
            "health": f"{settings.API_PREFIX}/health",
        }

    # ── Dev endpoint: reset password (development only) ───────────────────────

    if not settings.is_production:

        @app.post(f"{settings.API_PREFIX}/auth/dev/reset-password", tags=["dev"])
        async def dev_reset_password(
            payload: DevResetPasswordRequest,
            db: AsyncSession = Depends(get_db),
        ):
            result = await db.execute(
                select(User).where(User.email == payload.email.lower())
            )
            user = result.scalar_one_or_none()

            if not user:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="User not found",
                )

            user.hashed_password = hash_password(payload.new_password)
            await db.commit()
            await db.refresh(user)

            return {"status": "ok", "email": user.email}

    return app


app = create_app()