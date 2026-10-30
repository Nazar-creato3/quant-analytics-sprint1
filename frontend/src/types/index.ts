// Quant Analytics — TypeScript type definitions
// Mirror of backend Pydantic schemas

export type ManeuverStatus =
  | "pending" | "pending_approval" | "awaiting_approval"
  | "approved" | "rejected"
  | "executing" | "filled" | "cancelled" | "invalidated";

export type DealIntentStatus =
  | "draft" | "pending_approval" | "approved" | "rejected"
  | "held" | "executing" | "filled" | "cancelled" | "failed";

export interface DealIntent {
  id: string;
  instrument_id: number;
  sleeve_id: string;
  direction: Direction;
  target_price: number | null;
  entry_reason: string;
  strategy: string;
  required_confidence: number;
  max_slippage_bps: number;
  max_spread_bps: number;
  time_in_force: string;
  trigger_type: string;
  exit_logic: Record<string, unknown>;
  hedge_attachment_id: string | null;
  approval_threshold: number;
  risk_tag: string;
  news_lock: boolean;
  correlation_lock: boolean;
  volatility_lock: boolean;
  status: DealIntentStatus;
  created_at: string;
  updated_at: string;
}

export type {
  ActionForecast,
  ActionRecommendation,
  DistributionForecast,
  ForecastHierarchyOutput,
  ForecastHierarchyView,
  ForecastInstructionBlock,
  ForecastPredictionItem,
  IntervalForecast,
  LayerBasis,
  MarketOutlookCard,
  MarketOutlookEntry,
  MarketOutlookPoint,
  MarketOutlookScenario,
  PointForecast,
  PointMagnitude,
  RegimeContext,
  RegimeForecastSection,
  RiskForecast,
  ScenarioArchetype,
  ScenarioForecast,
  StructuredForecastSections,
} from "./forecast-hierarchy";

import type { ForecastHierarchyOutput, StructuredForecastSections } from "./forecast-hierarchy";

export interface TickerAnalysisPayload {
  ml_score?: number | null;
  shap_available?: boolean;
  shap_top_factors?: { feature: string; contribution: number }[] | null;
  data_gaps?: string[];
  factor_exposures?: Record<string, number>;
  risk_metrics?: Record<string, number>;
}

export interface ForecastData {
  symbol: string;
  instrument_id: number;
  dominant_regime: string | null;
  regime_distribution: Record<string, number>;
  composite_risk_score: number;
  confidence: number;
  calibrated_confidence?: number | null;
  risk_flags: string[];
  factor_exposures: Record<string, number>;
  probability_map: Record<string, number>;
  metric_validity?: Record<string, boolean>;
  data_quality?: Record<string, string>;
  forecast_explanation: string | null;
  regime_explanation: string | null;
  risk_explanation: string | null;
  risk_engine_metrics: Record<string, unknown>;
  source_metrics: Record<string, unknown>;
  structured?: StructuredForecastSections | null;
  as_of?: string | null;
  snapshot_id?: string | null;
  /** Prompt 38 orchestrator output — populated when backend ships full hierarchy. */
  hierarchy?: ForecastHierarchyOutput | null;
  /** Alias some backends may use for the same payload. */
  forecast_output?: ForecastHierarchyOutput | null;
  /** Backend field name from GET /forecast/{symbol}. */
  hierarchy_output?: Record<string, unknown> | ForecastHierarchyOutput | null;
  action_recommendation?: string | null;
  narrator_insights?: string[];
  scenario_disclosure?: ScenarioDisclosure | null;
  llm_narrative?: string | null;
  ticker_analysis?: TickerAnalysisPayload | null;
  ensemble_forecast?: import("@/components/forecasting/ForecastEnsemblePanel").EnsembleForecastData | null;
  conformal_intervals?: import("@/components/forecasting/ForecastEnsemblePanel").ConformalIntervalData | null;
  bull_base_bear?: import("@/components/forecasting/BullBaseBearPanel").BullBaseBearScenario[];
  global_macro?: import("@/components/forecasting/GlobalMacroPanel").GlobalMacroData | null;
  track_record_chart?: import("@/components/forecasting/TrackRecordPanel").TrackRecordChartData | null;
  live_direction_accuracy?: LiveDirectionAccuracy | null;
  market_beat?: MarketBeatData | null;
}

