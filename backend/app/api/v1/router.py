"""API v1 router вЂ” registers all endpoint sub-routers."""
"""API v1 router - registers all endpoint sub-routers."""
from fastapi import APIRouter

from app.api.v1.endpoints.account import router as account_router
from app.api.v1.endpoints.broker import router as broker_router
from app.api.v1.endpoints.auth import router as auth_router
from app.api.v1.endpoints.grid import router as grid_router
from app.api.v1.endpoints.dca_bots import router as dca_bots_router
from app.api.v1.endpoints.momentum_bots import router as momentum_bots_router
from app.api.v1.endpoints.bots import router as bots_router
from app.api.v1.endpoints.maneuvers import router as maneuvers_router
from app.api.v1.endpoints.robot import router as robot_router
from app.api.v1.endpoints.ops import router as ops_router
from app.api.v1.endpoints.ops_observe import router as ops_observe_router
from app.api.v1.endpoints.perf_budget import router as perf_budget_router
from app.api.v1.endpoints.catalog import router as catalog_router
from app.api.v1.endpoints.market_eod import router as market_eod_router
from app.api.v1.endpoints.feature_flags import router as feature_flags_router
from app.api.v1.endpoints.market import (
    audit_router,
    backtest_router,
    health_router,
    market_router,
)
from app.api.v1.endpoints.pipeline import router as pipeline_router
from app.api.v1.endpoints.settings import router as settings_router
from app.api.v1.endpoints.trading_accounts import router as trading_accounts_router
from app.api.v1.endpoints.watchlist_news import news_router, watchlist_router
from app.api.v1.endpoints.websocket import router as ws_router
from app.api.v1.endpoints.trading import router as trading_router
from app.api.v1.endpoints.portfolio import router as portfolio_router
from app.api.v1.endpoints.position_audit import router as position_audit_router
from app.api.v1.endpoints.cockpit import router as cockpit_router
from app.api.v1.endpoints.deal_intents import router as deal_intents_router
from app.api.v1.endpoints.direct_deals import router as direct_deals_router
from app.api.v1.endpoints.forecast import router as forecast_router
from app.api.v1.endpoints.forecast_log import router as forecast_log_router
from app.api.v1.endpoints.portfolio_book import router as portfolio_book_router
from app.api.v1.endpoints.venues import router as venues_router
from app.api.v1.endpoints.notifications import router as notifications_router
from app.api.v1.endpoints.returns import router as returns_router
from app.api.v1.endpoints.factor_lens import router as factor_lens_router
from app.api.v1.endpoints.fund_lookthrough import router as fund_lookthrough_router
from app.api.v1.endpoints.futures_risk import router as futures_risk_router
from app.api.v1.endpoints.decisions_report import router as decisions_report_router
from app.api.v1.endpoints.total_costs import router as total_costs_router
from app.api.v1.endpoints.pretrade_check import router as pretrade_check_router
from app.api.v1.endpoints.key_rate import router as key_rate_router
from app.api.v1.endpoints.goals import router as goals_router
from app.api.v1.endpoints.decision_core import router as decision_core_router
from app.api.v1.endpoints.tax_ru import router as tax_ru_router
from app.api.v1.endpoints.futures_market import router as futures_market_router
from app.api.v1.endpoints.risk_engine import router as risk_engine_router
from app.api.v1.endpoints.position_liquidity import router as position_liquidity_router
from app.api.v1.endpoints.bonds import router as bonds_router
from app.api.v1.endpoints.payouts import router as payouts_router
from app.api.v1.endpoints.tax_rf import router as tax_rf_router
from app.api.v1.endpoints.pretrade import router as pretrade_router
from app.api.v1.endpoints.forecast_core import router as forecast_core_router
from app.api.v1.endpoints.model_risk import router as model_risk_router
from app.api.v1.endpoints.market_regime import router as market_regime_router
from app.api.v1.endpoints.stress_library import router as stress_library_router
from app.api.v1.endpoints.concentration import router as concentration_router
from app.api.v1.endpoints.behavior import router as behavior_router
from app.api.v1.endpoints.explanations import router as explanations_router
from app.api.v1.endpoints.portfolio_report import router as portfolio_report_router
from app.api.v1.endpoints.act_desk import router as act_desk_router
from app.api.v1.endpoints.investment_profile import router as investment_profile_router
from app.api.v1.endpoints.e2e_demo import router as e2e_demo_router
from app.api.v1.endpoints.privacy import router as privacy_router
from app.api.v1.endpoints.onboarding import router as onboarding_router
from app.api.v1.endpoints.sandbox_limits import router as sandbox_limits_router
from app.api.v1.endpoints.qa_tools import router as qa_tools_router
from app.api.v1.endpoints.macro import router as macro_router
from app.api.v1.endpoints.strategy_composer import router as strategy_composer_router
from app.api.v1.endpoints.market_graph import router as market_graph_router
from app.api.v1.endpoints.stress_harness import router as stress_harness_router
from app.api.v1.endpoints.track_record import router as track_record_router
from app.api.v1.endpoints.admissions import router as admissions_router
from app.api.v1.endpoints.applications import router as applications_router
from app.api.v1.endpoints.chat import router as chat_router
from app.api.v1.endpoints.origination import (
    access_router,
    admin_router,
    billing_router,
    devices_router,
    subport_router,
)
from app.api.v1.endpoints.crypto_stack import router as crypto_stack_router
from app.api.v1.endpoints.crypto_stack_integrations import (
    router as crypto_stack_integrations_router,
)
from app.api.v1.endpoints.trading_engines import router as trading_engines_router
from app.api.v1.endpoints.terminal import router as terminal_router
from app.api.v1.endpoints.terminal_agents import router as terminal_agents_router
from app.api.v1.endpoints.terminal_quant import router as terminal_quant_router
from app.api.v1.endpoints.orders import router as orders_router
from app.api.v1.endpoints.partners import router as partners_router
from app.api.v1.endpoints.bot_core import router as bot_core_router
from app.api.v1.endpoints.ops_observe import router as ops_observe_router
from app.api.v1.endpoints.perf_budget import router as perf_budget_router
from app.api.v1.endpoints.beta_admin import router as beta_admin_router
from app.api.v1.endpoints.subject_rights import router as subject_rights_router
from app.api.v1.endpoints.support_desk import router as support_desk_router
from app.api.v1.endpoints.experiments import router as experiments_router
from app.api.v1.endpoints.product_analytics import router as product_analytics_router
from app.api.v1.endpoints.public_accuracy import router as public_accuracy_router
from app.api.v1.endpoints.waitlist import router as waitlist_router
from app.api.v1.endpoints.legal import router as legal_router
from app.api.v1.endpoints.subscription_billing import router as subscription_billing_router
from app.api.v1.endpoints.signal_monitoring import router as signal_monitoring_router
from app.api.v1.endpoints.terminal_market import router as terminal_market_router
from app.api.v1.endpoints.email_webhooks import router as email_webhooks_router
from app.api.v1.endpoints.ml_registry import router as ml_registry_router
from app.api.v1.endpoints.regulatory_data import router as regulatory_data_router
from app.api.v1.endpoints.two_factor import router as two_factor_router
from app.api.v1.endpoints.fleet_audit import router as fleet_audit_router
from app.api.v1.endpoints.platform import router as platform_router

