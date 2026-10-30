"""Alembic environment configuration."""
from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool
from sqlalchemy.engine import Connection

from app.core.config import settings
from app.db.session import Base

# Import all models so Alembic detects them
from app.db.models import (  # noqa: F401
    User,
    Watchlist,
    OHLCVBar,
    NewsArticle,
    MarketSignal,
    ManeuverReport,
    Maneuver,
    ExecutionOrder,
    BacktestRun,
    AuditLog,
)
from app.domain.active_lock import ActiveLockORM  # noqa: F401
from app.domain.deal_intent import DealIntentORM  # noqa: F401
from app.domain.equity import (  # noqa: F401
    CorporateActionORM,
    DividendEventORM,
    EarningsCalendarORM,
    LiquidityFilterORM,
    MarketSessionProfileORM,
    NewsImpactScoreORM,
    SectorRotationScoreORM,
    SplitHistoryORM,
    VolatilityByRegimeORM,
)
from app.domain.kill_switch import KillSwitchStateORM  # noqa: F401
from app.domain.instrument import InstrumentORM  # noqa: F401
from app.domain.market_data import (  # noqa: F401
    MacroIndicatorORM,
    MarketOhlcvORM,
    MarketTradeORM,
    OrderBookSnapshotORM,
    SectorMappingORM,
)
from app.domain.macro_registry import (  # noqa: F401
    MacroCalendarEntryORM,
    MacroRawResponseORM,
    MacroReportSnapshotORM,
    MacroSeriesHistoryORM,
    MacroSeriesNormalizedORM,
    MacroSourceRegistryORM,
)
from app.domain.regime import RegimeHistoryORM  # noqa: F401
from app.domain.hierarchy_calibration import HierarchyCalibrationHistoryORM  # noqa: F401
from app.domain.news_impact import NewsImpactHistoryORM  # noqa: F401
from app.domain.profile import ApprovalPolicyORM, ProfileORM  # noqa: F401
from app.domain.access_policy import AccessPolicyStateORM  # noqa: F401
from app.domain.admissions import AdmissionCaseORM, AdmissionStatusHistoryORM  # noqa: F401
from app.domain.device_identity import (  # noqa: F401
    DeviceORM,
    IdentityClusterMemberORM,
    IdentityClusterORM,
    SessionDeviceORM,
)
from app.domain.rbac import AccountGroupORM, IdentityORM, PermissionORM, RolePermissionORM  # noqa: F401
from app.domain.admin_security import BreakGlassRequestORM  # noqa: F401
from app.domain.subscription import InvoiceORM, SubscriptionORM  # noqa: F401
from app.domain.sub_portfolio import SubPortfolioORM  # noqa: F401
from app.domain.review_queue import ReviewQueueORM  # noqa: F401
from app.domain.custom_basket import CustomBasketItemORM, CustomBasketORM  # noqa: F401
from app.domain.sleeve import SleeveORM  # noqa: F401

config = context.config
# Migrations must run as POSTGRES_USER (apex), not appuser — appuser cannot CREATE TABLE.
_migration_url = settings.MIGRATION_DATABASE_URL_SYNC.replace("%", "%%")
config.set_main_option("sqlalchemy.url", _migration_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=settings.MIGRATION_DATABASE_URL_SYNC,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        do_run_migrations(connection)


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