export interface MarketBeatSubscore {
  available: boolean;
  score?: number | null;
  p?: number | null;
}

export interface DailyBookHolding {
  symbol: string;
  score_20: number;
  p_beat_20?: number | null;
  weight: number;
}

export interface ForecastTearSheet {
  as_of?: string;
  excess?: number | null;
  book_return?: number | null;
  turnover?: number | null;
  scheme?: string;
  count?: number;
  note_ru?: string;
  ece?: { n?: number; ece?: number; reliable?: boolean };
  deflated_sharpe?: { n?: number; sharpe?: number; dsr?: number };
}

export interface DailyBook {
  as_of: string;
  holdings: DailyBookHolding[];
  count: number;
  scheme?: string;
  note_ru?: string;
  deflated_sharpe?: { n?: number; sharpe?: number; dsr?: number };
}

export interface MarketBeatData {
  symbol: string;
  score_20: number;
  /** Kept in the payload; no separate 60-day model exists, so it is not shown. */
  score_60: number;
  /** Model horizons: 1, 5 and 21 sessions (score_21 = score_20). */
  score_1?: number;
  score_5?: number;
  score_21?: number;
  p_beat_20: number;
  p_beat_60: number;
  benchmark_hint?: string;
  explanation_ru: string;
  subscores?: {
    technical?: MarketBeatSubscore | null;
    fundamental?: MarketBeatSubscore | null;
    news?: MarketBeatSubscore | null;
  };
  selection?: string;
  timing?: string;
  timing_ru?: string;
  timing_source?: string;
  timing_trained?: boolean;
  model_accepted?: boolean;
  score_trusted?: boolean;
  ece?: number | null;
  live_accuracy?: number | null;
  live_n: number;
}

export interface LiveDirectionAccuracy {
  accuracy: number | null;
  sample_size: number;
  ci_low?: number | null;
  ci_high?: number | null;
  horizon_days?: number;
  window_days?: number;
  formatted_ru?: string;
}

export interface MarketPredictionSummary {
  paragraphs: string[];
  coverage: string[];
  engines_used: string[];
  evidence: string[];
  missing_resources: string[];
  confidence_pct: number;
}

export interface ScenarioDisclosureScenario {
  archetype: string;
  label_ru?: string;
  probability: number;
  impact?: number | null;
}

export interface ScenarioDisclosure {
  paragraphs: string[];
  top_scenario: string;
  top_probability: number;
  second_scenario?: string | null;
  second_probability?: number | null;
  scenarios?: ScenarioDisclosureScenario[];
  evidence?: string[];
  engines_used?: string[];
  scope?: string;
  layers?: Record<string, unknown>;
  breakdown?: Record<string, number>;
  freshness?: Record<string, unknown>;
  expected_move?: number;
  volatility_regime?: string;
  risk_action?: string;
  confidence?: number;
}

export interface MacroBlock {
  indicators: Record<string, number>;
  report_mode: string;
  missing_resources: string[];
  upcoming_releases: Array<Record<string, unknown>>;
  as_of?: string | null;
}

export interface MarketForecastData {
  as_of: string;
  global_regime: Record<string, unknown>;
  /** Legacy string bullets or enhanced MarketOutlookPoint objects. */
  market_outlook: import("./forecast-hierarchy").MarketOutlookEntry[];
  /** Optional structured cards — scaffolded client-side when absent. */
  market_outlook_cards?: import("./forecast-hierarchy").MarketOutlookCard[];
  sector_rotation: Record<string, unknown>[];
  calibrated_probabilities: Record<string, number>;
  macro_indicators: Record<string, number>;
  macro_block?: MacroBlock | null;
  market_prediction_summary?: MarketPredictionSummary | null;
  scenario_disclosure?: ScenarioDisclosure | null;
  llm_narrative?: string | null;
}

export type StrategyType =
  | "momentum" | "mean_reversion" | "breakout"
  | "grid" | "event_driven" | "trend_following"
  | "macro" | "no_trade";

export type Direction = "long" | "short" | "neutral";
export type TradingMode = "paper" | "live";