api_router = APIRouter()

# REST
api_router.include_router(auth_router)
api_router.include_router(two_factor_router)
api_router.include_router(email_webhooks_router)
api_router.include_router(ml_registry_router)
api_router.include_router(account_router)
api_router.include_router(pipeline_router)
api_router.include_router(maneuvers_router)
api_router.include_router(robot_router)
api_router.include_router(market_router)
api_router.include_router(backtest_router)
api_router.include_router(audit_router)
api_router.include_router(health_router)
api_router.include_router(watchlist_router)
api_router.include_router(news_router)
api_router.include_router(grid_router)
api_router.include_router(dca_bots_router)
api_router.include_router(momentum_bots_router)
api_router.include_router(bots_router)
api_router.include_router(settings_router)
api_router.include_router(trading_accounts_router)
api_router.include_router(trading_router)
api_router.include_router(ops_router)
api_router.include_router(ops_observe_router)
api_router.include_router(perf_budget_router)
api_router.include_router(catalog_router)
api_router.include_router(market_eod_router)
api_router.include_router(feature_flags_router)
api_router.include_router(platform_router)
api_router.include_router(portfolio_router)
api_router.include_router(position_audit_router)
api_router.include_router(broker_router)
api_router.include_router(cockpit_router)
api_router.include_router(deal_intents_router)
api_router.include_router(direct_deals_router)
api_router.include_router(forecast_router)
api_router.include_router(forecast_log_router)
api_router.include_router(portfolio_book_router)
api_router.include_router(venues_router)
api_router.include_router(notifications_router)
api_router.include_router(returns_router)
api_router.include_router(factor_lens_router)
api_router.include_router(fund_lookthrough_router)
api_router.include_router(futures_risk_router)
api_router.include_router(decisions_report_router)
api_router.include_router(total_costs_router)
api_router.include_router(pretrade_check_router)
api_router.include_router(key_rate_router)
api_router.include_router(goals_router)
api_router.include_router(decision_core_router)
api_router.include_router(tax_ru_router)
api_router.include_router(futures_market_router)
api_router.include_router(risk_engine_router)
api_router.include_router(position_liquidity_router)
api_router.include_router(bonds_router)
api_router.include_router(payouts_router)
api_router.include_router(tax_rf_router)
api_router.include_router(pretrade_router)
api_router.include_router(forecast_core_router)
api_router.include_router(model_risk_router)
api_router.include_router(market_regime_router)
api_router.include_router(stress_library_router)
api_router.include_router(concentration_router)
api_router.include_router(behavior_router)
api_router.include_router(explanations_router)
api_router.include_router(portfolio_report_router)
api_router.include_router(act_desk_router)
api_router.include_router(investment_profile_router)
api_router.include_router(e2e_demo_router)
api_router.include_router(privacy_router)
api_router.include_router(onboarding_router)
api_router.include_router(sandbox_limits_router)
api_router.include_router(qa_tools_router)
api_router.include_router(macro_router)
api_router.include_router(strategy_composer_router)
api_router.include_router(market_graph_router)
api_router.include_router(stress_harness_router)
api_router.include_router(track_record_router)
api_router.include_router(admissions_router)
api_router.include_router(applications_router)
api_router.include_router(chat_router)
api_router.include_router(devices_router)
api_router.include_router(access_router)
api_router.include_router(admin_router)
api_router.include_router(fleet_audit_router)
api_router.include_router(billing_router)
api_router.include_router(subport_router)
api_router.include_router(crypto_stack_router)
api_router.include_router(crypto_stack_integrations_router)
api_router.include_router(trading_engines_router)
api_router.include_router(orders_router)
api_router.include_router(partners_router)
api_router.include_router(subscription_billing_router)
api_router.include_router(bot_core_router)
api_router.include_router(ops_observe_router)
api_router.include_router(perf_budget_router)
api_router.include_router(waitlist_router)
api_router.include_router(legal_router)
api_router.include_router(public_accuracy_router)
api_router.include_router(product_analytics_router)
api_router.include_router(experiments_router)
api_router.include_router(beta_admin_router)
api_router.include_router(subject_rights_router)
api_router.include_router(support_desk_router)
api_router.include_router(signal_monitoring_router)
api_router.include_router(terminal_router)
api_router.include_router(terminal_market_router)
api_router.include_router(terminal_agents_router)
api_router.include_router(terminal_quant_router)
api_router.include_router(regulatory_data_router)

# WebSocket
api_router.include_router(ws_router)