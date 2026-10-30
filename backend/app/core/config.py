from __future__ import annotations

"""
Core configuration management using Pydantic Settings v2.
All settings read from environment variables with strong typing and validation.
"""

import ipaddress
import os
import secrets
from enum import Enum
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

from pydantic import (
    AnyHttpUrl,
    Field,
    computed_field,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppEnv(str, Enum):
    DEVELOPMENT = "development"
    STAGING = "staging"
    PRODUCTION = "production"


class MarketDataProvider(str, Enum):
    ALPACA = "alpaca"
    POLYGON = "polygon"
    TWELVEDATA = "twelvedata"
    TIINGO = "tiingo"
    MARKETSTACK = "marketstack"
    FINNHUB = "finnhub"
    YFINANCE = "yfinance"


class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


# Known weak/default secrets — rejected when APP_ENV=production.
_WEAK_SECRET_KEYS: frozenset[str] = frozenset(
    {
        "changeme",
        "secret",
        "password",
        "test",
        "dev",
        "your-secret-key-here",
        "supersecret",
        "apex_pass",
        "changeme123",
        "ci-test-secret-key-32chars-minimum",
    }
)


# Resolve .env locations with absolute paths so settings load identically no
# matter which directory uvicorn / celery / pytest is launched from. Without
# this, `env_file=".env"` resolves against the current working directory: when
# a process starts from the repo root it reads the root .env and silently
# misses keys (e.g. NEWS_API_KEY) that only live in backend/.env.
# backend/app/core/config.py -> parents[2] == backend/, parents[3] == repo root.
_BACKEND_DIR = Path(__file__).resolve().parents[2]
_REPO_ROOT = _BACKEND_DIR.parent

# Order matters: later files override earlier ones in pydantic-settings, so
# backend/.env is the canonical per-service config and takes precedence over a
# root .env. Real OS environment variables still override both.
_ENV_FILES = (
    _REPO_ROOT / ".env",
    _BACKEND_DIR / ".env",
    _BACKEND_DIR / ".env.alpaca.local",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────────
    APP_NAME: str = "apex-intel"
    APP_ENV: AppEnv = AppEnv.DEVELOPMENT
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = False
    # qa-e2e stack only. Default off. Does not enable live trading.
    QA_E2E_DEMO: bool = False
    LOG_LEVEL: LogLevel = LogLevel.INFO
    SECRET_KEY: str = Field(default_factory=lambda: secrets.token_hex(32))
    API_PREFIX: str = "/api/v1"

    # ── Public domain / CORS ───────────────────────────────────
    # Used to build default CORS allowlist in production (http + https).
    DOMAIN: str = ""
    # Optional comma-separated extra origins, e.g. https://staging.example.com
    CORS_ORIGINS: str = ""

    # ── Auth ─────────────────────────────────────────────────
    WHITELIST_EMAILS: str = ""
    # Origination: when true, login is allowed without whitelist (dev/staging).
    # Production stays false: anyone can self-register, login after admissions approval.
    OPEN_REGISTRATION: bool = False
    # Allow multiple accounts per device when any account is already bound (dev/admin workstations).
    ALLOW_MULTI_ACCOUNT_DEVICES: bool = False
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    ALGORITHM: str = "HS256"
    PASSWORD_DEV_PLAIN: bool = False
    MFA_REQUIRED: bool = False
    SECURITY_HEADERS_ENABLED: bool = True
    HSTS_MAX_AGE_SECONDS: int = 31_536_000
    CONTENT_SECURITY_POLICY: str = (
        "default-src 'self'; frame-ancestors 'none'; base-uri 'self'; "
        "object-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'"
    )
    CSRF_PROTECTION_ENABLED: bool = False
    CSRF_COOKIE_NAME: str = "apex_csrf"
    CSRF_HEADER_NAME: str = "X-CSRF-Token"
    SECRETS_BACKEND: str = "env"
    TINKOFF_APP_NAME: str = "QuantAnalytics"
    HOSTING_PAID_UNTIL: str = ""  # ISO date; empty = unknown (Prompt 02 quota)
    VAULT_ADDR: str = ""
    VAULT_TOKEN: str = ""
    VAULT_SECRET_PATH: str = "secret/data/apex-intel"
    FIELD_ENCRYPTION_KEY: str = ""
    BROKER_RATE_LIMIT_PER_MINUTE: int = 30

    # ── Application / paywall flow ───────────────────────────
    TURNSTILE_SITE_KEY: str = ""
    TURNSTILE_SECRET_KEY: str = ""
    SMS_PROVIDER: str = "stub"  # stub | twilio | smsru
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_FROM_NUMBER: str = ""
    SMSRU_API_KEY: str = ""
    # Sign-in requires a confirmed Russian mobile number (149-FZ art. 10.6, KoAP 13.55).
    PHONE_SIGNIN_REQUIRED: bool = True
    # Wake-up tier: Twilio voice/SMS to these E.164 numbers (comma-separated).
    CRITICAL_ESCALATION_PHONES: str = ""
    # voice | sms | both — voice is default (harder to sleep through).
    CRITICAL_ESCALATION_MODE: str = "voice"
    # Min seconds between repeat wake-up calls for the same condition.
    CRITICAL_ESCALATION_COOLDOWN_SECONDS: int = 900
    EMAIL_VERIFICATION_BASE_URL: str = "http://localhost:3000"
    EMAIL_PROVIDER: str = "stub"
    EMAIL_PRIMARY_PROVIDER: str = "stub"
    EMAIL_SECONDARY_PROVIDER: str = ""
    EMAIL_FROM_ADDRESS: str = "noreply@apex-intel.local"
    EMAIL_FROM_NAME: str = "Apex Intel"
    UNISENDER_API_KEY: str = ""
    UNISENDER_API_URL: str = "https://goapi.unisender.ru/ru/transactional/api/v1"
    SENDGRID_API_KEY: str = ""
    SENDGRID_WEBHOOK_SECRET: str = ""
    POSTMARK_SERVER_TOKEN: str = ""
    POSTMARK_MESSAGE_STREAM: str = "outbound"
    POSTMARK_WEBHOOK_SECRET: str = ""
    AWS_SES_REGION: str = ""
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""
    REQUIRE_EMAIL_VERIFICATION: bool = False
    RECOVERY_RATE_LIMIT_PER_EMAIL: int = 3
    RECOVERY_RATE_LIMIT_PER_IP: int = 10
    RECOVERY_RATE_LIMIT_WINDOW_SECONDS: int = 3600
    VERIFICATION_RATE_LIMIT_PER_EMAIL: int = 3
    VERIFICATION_RATE_LIMIT_WINDOW_SECONDS: int = 3600
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    DISPOSABLE_EMAIL_DOMAINS: str = ""
    PAYMENT_WEBHOOK_SECRET: str = ""
    YOOKASSA_SHOP_ID: str = ""
    YOOKASSA_SECRET_KEY: str = ""
    YOOKASSA_RETURN_URL: str = ""
    SUBSCRIPTION_AMOUNT_RUB: str = "9900.00"
    WEBAUTHN_RP_ID: str = "localhost"
    WEBAUTHN_RP_NAME: str = "Apex Intel"
    WEBAUTHN_ORIGIN: str = "http://localhost:3000"
    APPLICATION_RATE_LIMIT_IP: int = 10
    APPLICATION_RATE_LIMIT_PHONE: int = 1
    APPLICATION_RATE_WINDOW_SECONDS: int = 86400

    # ── Twenty CRM (application origination sync) ─────────────
    TWENTY_API_URL: str = ""
    TWENTY_API_KEY: str = ""
    TWENTY_WORKSPACE_ID: str = ""
    # Failed password attempts per email+IP pair (WebAuthn retries are not counted).
    LOGIN_RATE_LIMIT_MAX_FAILURES: int = 10
    LOGIN_RATE_LIMIT_WINDOW_SECONDS: int = 300
    # Per-email ceiling across IPs (distributed password guessing).
    LOGIN_RATE_LIMIT_MAX_FAILURES_PER_EMAIL: int = 12
    # Comma-separated CIDRs for reverse proxies that may set X-Forwarded-For.
    TRUSTED_PROXY_CIDRS: str = (
        "127.0.0.1/32,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"
    )

    # ── Database ─────────────────────────────────────────────
    POSTGRES_HOST: str = os.getenv("POSTGRES_HOST", "localhost")
    POSTGRES_PORT: int = int(os.getenv("POSTGRES_PORT", 5432))
    POSTGRES_DB: str = os.getenv("POSTGRES_DB", "apex_intel")
    # Superuser / migration role (alembic only — never app runtime).
    POSTGRES_USER: str = os.getenv("POSTGRES_USER", "apex_user")
    POSTGRES_PASSWORD: str = os.getenv("POSTGRES_PASSWORD", "apex_pass")
    # Application role subject to RLS (backend + celery runtime).
    APP_DB_USER: str = os.getenv("APP_DB_USER", "appuser")
    APP_DB_PASSWORD: str = os.getenv(
        "APP_DB_PASSWORD", os.getenv("POSTGRES_PASSWORD", "apex_pass")
    )
    DB_POOL_SIZE: int = int(os.getenv("DB_POOL_SIZE", 10))
    DB_MAX_OVERFLOW: int = int(os.getenv("DB_MAX_OVERFLOW", 20))
    DB_POOL_TIMEOUT: int = int(os.getenv("DB_POOL_TIMEOUT", 30))

    @computed_field  # type: ignore[prop-decorator]
    @property
    def DATABASE_URL(self) -> str:
        """Async driver URL for the application runtime."""
        # если в окружении явно задана DATABASE_URL — используем её
        env_url = os.getenv("DATABASE_URL")
        if env_url:
            return env_url

        user = quote_plus(self.APP_DB_USER)
        password = quote_plus(self.APP_DB_PASSWORD)
        return (
            f"postgresql+asyncpg://{user}:{password}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def DATABASE_URL_SYNC(self) -> str:
        """Sync driver URL for application runtime."""
        env_url = os.getenv("DATABASE_URL_SYNC")
        if env_url:
            return env_url

        user = quote_plus(self.APP_DB_USER)
        password = quote_plus(self.APP_DB_PASSWORD)
        return (
            f"postgresql://{user}:{password}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def MIGRATION_DATABASE_URL_SYNC(self) -> str:
        """Sync URL for Alembic migrations (apex superuser)."""
        env_url = os.getenv("MIGRATION_DATABASE_URL_SYNC")
        if env_url:
            return env_url

        user = quote_plus(self.POSTGRES_USER)
        password = quote_plus(self.POSTGRES_PASSWORD)
        return (
            f"postgresql://{user}:{password}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    # ── Redis ────────────────────────────────────────────────
    REDIS_URL: str = "redis://redis:6379/0"
    CELERY_BROKER_URL: str = "redis://redis:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://redis:6379/2"
    CACHE_TTL_SECONDS: int = 300
    MARKET_GRAPH_CACHE_TTL_SECONDS: int = 300
    MARKET_GRAPH_CORRELATION_WINDOW: int = 60
    MARKET_GRAPH_MIN_REBUILD_INTERVAL_SECONDS: int = 300
    MARKET_GRAPH_NEWS_IMPACT_LOOKBACK_HOURS: int = 72

    # ── Market Data ──────────────────────────────────────────
    # Preferred primary for get_market_data_client(); quote/bar resolvers still
    # walk the full keyed chain (Alpaca→Polygon→TwelveData→Tiingo→MarketStack→
    # Finnhub→yfinance) when keys are present.
    MARKET_DATA_PROVIDER: MarketDataProvider = MarketDataProvider.ALPACA
    ALPACA_API_KEY: str = ""
    ALPACA_SECRET_KEY: str = ""
    ALPACA_BASE_URL: AnyHttpUrl = "https://paper-api.alpaca.markets"  # type: ignore
    BYBIT_API_BASE_URL: str = "https://api.bybit.com"
    BYBIT_API_KEY: str = ""
    BYBIT_API_SECRET: str = ""
    BINANCE_API_KEY: str = ""
    BINANCE_API_SECRET: str = ""
    BINANCE_BASE_URL: str = "https://testnet.binance.vision"
    TOKENIZED_API_KEY: str = ""
    TOKENIZED_API_SECRET: str = ""
    MEXC_API_BASE_URL: str = "https://api.mexc.com"
    EXECUTION_SERVER_PUBLIC_IP: str | None = None
    POLYGON_API_KEY: str = ""
    FINNHUB_API_KEY: str = ""
    COINGECKO_API_KEY: str = ""
    TIINGO_API_KEY: str = ""
    MARKETSTACK_API_KEY: str = ""
    TWELVEDATA_API_KEY: str = ""
    TWELVE_DATA_API_KEY: str = ""  # alias; synced from TWELVEDATA_API_KEY if empty
    FRED_API_KEY: str = ""
    FRED_CANADA_API_KEY: str = ""
    # Stooq daily CSV — optional session cookie / apikey from env only (never commit).
    STOOQ_API_KEY: str = ""
    STOOQ_COOKIE: str = ""
    # Nightly bulk ASCII extract (writable under ./data/stooq or /app/data/stooq).
    STOOQ_BULK_DIR: str = ""
    STOOQ_BULK_PACKAGES: str = "d_us_txt.zip,d_world_txt.zip"
    # Local overwrite cache of FRED macro series (VIX, yields, Fed — not equity OHLCV).
    FRED_BULK_DIR: str = ""
    # Nightly board/liquid equity EOD (Tiingo+Yahoo) — Stooq complement, always on.
    EQUITY_EOD_DIR: str = ""
    EIA_API_KEY: str = ""
    EIA_BULK_PATH: str = ""
    ALPHA_VANTAGE_API_KEY: str = ""
    FMP_API_KEY: str = ""
    NEWSCATCHER_API_KEY: str = ""
    FINIMPULSE_API_KEY: str = ""
    FINIMPULSE_SANDBOX_KEY: str = ""
    FINIMPULSE_BASE_URL: str = "https://api.finimpulse.com"
    APIBRICKS_API_KEY: str = ""
    # Spot commodities / central banks (macro registry). Empty key = source skipped, fallback used.
    OILPRICEAPI_API_KEY: str = ""
    # xFinLink metrics (market cap, P/E from filings) for the screener; free tier 100 req/day.
    XFINLINK_API_KEY: str = ""
    API_NINJAS_API_KEY: str = ""
    # Riksbank SWEA works without a key (low rate limit); a subscription key raises the limit.
    RIKSBANK_API_KEY: str = ""
    SEC_USER_AGENT: str = "QuantAnalytics/1.0 (research@quantanalyticsclub.ru)"
    # Tier C (paid vendors). Empty key = never call. Live HTTP stays off until
    # TIER_C_LIVE_FETCH and a registered fetcher exist. Local PIT files still apply.
    SHARADAR_API_KEY: str = ""
    NASDAQ_DATA_LINK_API_KEY: str = ""
    RAVENPACK_API_KEY: str = ""
    DATABENTO_API_KEY: str = ""
    # Licensed alt (Brain / Benzinga / Quiver / Morningstar). Empty = no HTTP.
    # Brain often arrives as S3 JSON dropped under TIER_C_STORE_DIR as BRAIN_BSI.json.
    BRAIN_API_KEY: str = ""
    BRAIN_API_BASE_URL: str = ""
    BENZINGA_API_KEY: str = ""
    QUIVER_API_KEY: str = ""
    MORNINGSTAR_API_KEY: str = ""
    MORNINGSTAR_API_BASE_URL: str = ""
    # Official QC/LEAN dump from your account (`lean data download`). Empty = skip.
    QUANTCONNECT_DATA_DIR: str = ""
    TIER_C_LIVE_FETCH: bool = False
    TIER_C_STORE_DIR: str = ""
    PIT_STORE_DIR: str = ""
    DAILY_BOOK_DIR: str = ""
    # Regulatory data sidecar (OpenBB isolated in separate container — AGPL).
    # Set ENABLE_OPENBB_SOURCE=false to disable SEC/FINRA without affecting other features.
    ENABLE_OPENBB_SOURCE: bool = True
    OPENBB_SERVICE_URL: str = "http://openbb-service:6900"
    OPENBB_SERVICE_TIMEOUT_SECONDS: float = 8.0
    # Terminal platform data connectors (ProviderRouter) reuse the keys above:
    # ALPACA_*, POLYGON_*, TWELVEDATA_*/TWELVE_DATA_*, TIINGO_*, MARKETSTACK_*,
    # FINNHUB_*, COINGECKO_*, FRED_*, ALPHA_VANTAGE_*, FMP_*, MOEX_*.
    # Public providers (MOEX ISS, CBR, IMF, World Bank, yfinance, Rosstat) need no key.
    # MOEX ISS — optional auth token or basic credentials (public ISS works without keys)
    MOEX_API_TOKEN: str = ""
    MOEX_USERNAME: str = ""
    MOEX_PASSWORD: str = ""
    # Selective egress proxy (Frankfurt etc.) for foreign APIs blocked from RU.
    # Prefer FOREIGN_HTTPS_PROXY; HTTPS_PROXY/HTTP_PROXY are fallbacks for foreign clients only.
    # MOEX/Binance/CBR/*.ru clients use trust_env=False and never honor these.
    FOREIGN_HTTPS_PROXY: str = ""
    HTTPS_PROXY: str = ""
    HTTP_PROXY: str = ""
    NO_PROXY: str = (
        "localhost,127.0.0.1,postgres,redis,backend,"
        "*.moex.com,iss.moex.com,"
        "api.binance.com,data-api.binance.vision,stream.binance.com,"
        "*.binance.com,*.cbr.ru,cbr.ru,*.ru,openbb-service"
    )
    # Optional path to World Bank bulk CSV/zip exports (see scripts/world_bank_ingest.py)
    WORLD_BANK_BULK_PATH: str = ""
    # Eurostat ESTAT_downloads_data_* zips (SDMX-CSV) and extracted store for registry refresh
    EUROSTAT_DATA_DIR: str = ""
    EUROSTAT_STORE_DIR: str = ""

    # ── News ─────────────────────────────────────────────────
    NEWS_API_KEY: str = ""
    GNEWS_API_KEY: str = ""
    # NewsAPI free/Developer tier delays articles ~24h; a 24h window returns
    # nothing. 72h clears the delay plus weekends. fetch_articles also falls
    # back to an unbounded query if a windowed request is still empty.
    NEWS_LOOKBACK_HOURS: int = 72
    NEWS_MAX_ARTICLES: int = 50
    # Operator cockpit news panel — keep in sync with frontend NEWS_DISPLAY_COUNT
    NEWS_PANEL_SIZE: int = 10
    # Bulk financial news CSV import (Docker mount: backend/data/news)
    NEWS_CSV_DATA_DIR: str = ""

    # ── RapidAPI / Investing.com market intelligence ─────────
    # RapidAPI "Investing.Com Ultimate API" — economic calendar, quotes,
    # earnings. Provides event/earnings catalysts that complement NewsAPI.
    RAPIDAPI_KEY: str = ""
    INVESTING_RAPIDAPI_HOST: str = "investing-com-ultimate-api.p.rapidapi.com"
    INVESTING_RAPIDAPI_ENABLED: bool = True
    INVESTING_RAPIDAPI_TIMEOUT_SECONDS: int = 15
    INVESTING_EVENTS_LOOKAHEAD_DAYS: int = 7

    # ── Equity analytics (Prompt 10) ─────────────────────────
    EQUITY_EARNINGS_PROXIMITY_DAYS: int = 5
    EQUITY_DIVIDEND_PROXIMITY_DAYS: int = 3
    EQUITY_MIN_VOLUME_THRESHOLD: int = 50_000

    # ── Event Risk Layer (Prompt 11) ─────────────────────────
    EVENT_RISK_NEWS_SHOCK_THRESHOLD: float = 0.65
    EVENT_RISK_LOCK_TTL_MINUTES: int = 60
    EVENT_RISK_POLL_LOOKBACK_MINUTES: int = 30
    NEWS_IMPACT_SIGMA_THRESHOLD: float = 2.0

    # ── Liquidity Monitor (Prompt 25) ────────────────────────
    LIQUIDITY_DROUGHT_THRESHOLD: float = 0.35
    LIQUIDITY_DROUGHT_LOCK_TTL_MINUTES: int = 30
    LIQUIDITY_DEPTH_LEVELS: int = 5
    LIQUIDITY_MAX_SPREAD_BPS: float = 100.0
    LIQUIDITY_BASELINE_SNAPSHOTS: int = 10
    LIQUIDITY_VOLUME_LOOKBACK_BARS: int = 20

    # ── Forecast Engine (Prompt 22) ──────────────────────────
    FORECAST_RISK_FLAG_THRESHOLD: float = 0.45
    FORECAST_ELEVATED_UNCERTAINTY_THRESHOLD: float = 0.50
    FORECAST_TAIL_RISK_ALPHA: float = 0.95
    FORECAST_TAIL_RISK_NORMALIZATION: float = 0.05
    FORECAST_VOL_WINDOW: int = 10
    FORECAST_VOL_TREND_PERIODS: int = 5
    FORECAST_PRICE_LOOKBACK_BARS: int = 90
    FORECAST_MODE: str = "compact"
    MLFLOW_TRACKING_URI: str = "file:///app/data/mlflow"
    MLFLOW_EXPORT_DIR: str = "/app/data/mlflow_exports"
    FEAST_STORE_DIR: str = "/app/data/feature_store"

    TELEGRAM_BOT_TOKEN: str = ""
    TELEGRAM_CHAT_ID: str = ""
    # Optional relay base (e.g. http://172.18.0.1:18787) when containers cannot reach api.telegram.org
    TELEGRAM_API_BASE_URL: str = ""
    HC_PING_DATA_INGESTION: str = ""
    HC_PING_FORECAST: str = ""
    HC_PING_GRIDBOT: str = ""
    ALERT_WEBHOOK_URL: str = ""
    HEALTH_CHECK_BASE_URL: str = ""
    # Hourly health report / critical escalation to Telegram (off: no bot spam).
    HEALTH_TELEGRAM_ENABLED: bool = False
    HEALTH_CHECK_WS_URL: str = ""
    HEALTH_CHECK_CHAT_TOKEN: str = ""
    # Expensive health probes (live LLM) — default OFF to avoid AITunnel bleed on hourly cron.
    HEALTH_LIVE_CHAT_CHECK_ENABLED: bool = False
    HEALTH_LIVE_CHAT_INTERVAL_SECONDS: float = 10800.0  # 3h when enabled
    HEALTH_LLM_TRIAGE_ENABLED: bool = False
    HEALTH_LLM_TRIAGE_INTERVAL_SECONDS: float = 3600.0
    HEALTH_EXPENSIVE_CACHE_TTL_SECONDS: float = 86400.0
    TEST_USER_A_EMAIL: str = ""
    TEST_USER_A_PASSWORD: str = ""
    TEST_USER_A_TOKEN: str = ""
    TEST_USER_B_EMAIL: str = ""
    TEST_USER_B_PASSWORD: str = ""
    TEST_USER_B_TOKEN: str = ""
    ADMIN_ACCESS_TOKEN_COOKIE: str = "apex_admin_access_token"
    ADMIN_TOKEN_AUDIENCE: str = "admin"

    # ── LLM (AITUNNEL — single OpenAI-compatible gateway) ───
    AITUNNEL_API_KEY: str = ""
    AITUNNEL_BASE_URL: str = "https://api.aitunnel.ru/v1"
    # A1 provider switch. Default id is the gateway already configured above.
    # A Russian-origin model vendor is not in tech-stack.md or DECISIONS (OQ-A1-1).
    # LLM_ONPREM refuses any public host; it does not invent an endpoint.
    LLM_PROVIDER: str = "aitunnel"
    LLM_ONPREM: bool = False
    LLM_ONPREM_BASE_URL: str = ""
    LLM_ONPREM_API_KEY: str = ""
    # LLM_PROVIDER=gigachat: Sber GigaChat (Russian model, data stays in Russia).
    # GIGACHAT_AUTH_KEY = the "Authorization key" from developers.sber.ru (base64 of id:secret).
    GIGACHAT_AUTH_KEY: str = ""
    GIGACHAT_SCOPE: str = "GIGACHAT_API_PERS"
    GIGACHAT_MODEL: str = "GigaChat-2-Max"
    GIGACHAT_AUTH_URL: str = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
    GIGACHAT_BASE_URL: str = "https://gigachat.devices.sberbank.ru/api/v1"
    # Path to the Russian Trusted Root CA (.crt/.pem); empty = system trust store.
    GIGACHAT_CA_BUNDLE: str = ""
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    LLM_MODEL_CLIENT_CHAT: str = "kimi-k3"
    LLM_MODEL_BATCH: str = "kimi-k3"
    LLM_ENABLED: bool = False
    # Paid model calls only when a person asks (chat, «Пояснение ИИ»). Background jobs,
    # page loads, health checks and news ingestion never spend tokens unless enabled.
    LLM_AUTO_EXPLAIN: bool = False
    LLM_NEWS_EVENT_EXTRACTION: bool = False
    LLM_NEWS_TRANSLATION: bool = False
    LLM_TIMEOUT_SECONDS: int = 75
    # Alert when AITUNNEL balance < ~N hours of observed spend (health check + Telegram).
    AITUNNEL_BALANCE_ALERT_HOURS: float = 24.0
    # Fallback threshold (₽) when no spend history exists yet.
    AITUNNEL_BALANCE_ALERT_RUB: float = 100.0
    # Alert when 24h burn exceeds this without an obvious user-traffic spike (health / cron bleed).
    AITUNNEL_BURN_SPIKE_ALERT_RUB_24H: float = 150.0
    # In-app chat diagnostics are hidden in normal user-facing replies.
    CHAT_DEBUG_FOOTERS: bool = False
    # Applies to successful LLM replies only; rule fallback keeps its own guard.
    CHAT_SHOW_DISCLOSURE: bool = False

    # ── Trading Mode ─────────────────────────────────────────
    PAPER_TRADING_ENABLED: bool = True
    # When True, pipeline auto-approves and paper-fills tradeable maneuvers
    # (no manual operator approval required in paper mode).
    PAPER_AUTO_EXECUTE: bool = True
    LIVE_TRADING_ENABLED: bool = False
    LIVE_TRADING_CONFIRMATION: str = ""
    # Profile live-transition gate (Prompt 2 constitution)
    PAPER_TRADING_MIN_DAYS: int = 30
    PAPER_SHARPE_MIN_THRESHOLD: float = 0.5

    # ── Risk Defaults ────────────────────────────────────────
    DEFAULT_PORTFOLIO_SIZE: float = 0.0
    # Used only when portfolio_size is unset (0) — maneuver sizing still needs positive capital.
    SIZING_PORTFOLIO_FALLBACK_USD: float = 10_000.0
    MAX_RISK_PER_TRADE_PCT: float = 2.0
    DAILY_MAX_LOSS_PCT: float = 5.0
    MAX_PORTFOLIO_EXPOSURE_PCT: float = 80.0
    MAX_DRAWDOWN_PCT: float = 15.0
    NO_TRADE_CONFIDENCE_THRESHOLD: float = 0.5

    # ── Position Sizing Caps (bankruptcy protection) ─────────
    # Never let a single trade consume more than this share of total capital.
    # With MAX_PORTFOLIO_EXPOSURE_PCT this keeps a mandatory cash buffer:
    # cash buffer % = 100 - MAX_PORTFOLIO_EXPOSURE_PCT (default 20%).
    MAX_POSITION_PCT: float = 10.0
    # Optional hard absolute cap per position in USD (0 = disabled, use % only).
    MAX_NOTIONAL_PER_POSITION_USD: float = 0.0
    # Hard limits for orders on a real broker account (checked by the broker
    # executor itself, after every upstream sizing step).
    LIVE_MAX_ORDER_PCT_OF_EQUITY: float = 10.0
    LIVE_MAX_ORDER_RUB: float = 0.0  # 0 = no absolute cap, only the % cap
    LIVE_MAX_ORDERS_PER_DAY: int = 20
    LIVE_ALLOW_SHORT: bool = False

    # ── Bot risk (shared Grid / DCA / Momentum) ───────────────
    # Risk per trade for bot position sizing (1–2% typical).
    BOT_RISK_PER_TRADE_PCT: float = 1.5
    # Halt all bots when aggregate drawdown exceeds this % of allocated capital.
    BOT_CIRCUIT_BREAKER_DRAWDOWN_PCT: float = 10.0
    # warn = log/event only; block = reject new correlated entries.
    BOT_CORRELATION_MODE: str = "block"
    # Default global stop-loss distance (fraction below grid lower / entry).
    BOT_DEFAULT_STOP_LOSS_PCT: float = 0.05
    # Round-trip fee/commission estimate per side, used for net-profit analytics.
    COMMISSION_RATE_PCT: float = 0.1
    # Estimated perpetual funding drag (% of notional per day). 0 = equities/spot.
    # Positive = cost to hold (long pays / short receives is signed later by side).
    FUNDING_RATE_PCT_PER_DAY: float = 0.01

    # ── Pipeline ─────────────────────────────────────────────
    # Owner for beat/scheduled runs (email). Falls back to first active admin.
    PIPELINE_OWNER_EMAIL: str = ""
    PIPELINE_SCHEDULE_CRON: str = "0 9 * * 1-5"
    PIPELINE_MAX_TICKERS: int = 0  # 0 = full effective watchlist (no cap)
    PIPELINE_BAR_LOOKBACK_DAYS: int = 180
    # Refresh macro calendars when DB cache is older than this (minutes). 0 = always refresh.
    PIPELINE_MACRO_REFRESH_TTL_MINUTES: int = 30
    # LLM multi-role debate adds 60–120s; off by default in prod (optional enrichment).
    PIPELINE_LLM_DEBATE_ENABLED: bool = False
    # TreeSHAP optional in presentation (requires shap>=0.47 + compatible numpy).
    PIPELINE_SKIP_SHAP: bool = False
    # Emergency toggles — keep False so full analysis runs; set only for incident response.
    PIPELINE_SKIP_HMM_REGIME: bool = False
    PIPELINE_NEWS_FAST: bool = False
    PIPELINE_SKIP_MACRO_REFRESH: bool = False
    MANEUVER_COUNT: int = 10
    # Russian market first (the product is for Russian investors); a few global benchmarks after.
    DEFAULT_WATCHLIST: str = "SBER,GAZP,LKOH,YDEX,ROSN,GMKN,PLZL,MOEX,IMOEX,AAPL,MSFT,GOOGL,AMZN,META,NVDA,TSLA,SPY,QQQ,JPM,V,BTC-USD"
    FORECAST_LOG_BASKET: str = (
        "SBER,GAZP,LKOH,GMKN,ROSN,IMOEX,AAPL,MSFT,SPY,QQQ,BTC-USD"
    )

    # ── Maneuver scoring weights (configurable) ──────────────
    # Blended candidate score = technical * SCORE_WEIGHT_TECHNICAL
    #   + news/events * SCORE_WEIGHT_NEWS + regime/macro * SCORE_WEIGHT_REGIME.
    # Weights are normalized at runtime so they need not sum to exactly 1.0.
    SCORE_WEIGHT_TECHNICAL: float = 0.40
    SCORE_WEIGHT_NEWS: float = 0.35
    SCORE_WEIGHT_REGIME: float = 0.25
    # classifier = DirectionClassifier (default). ensemble = ForecastEngine — only after review.
    MANEUVER_SIGNAL_SOURCE: str = "classifier"
    MANEUVER_ENSEMBLE_SHADOW: bool = True
    # Diagnostic comparison only (does not change manoeuvres); each ticker costs a model replay.
    MANEUVER_ENSEMBLE_SHADOW_MAX: int = 3

    # ── Monitoring ───────────────────────────────────────────
    SENTRY_DSN: str = ""
    PROMETHEUS_ENABLED: bool = True

    # ── Notifications ────────────────────────────────────────
    NOTIFY_EMAIL: str = ""
    WEBHOOK_URL: str = ""

    # ── Computed properties ──────────────────────────────────

    @property
    def whitelist_emails_set(self) -> set[str]:
        """Parse comma-separated whitelist emails into a set."""
        return {
            e.strip().lower()
            for e in self.WHITELIST_EMAILS.split(",")
            if e.strip()
        }

    @property
    def trusted_proxy_networks(self) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...]:
        """Networks allowed to supply X-Forwarded-For / X-Real-IP."""
        networks: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = []
        for raw in self.TRUSTED_PROXY_CIDRS.split(","):
            cidr = raw.strip()
            if not cidr:
                continue
            networks.append(ipaddress.ip_network(cidr, strict=False))
        return tuple(networks)

    @property
    def default_watchlist_list(self) -> list[str]:
        return [t.strip().upper() for t in self.DEFAULT_WATCHLIST.split(",") if t.strip()]

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == AppEnv.PRODUCTION

    @property
    def is_development(self) -> bool:
        return self.APP_ENV == AppEnv.DEVELOPMENT

    @property
    def live_trading_unlocked(self) -> bool:
        """Live trading requires BOTH the flag AND the confirmation string."""
        return (
            self.LIVE_TRADING_ENABLED
            and self.LIVE_TRADING_CONFIRMATION == "I_UNDERSTAND_THE_RISKS"
        )

    @property
    def telegram_configured(self) -> bool:
        return bool(self.TELEGRAM_BOT_TOKEN.strip() and self.TELEGRAM_CHAT_ID.strip())

    @property
    def alert_webhook_configured(self) -> bool:
        return bool(self.ALERT_WEBHOOK_URL.strip())

    @property
    def twilio_configured(self) -> bool:
        return bool(
            self.TWILIO_ACCOUNT_SID.strip()
            and self.TWILIO_AUTH_TOKEN.strip()
            and self.TWILIO_FROM_NUMBER.strip()
        )

    @property
    def critical_escalation_phones(self) -> list[str]:
        return [p.strip() for p in self.CRITICAL_ESCALATION_PHONES.split(",") if p.strip()]

    @property
    def critical_escalation_configured(self) -> bool:
        return self.twilio_configured and bool(self.critical_escalation_phones)

    # ── Validators ───────────────────────────────────────────

    @field_validator("PAPER_TRADING_MIN_DAYS")
    @classmethod
    def validate_paper_trading_min_days(cls, v: int) -> int:
        if v < 0:
            raise ValueError("PAPER_TRADING_MIN_DAYS must be >= 0")
        return v

    @field_validator("PAPER_SHARPE_MIN_THRESHOLD")
    @classmethod
    def validate_paper_sharpe_threshold(cls, v: float) -> float:
        if v < -10 or v > 10:
            raise ValueError("PAPER_SHARPE_MIN_THRESHOLD must be between -10 and 10")
        return v

    @field_validator("MAX_RISK_PER_TRADE_PCT")
    @classmethod
    def validate_max_risk(cls, v: float) -> float:
        if v <= 0 or v > 10:
            raise ValueError("MAX_RISK_PER_TRADE_PCT must be between 0 and 10")
        return v

    @field_validator("NO_TRADE_CONFIDENCE_THRESHOLD")
    @classmethod
    def validate_confidence_threshold(cls, v: float) -> float:
        if not 0 < v < 1:
            raise ValueError("NO_TRADE_CONFIDENCE_THRESHOLD must be between 0 and 1")
        return v

    @field_validator("MAX_POSITION_PCT")
    @classmethod
    def validate_max_position_pct(cls, v: float) -> float:
        if v <= 0 or v > 100:
            raise ValueError("MAX_POSITION_PCT must be between 0 and 100")
        return v

    @property
    def cash_buffer_pct(self) -> float:
        """Mandatory free-cash cushion = 100 - max total exposure."""
        return max(0.0, 100.0 - self.MAX_PORTFOLIO_EXPOSURE_PCT)

    @model_validator(mode="after")
    def apply_defaults(self) -> "Settings":
        # Accept either TWELVEDATA_API_KEY or TWELVE_DATA_API_KEY from env.
        twelve = (self.TWELVEDATA_API_KEY or "").strip()
        twelve_alias = (self.TWELVE_DATA_API_KEY or "").strip()
        if twelve and not twelve_alias:
            self.TWELVE_DATA_API_KEY = twelve
        elif twelve_alias and not twelve:
            self.TWELVEDATA_API_KEY = twelve_alias

        if not self.WORLD_BANK_BULK_PATH.strip():
            bulk_dir = _REPO_ROOT / "рыночные данные"
            if bulk_dir.is_dir():
                self.WORLD_BANK_BULK_PATH = str(bulk_dir)

        if not self.EIA_BULK_PATH.strip():
            bulk_dir = _REPO_ROOT / "рыночные данные"
            if bulk_dir.is_dir():
                self.EIA_BULK_PATH = str(bulk_dir)

        if not self.EUROSTAT_DATA_DIR.strip():
            euro_dir = _REPO_ROOT / "рыночные данные" / "ЕВРОСТАТ"
            market_dir = _REPO_ROOT / "рыночные данные"
            if euro_dir.is_dir():
                self.EUROSTAT_DATA_DIR = str(euro_dir)
            elif market_dir.is_dir():
                self.EUROSTAT_DATA_DIR = str(market_dir)

        if not self.EUROSTAT_STORE_DIR.strip():
            self.EUROSTAT_STORE_DIR = str(_BACKEND_DIR / "data" / "eurostat")

        if not self.STOOQ_BULK_DIR.strip():
            # Docker: /app/data is the platform data mount. Local Windows: prefer backend/data.
            docker_data = Path("/app/data")
            local_data = _BACKEND_DIR / "data" / "stooq"
            # Only treat /app/data as docker when it looks like a Linux container mount
            # (avoid Windows accidentally creating C:\app\data from Path("/app/data")).
            in_docker = Path("/.dockerenv").is_file() or (
                docker_data.is_dir() and str(docker_data).startswith("/app")
            )
            if in_docker:
                self.STOOQ_BULK_DIR = str(docker_data / "stooq")
            else:
                self.STOOQ_BULK_DIR = str(local_data)

        if not self.FRED_BULK_DIR.strip():
            self.FRED_BULK_DIR = str(Path(self.STOOQ_BULK_DIR).parent / "fred")

        if not self.EQUITY_EOD_DIR.strip():
            self.EQUITY_EOD_DIR = str(Path(self.STOOQ_BULK_DIR).parent / "equity_eod")

        if not self.NEWS_CSV_DATA_DIR.strip():
            repo_news = _BACKEND_DIR / "data" / "news"
            legacy_news = _REPO_ROOT / "новостные данные"
            if repo_news.is_dir() and any(repo_news.glob("*.csv")):
                self.NEWS_CSV_DATA_DIR = str(repo_news)
            elif legacy_news.is_dir():
                self.NEWS_CSV_DATA_DIR = str(legacy_news)
            else:
                self.NEWS_CSV_DATA_DIR = str(repo_news)

        if self.LIVE_TRADING_ENABLED and not self.PAPER_TRADING_ENABLED:
            if self.LIVE_TRADING_CONFIRMATION != "I_UNDERSTAND_THE_RISKS":
                raise ValueError(
                    "To enable live trading, set LIVE_TRADING_CONFIRMATION=I_UNDERSTAND_THE_RISKS"
                )
        return self

    @model_validator(mode="after")
    def derive_webauthn_from_domain(self) -> "Settings":
        """Use production DOMAIN for WebAuthn RP when explicit vars are unset."""
        domain = self.DOMAIN.strip().lower()
        if not domain:
            return self
        if self.WEBAUTHN_RP_ID in ("", "localhost"):
            self.WEBAUTHN_RP_ID = domain
        if self.WEBAUTHN_ORIGIN.startswith("http://localhost"):
            self.WEBAUTHN_ORIGIN = f"https://{domain}"
        return self

    @model_validator(mode="after")
    def validate_production_secret_key(self) -> "Settings":
        if self.APP_ENV != AppEnv.PRODUCTION:
            return self
        key = self.SECRET_KEY.strip()
        if len(key) < 32:
            raise ValueError(
                "SECRET_KEY must be at least 32 characters when APP_ENV=production"
            )
        lowered = key.lower()
        if lowered in _WEAK_SECRET_KEYS:
            raise ValueError(
                "SECRET_KEY is a known weak/default value; set a strong random secret in production"
            )
        if len(set(lowered)) <= 2:
            raise ValueError(
                "SECRET_KEY is too predictable for production; use a high-entropy random value"
            )
        if self.DEBUG:
            raise ValueError("DEBUG must be false when APP_ENV=production")
        if self.PASSWORD_DEV_PLAIN:
            raise ValueError("PASSWORD_DEV_PLAIN must be false when APP_ENV=production")
        if not self.CSRF_PROTECTION_ENABLED:
            raise ValueError("CSRF_PROTECTION_ENABLED must be true when APP_ENV=production")
        return self

    def get_cors_origins(self) -> list[str]:
        if self.APP_ENV == AppEnv.DEVELOPMENT:
            return [
                "http://localhost:3000",
                "http://127.0.0.1:3000",
                "http://localhost:3001",
                "http://127.0.0.1:3001",
                "http://localhost:3100",
                "http://127.0.0.1:3100",
            ]

        origins: list[str] = []
        if self.CORS_ORIGINS.strip():
            origins.extend(
                o.strip().rstrip("/")
                for o in self.CORS_ORIGINS.split(",")
                if o.strip()
            )
        if self.DOMAIN.strip():
            domain = self.DOMAIN.strip().rstrip("/")
            origins.extend(
                [
                    f"http://{domain}",
                    f"https://{domain}",
                    f"http://www.{domain}",
                    f"https://www.{domain}",
                ]
            )
        # Same-origin requests (relative /api/* via reverse proxy) need no CORS,
        # but explicit origins are required when NEXT_PUBLIC_API_URL points at the
        # public host while the UI is served from another port during staging.
        return list(dict.fromkeys(origins))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached settings singleton — import this everywhere."""
    return Settings()


settings = get_settings()