export interface Maneuver {
  id: string;
  rank: number;
  ticker: string;
  strategy_type: StrategyType;
  direction: Direction;
  entry_zone_low: number | null;
  entry_zone_high: number | null;
  exit_zone_low: number | null;
  exit_zone_high: number | null;
  stop_loss: number | null;
  take_profit: number | null;
  invalidation_level: number | null;
  risk_percent: number;
  position_size_usd: number;
  expected_return_low: number | null;
  expected_return_high: number | null;
  expected_pnl_low: number | null;
  expected_pnl_high: number | null;
  confidence: number;
  time_horizon: string;
  catalyst: string | null;
  rationale: string | null;
  execution_plan: string | null;
  status: ManeuverStatus;
  trading_mode: TradingMode;
  approved_at: string | null;
  filled_at: string | null;
  fill_price: number | null;
  exit_price?: number | null;
  realized_pnl: number | null;
  exit_reason?: string | null;
  created_at: string;
  closed_at?: string | null;
  avg_entry_price?: number | null;
  // Live position enrichment (optional — backend may not populate yet)
  approx_profit?: number | null;
  unrealized_pnl?: number | null;
  time_to_close?: number | string | null;
  current_price?: number | null;
  /** P(hit TP before horizon expiry), 0–1 */
  tp_hit_probability?: number | null;
  profit_disclosure?: string | null;
  horizon_expired?: boolean | null;
  /** Absolute UTC ISO timestamp when the maneuver horizon expires. */
  horizon_end_at?: string | null;
  /** Alias of horizon_end_at for clients that expect explicit expiry naming. */
  expiry_at?: string | null;
  signal_meta?: Record<string, unknown> | null;
  regime_context?: string | null;
  key_drivers?: Array<{ feature: string; contribution: number; label?: string }> | null;
  risk_flags?: string[] | null;
  suggested_position_pct?: number | null;
}

export interface ManeuverApprovalOptions {
  time_horizon?: string;
  expiry_at?: string;
}

export interface TradeMarker {
  maneuver_id: string;
  side: "buy" | "sell" | string;
  kind: "entry" | "exit" | string;
  price: number;
  at: string;
  size_usd: number;
  qty?: number | null;
  label?: string | null;
}

export interface TickerBookLeg {
  maneuver_id: string;
  side: string;
  fill_price: number | null;
  size_usd: number;
  qty: number | null;
  stop_loss: number | null;
  take_profit: number | null;
  filled_at: string | null;
}

export interface TickerBook {
  ticker: string;
  avg_entry: number | null;
  avg_long?: number | null;
  avg_short?: number | null;
  qty?: number;
  qty_long?: number;
  qty_short?: number;
  exposure_usd: number;
  long_usd?: number;
  short_usd?: number;
  open_legs: number;
  net_side: string;
  dual?: boolean;
  mark_price?: number | null;
  breakeven?: number | null;
  breakeven_long?: number | null;
  breakeven_short?: number | null;
  unrealized_usd?: number | null;
  unrealized_pct?: number | null;
  strategy_low: number | null;
  strategy_high: number | null;
  risk_low?: number | null;
  risk_high?: number | null;
  avg_in_strategy_zone: boolean | null;
  zone_edge_pct?: number | null;
  legs?: TickerBookLeg[];
  markers: TradeMarker[];
  pnl_if_flat_hint?: string | null;
}

/** Robot Core level line (from RobotPlan.levels). */
export interface RobotLevel {
  id?: string;
  kind: "entry" | "add" | "tp" | "sl" | "trail" | string;
  side?: string;
  price?: number | null;
  size_pct?: number;
  status?: string;
  fill_price?: number | null;
  trail_pct?: number;
  activate_at?: number | null;
}

export interface RobotPlan {
  id: string;
  ticker: string;
  maneuver_id?: string | null;
  status: string;
  side: string;
  mode: string;
  levels: RobotLevel[];
  kill_switch_pct?: number | null;
  notes?: string | null;
  plan_type?: string;
  plan_params?: Record<string, unknown>;
  capabilities?: {
    mode?: string;
    live?: string[];
    paper?: string[];
    note?: string;
  };
  session_id?: string | null;
  is_legacy?: boolean;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface RobotLotBook {
  ticker: string;
  side: string;
  qty: number;
  avg_entry: number | null;
  cost_basis_usd: number;
  fee_usd: number;
  funding_usd?: number;
  open_lots: number;
  breakeven: number | null;
  lots: Array<{
    id: string;
    side: string;
    qty_open: number;
    entry_price: number;
    opened_at?: string | null;
    maneuver_id?: string | null;
    source?: string;
  }>;
  plans: RobotPlan[];
  avg_long?: number | null;
  avg_short?: number | null;
  qty_long?: number;
  qty_short?: number;
  breakeven_long?: number | null;
  breakeven_short?: number | null;
  net_breakeven?: number | null;
  dual?: boolean;
}

export interface ManeuverReport {
  id: string;
  created_at: string;
  watchlist: string[];
  pipeline_run_id: string;
  text_summary: string | null;
  regime: string | null;
  market_context: Record<string, unknown>;
  status: string;
  maneuvers: Maneuver[];
}

export interface PipelineRunResponse {
  run_id: string;
  task_id?: string;
  status: string;
  message: string;
  report_id?: string;
  eta_seconds?: number;
  tradeable_count?: number;
  maneuver_slots?: number;
}

export type ManualOrderSide = "buy" | "sell";
export type ManualOrderType =
  | "market"
  | "limit"
  | "stop"
  | "stop_limit"
  | "oco"
  | "trailing_stop";

export interface OrderBookLevel {
  price: number;
  size: number;
}

export interface OrderBookSnapshot {
  ticker: string;
  bids: OrderBookLevel[];
  asks: OrderBookLevel[];
  mid_price: number | null;
  spread_bps: number | null;
  source?: string | null;
  as_of?: string | null;
  depth_available?: boolean;
  session_label?: string | null;
  /** Provider/session why L2 is missing (distinct from CLOSED banner). */
  depth_unavailable_reason?: string | null;
  exchange_id?: string | null;
  exchange_name_ru?: string | null;
  session_status?: "open" | "closed" | "pre" | "post" | null;
  session_message_ru?: string | null;
}

export interface RecentTrade {
  id: string;
  price: number;
  size: number;
  side: "buy" | "sell" | null;
  ts: string;
  source: string;
}

export interface SymbolTradingRules {
  ticker: string;
  venue: string;
  tick_size: number;
  lot_size: number;
  min_qty: number;
  min_notional_usd?: number;
  price_decimals?: number;
  qty_decimals?: number;
  data_only?: boolean;
  execution_enabled?: boolean;
  feed_label_ru?: string | null;
  bybit_tokenized_listed?: boolean | null;
  execution_block_type?: "unavailable" | "connect_provider" | null;
  globally_tradeable?: boolean | null;
  required_providers_ru?: string[] | null;
}

export interface SlippageEstimate {
  estimated_slippage_bps: number;
  estimated_avg_fill: number | null;
  warning: string | null;
  visible_liquidity_usd: number;
}

export interface OrderTicketPrefill {
  ticker: string;
  side: ManualOrderSide;
  quantity: number;
  limit_price: number | null;
  stop_price: number | null;
  take_profit: number | null;
  stop_loss: number | null;
  position_size_usd: number;
  position_pct: number;
  maneuver_id: string;
  direction: string;
  time_horizon?: string | null;
  expiry_at?: string | null;
  bracket?: { stop_loss?: number | null; take_profit?: number | null } | null;
}

export interface ManualOrder {
  id: string;
  ticker: string;
  side: ManualOrderSide;
  order_type: ManualOrderType;
  quantity: number;
  limit_price: number | null;
  stop_price: number | null;
  time_in_force: string;
  status: string;
  maneuver_id: string | null;
  fill_price: number | null;
  slippage_warning: string | null;
  submitted_at: string;
  filled_at: string | null;
  error_message: string | null;
}

export interface LivePerformanceMetrics {
  label: string;
  sharpe_ratio: number | null;
  win_rate: number | null;
  expectancy_usd: number | null;
  max_drawdown_pct: number | null;
  sample_size: number;
  backtest_sharpe: number | null;
  backtest_win_rate: number | null;
  calibration_error: number | null;
  as_of: string;
}

export interface ModelDriftSnapshot {
  live_accuracy: number | null;
  backtest_accuracy: number | null;
  accuracy_gap: number | null;
  alert: boolean;
  alert_message: string | null;
  as_of: string;
}

export interface UserSettings {
  portfolio_size: number;
  max_risk_per_trade_pct: number;
  confidence_threshold: number;
  daily_max_loss_pct: number;
  default_watchlist: string[];
  paper_trading_enabled: boolean;
  live_trading_enabled: boolean;
  tokenized_equity_provider?: "bybit" | "mexc";
  /** Account total; trading cap cannot exceed this. */
  cap_max_usd?: number;
}

export interface BacktestResult {
  id: string;
  strategy: string;
  ticker: string;
  start_date: string;
  end_date: string;
  initial_capital: number;
  final_capital: number | null;
  total_return_pct: number | null;
  sharpe_ratio: number | null;
  max_drawdown_pct: number | null;
  total_trades: number | null;
  win_rate: number | null;
  status: string;
  created_at: string;
  completed_at: string | null;
  metrics: Record<string, number>;
}

export interface AuditLog {
  id: string;
  timestamp: string;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  details: Record<string, unknown>;
  ip_address: string | null;
  success: boolean;
  error: string | null;
}

export interface User {
  id: string;
  email: string;
  role: string;
  is_active: boolean;
  is_whitelisted: boolean;
  created_at: string;
  last_login: string | null;
}

export interface AccountUser {
  id: string;
  email: string;
  name: string;
  role: string;
  created_at: string;
  last_login: string | null;
}

export interface AccountBalance {
  total_usd: number;
  free_usd: number;
  locked_usd: number;
  currency: string;
  mode: string;
  is_paper: boolean;
  as_of: string;
}

export interface PortfolioPosition {
  ticker: string;
  market_value_usd: number | null;
  side: string;
  position_count: number;
}

export interface AccountPortfolio {
  id: string;
  name: string;
  mode: string;
  base_currency: string;
  market_value_usd: number | null;
  positions: PortfolioPosition[];
}

export interface AccountSummary {
  user: AccountUser;
  balance: AccountBalance;
  portfolios: AccountPortfolio[];
}

export interface PaperTransferResult {
  transaction_type: "deposit" | "withdraw";
  amount_usd: number;
  balance: AccountBalance;
  message: string;
}

export interface TokenResponse {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
  must_change_password?: boolean;
  webauthn_required?: boolean;
  webauthn_registration_required?: boolean;
  pending_approval?: boolean;
  two_factor_required?: boolean;
  two_factor_pending_token?: string;
  two_factor_backup_allowed?: boolean;
  two_factor_enrollment_required?: boolean;
}

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
  pages: number;
  meta?: Record<string, unknown> | null;
}

/** Server-trusted freshness metadata on open-positions list / WS snapshot. */
export interface LiveSnapshotMeta {
  server_now: string;
  last_refresh_at: string;
  data_freshness_seconds: number;
  stale: boolean;
}

export interface PositionsSnapshot {
  items: Maneuver[];
  total: number;
  live_snapshot: LiveSnapshotMeta;
}

export interface HealthStatus {
  status: string;
  version?: string;
  env?: string;
  db: string;
  redis: string;
  trading_mode: string;
}

export interface PilotLimits {
  enabled: boolean;
  max_notional_per_order: number;
  max_daily_loss: number;
  max_orders_per_session: number;
  source: string;
}

export interface PilotVenue {
  enabled: boolean;
  allowed_venue: string;
  allowed_symbols: string[];
  source: string;
}

export interface PilotAuditPaths {
  stop_drill: string;
  signoff: string;
  pilot_root: string;
}

export interface PilotDocsLink {
  name: string;
  path: string;
}

export interface GridBotTestCounts {
  gate_label: string;
  command: string;
  expected_count: number;
}

export interface KillSwitchDrillStatus {
  data_dir: string;
  exists: boolean;
  audit_file: string | null;
  passed: boolean | null;
  session_id: string | null;
  drill_id: string | null;
  ts_utc: string | null;
  drill_command: string;
  docs_path: string;
}

export interface VenueConnectivity {
  venue: string;
  configured: boolean;
  mode: string;
  detail: string;
}

export interface LastPipelineRun {
  run_id: string | null;
  report_id: string | null;
  status: string;
  triggered_by: string | null;
  completed_at: string | null;
  watchlist_count: number;
}

export interface GridBotTickStatus {
  enabled: boolean;
  schedule: string;
  active_bots: number;
  last_tick_at: string | null;
  last_tick_status: string | null;
  last_updated_bots: number;
  last_fills: number;
}

export interface ForecastRefreshStatus {
  enabled: boolean;
  schedule: string;
  last_refresh_at: string | null;
  last_status: string | null;
  symbols_saved: number;
  watchlist_size: number;
}

export interface PaperCapabilities {
  grid_bots?: boolean;
  maneuver_execution?: boolean;
  pipeline_auto_execute?: boolean;
  market_data?: boolean;
  news_ingestion?: boolean;
  backtest?: boolean;
  requires_live_keys_for?: string[];
}

export interface PilotStatus {
  phase4_bundle_command: string;
  pilot_limits: PilotLimits;
  pilot_venue: PilotVenue;
  venue_connectivity: VenueConnectivity[];
  app_trading_mode: string;
  paper_trading_enabled: boolean;
  live_trading_enabled: boolean;
  paper_capabilities: PaperCapabilities;
  last_pipeline_run: LastPipelineRun;
  grid_bot_tick: GridBotTickStatus;
  forecast_refresh: ForecastRefreshStatus;
  audit_paths: PilotAuditPaths;
  last_drill_files: string[];
  grid_bot_test_counts: GridBotTestCounts;
  docs_links: PilotDocsLink[];
  kill_switch_drill: KillSwitchDrillStatus;
}

/** Per-venue capital breakdown (Binance / Finam / Tinkoff / …). */
export interface VenueBalance {
  venue: string;
  configured?: boolean;
  mode?: string | null;
  /** True only when a live balance was actually fetched (stubs stay false). */
  refreshed?: boolean;
  trading_usd?: number | null;
  balance_usd: number;
  total_usd?: number | null;
  currency?: string | null;
  detail?: string | null;
  error?: string | null;
}

/** Response of GET /portfolio/balances and POST /ops/refresh-venue-balances. */
export interface VenueBalancesResponse {
  venues: VenueBalance[];
  total_trading_usd?: number;
  total_balance_usd?: number;
  total_usd?: number;
  currency?: string;
  as_of?: string;
}

export interface PortfolioMetrics {
  trading_usd: number;
  balance_usd: number;
  total_usd: number;
  currency: string;
  mode: TradingMode;
  source: "alpaca" | "internal" | "broker" | "broker_unavailable" | "no_live_broker";
  open_maneuvers: number;
  active_grid_bots: number;
  as_of: string;
  exposure_pct?: number;
  max_exposure_pct?: number;
  cash_buffer_usd?: number;
  max_position_usd?: number;
  max_position_pct?: number;
  /** Live net unrealized on open book (matches positions tab). */
  unrealized_pnl_usd?: number;
  /** Closed maneuver realized P&L summed into paper equity. */
  realized_pnl_usd?: number;
  deployed_notional_usd?: number;
  /** Operator-configured deploy cap (settings.portfolio_size) — not exchange balance. */
  portfolio_allocation_usd?: number;
  /** Live free balance from connected venues when fetched this session. */
  account_balance_usd?: number | null;
  /** Live total balance from connected venues when fetched this session. */
  account_total_usd?: number | null;
  /** Optional per-venue breakdown if metrics payload is enriched later. */
  venue_balances?: VenueBalance[];
}

export interface PortfolioRefreshResult extends PortfolioMetrics {
  deactivated_grid_bots: number;
  released_capital_usd: number;
  reconciled_at: string;
}

export interface RiskStatus {
  level: "ok" | "caution" | "block";
  label: string;
  explanation: string;
  contributing_factors: string[];
  exposure_pct: number;
  max_exposure_pct: number;
  daily_max_loss_pct: number;
  open_maneuvers: number;
  trading_usd: number;
  cash_buffer_usd: number;
  as_of: string;
}

/** Result of POST /ops/run-stop-drill (kill-switch drill). */
export interface StopDrillResult {
  passed: boolean;
  session_id?: string | null;
  reason?: string | null;
  data_dir?: string | null;
  audit_file?: string | null;
  staging?: boolean;
  production_mutation?: boolean;
  report?: Record<string, unknown>;
  error?: string | null;
  /** Convenience aliases frontend may also read from legacy shapes. */
  drill_id?: string | null;
  ts_utc?: string | null;
  message?: string | null;
}

/** Result of POST /ops/refresh-venue-balances (= VenueBalancesResponse). */
export type RefreshVenueBalancesResult = VenueBalancesResponse & {
  status?: string;
  refreshed?: number | null;
  message?: string | null;
  /** Defensive alias — some clients may echo venue_balances. */
  venue_balances?: VenueBalance[];
};

/** One position affected by a flatten / close-all operation. */
export interface ClosedPosition {
  id: string;
  ticker: string;
  direction: string;
  status_before: string;
  action: "closed" | "cancelled" | string;
  size_usd: number;
  realized_pnl?: number | null;
  close_price?: number | null;
}

/** Result of POST /ops/close-all-positions (flatten the paper book). */
export interface CloseAllPositionsResult {
  mode: string;
  closed_count: number;
  cancelled_count: number;
  realized_pnl_total: number;
  freed_exposure_usd: number;
  message?: string | null;
  positions?: ClosedPosition[];
}

export interface PositionAuditStatus {
  expiration_close_count: number;
  required_count: number;
  ready_to_trigger: boolean;
  audit_running: boolean;
  message_ru: string;
  last_audit_id?: string | null;
  last_audit_completed_at?: string | null;
}

export interface PositionAuditTriggerResult {
  status: "insufficient" | "already_running" | "queued" | string;
  audit_id?: string | null;
  expiration_close_count: number;
  required_count?: number;
  message_ru?: string;
}

export interface PositionAuditSummary {
  status: string;
  audit_id?: string | null;
  completed_at?: string | null;
  total_pnl_usd?: number;
  total_pnl_pct?: number;
  win_rate?: number;
  top_tickers?: Array<{ ticker: string; pnl_usd: number }>;
  capital_return_pct?: number;
  most_common_maneuver?: string;
  trade_count?: number;
  message_ru?: string;
}

/** GET /ops/llm-status — global navbar AI indicator. */
export interface LlmStatus {
  available: boolean;
  message_ru: string;
  reason?: string | null;
  balance_rub?: number | null;
}

/** Result of POST /ops/run-market-analysis. */
export interface MarketAnalysisResult {
  run_id?: string | null;
  task_id?: string | null;
  status: string;
  message?: string | null;
  watchlist?: string[];
}

export interface NewsArticle {
  id: string;
  title: string;
  description?: string | null;
  title_ru?: string | null;
  summary_ru?: string | null;
  is_machine_translated?: boolean;
  url: string;
  source: string;
  published_at: string;
  sentiment_score: number | null;
  sentiment_label: string | null;
  tickers_mentioned: string[];
  relevance_score: number;
  /** Present only on client-side demo fallback items */
  is_demo?: boolean;
}

export interface OHLCVBar {
  ticker: string;
  timestamp: string;
  timeframe: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  vwap: number | null;
}

// ── Asset Cockpit (Prompt 9) ────────────────────────────────────────────────

export type CockpitLookback = "1D" | "1W" | "1M" | "3M" | "6M" | "1Y";

export interface CockpitPriceRange {
  period_low: number;
  period_high: number;
  range_pct: number;
}

export interface CockpitVolatilityBands {
  mid: number;
  upper: number;
  lower: number;
  realized_vol: number;
}

export interface CockpitCorrelationPeer {
  symbol: string;
  correlation: number;
  relation: string;
}

export interface CockpitIntentSummary {
  id: string;
  status: string;
  strategy: string;
  direction: string;
  risk_tag: string;
  approval_state: string;
  created_at: string;
}

export interface CockpitSleeveBudget {
  sleeve_id: string;
  sleeve_name: string;
  risk_budget: number;
  risk_used: number;
  risk_remaining: number;
  status: string;
}

export interface CockpitMacroEvent {
  id: string;
  title: string;
  event_type: string;
  scheduled_at: string | null;
  source: string;
  is_stub: boolean;
}

export interface CockpitDecisionExplanation {
  decision_type: string;
  summary: string;
  text: string;
  timestamp: string | null;
  source_metrics: Record<string, unknown>;
}

export interface CockpitExplainability {
  headline: string;
  regime_explanation: string | null;
  factor_explanation: string | null;
  forecast_explanation: string | null;
  risk_explanation: string | null;
  recent_decisions: CockpitDecisionExplanation[];
  source_metrics: Record<string, unknown>;
}

export interface AssetCockpitData {
  symbol: string;
  instrument_id: number | null;
  category: string | null;
  tradable_unit: string;
  price: number | null;
  change_pct: number | null;
  quote_source: string | null;
  regime: string;
  regime_label: string;
  price_range: CockpitPriceRange;
  volatility_bands: CockpitVolatilityBands;
  liquidity_state: string;
  spread_state: string;
  spread_bps: number;
  sector: string | null;
  sector_relation: string;
  correlations: CockpitCorrelationPeer[];
  bot_suitability_score: number;
  allowed_strategies: string[];
  intents: CockpitIntentSummary[];
  sleeve_budget: CockpitSleeveBudget | null;
  news: NewsArticle[];
  macro_events: CockpitMacroEvent[];
  recent_actions: AuditLog[];
  why_so: CockpitExplainability | null;
  metadata: Record<string, unknown>;
}

export interface DirectDealsSymbol {
  symbol: string;
  name: string | null;
  asset_class: string;
  exchange: string;
  source: string;
  tradable_unit: string;
  bybit_tokenized?: boolean;
  bybit_tokenized_available?: boolean | null;
  unavailable_reason_ru?: string | null;
  execution_available_globally?: boolean | null;
  execution_hint_ru?: string | null;
  required_provider_ru?: string | null;
}

// ── Strategy Composer ─────────────────────────────────────────────────────────

export type ComposerField =
  | "volatility_percentile"
  | "volatility"
  | "regime"
  | "microstructure_score"
  | "session_active";

export type ComposerOperator = "gt" | "gte" | "lt" | "lte" | "eq" | "neq" | "in";

export interface ComposerPredicate {
  field: ComposerField;
  operator: ComposerOperator;
  value: number | boolean | string | string[];
}

export interface ComposerConditionGroup {
  id: string;
  logic: "and" | "or";
  predicates: ComposerPredicate[];
}

export interface ComposerOutcome {
  id: string;
  label: string;
  primary_strategy: string;
  grid_mode?: string | null;
}

export interface ComposerBranch {
  id: string;
  condition: ComposerConditionGroup;
  then_outcome_id: string;
  else_outcome_id?: string | null;
  else_branch_id?: string | null;
}

export interface ComposerConfig {
  version: number;
  name: string;
  root_branch_id: string;
  branches: ComposerBranch[];
  outcomes: ComposerOutcome[];
  default_outcome_id: string;
}

export interface ComposerValidationResult {
  valid: boolean;
  errors: string[];
  warnings: string[];
}

export interface CompiledOutcome {
  primary_strategy: string;
  grid_mode?: string | null;
}

export interface CompiledRule {
  branch_id: string;
  logic: "and" | "or";
  conditions: Record<string, unknown>[];
  then: CompiledOutcome;
  else_outcome?: CompiledOutcome | null;
  else_branch_id?: string | null;
}

export interface CompiledStrategyConfig {
  version: number;
  name: string;
  rules: CompiledRule[];
  default: CompiledOutcome;
}

export interface ComposerSchema {
  fields: { id: string; label: string }[];
  operators: string[];
  strategies: string[];
  grid_modes: string[];
  regime_values: string[];
  regime_aliases: Record<string, string[]>;
}


export interface PortfolioRiskHolding {
  symbol: string;
  notional_usd: number;
  weight: number;
  sector: string;
}

export interface PortfolioStressResult {
  scenario_id: string;
  label_ru: string;
  start: string;
  end: string;
  description_ru: string;
  total_return: number | null;
  max_drawdown: number | null;
  worst_day_return?: number | null;
  observations?: number;
  methodology_ru?: string;
}

export interface PortfolioRiskAnalytics {
  computed_at: string;
  lookback_start?: string;
  lookback_end?: string;
  lookback_days: number;
  data_as_of: string;
  nav_usd: number;
  holdings: PortfolioRiskHolding[];
  sector_weights: Record<string, number>;
  var_95: number | null;
  var_99: number | null;
  expected_shortfall_95: number | null;
  var_95_usd: number | null;
  var_99_usd: number | null;
  expected_shortfall_95_usd: number | null;
  observations?: number;
  alpha: number | null;
  beta: number | null;
  r_squared?: number | null;
  avg_pairwise_correlation: number | null;
  concentration_share: number | null;
  concentration_flag_ru?: string | null;
  stress: PortfolioStressResult[];
  insufficient_data: boolean;
  methodology: Record<string, unknown>;
  notes: string[];
}

export interface ComposerBacktestResult {
  symbol: string;
  start?: string;
  end?: string;
  observations: number;
  in_market_days?: number;
  win_rate: number | null;
  max_drawdown: number | null;
  total_return: number | null;
  purged_cv_win_rate: number | null;
  purged_folds: number;
  insufficient_data: boolean;
  methodology?: Record<string, unknown>;
  notes: string[];
}
