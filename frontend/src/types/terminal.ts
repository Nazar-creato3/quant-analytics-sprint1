/** Types for `/api/v1/terminal/*` — snapshot-first, sub-endpoint fallback, mock-friendly. */

export type TerminalSection = "market" | "economic" | "quant" | "agents";

export type TerminalDensity = "comfortable" | "compact";

export type TerminalSessionStatus =
  | "open"
  | "closed"
  | "pre"
  | "post"
  | "holiday"
  | "unknown";

export interface TerminalIndexRow {
  symbol: string;
  name?: string;
  price: number | null;
  change: number | null;
  change_pct: number | null;
  session?: TerminalSessionStatus | string | null;
  region?: string | null;
  currency?: string | null;
  stale?: boolean;
  reason?: string | null;
}

export interface TerminalPerformanceRow {
  label: string;
  period: string;
  /** null = no data — never fabricate 0% */
  value: number | null;
  unit?: "pct" | "level";
  reason?: string | null;
}

export interface TerminalMover {
  symbol: string;
  change_pct: number | null;
  price?: number | null;
  volume?: number | null;
  volume_label?: string | null;
}

export interface TerminalSnapshotItem {
  symbol: string;
  label?: string;
  value: number | null;
  change_pct: number | null;
  unit?: string | null;
  reason?: string | null;
}

export interface TerminalPulse {
  fear_greed: number | null;
  label: string;
  breadth: Array<{
    exchange: string;
    advancers: number;
    decliners: number;
  }>;
  gainers: TerminalMover[];
  losers: TerminalMover[];
  global_snapshot?: TerminalSnapshotItem[];
  vol_regime?: string | null;
  reason?: string | null;
}

export interface TerminalRiskSummary {
  score: number | null;
  label: string;
  var_pct?: number | null;
  high_beta: Array<{
    symbol: string;
    price?: number | null;
    beta?: number | null;
    change_pct: number | null;
    day_high?: number | null;
    day_low?: number | null;
    note?: string | null;
  }>;
  reason?: string | null;
}

export interface TerminalNewsItem {
  id: string;
  headline: string;
  source: string;
  published_at: string;
  url?: string | null;
  summary?: string | null;
}

export interface TerminalCalendarEvent {
  id: string;
  title: string;
  when: string;
  region?: string;
  importance?: "low" | "medium" | "high";
  expected?: string | null;
  actual?: string | null;
  previous?: string | null;
  forecast?: string | null;
}

export interface TerminalWatchItem {
  symbol: string;
  last: number | null;
  change?: number | null;
  change_pct: number | null;
  change_1d?: number | null;
  change_1w?: number | null;
  change_1m?: number | null;
  change_3m?: number | null;
  volume?: number | null;
  vol?: number | null;
  regime?: string | null;
  risk?: string | number | null;
  sector?: string | null;
  session?: TerminalSessionStatus | string | null;
  feed?: "live" | "delayed" | "stale" | "eod" | "forex" | "unknown" | string | null;
  data_only?: boolean;
  execution_enabled?: boolean;
  feed_label_ru?: string | null;
  reason?: string | null;
  currency?: string | null;
  bid?: number | null;
  ask?: number | null;
  routing_class?: string | null;
  show_volume?: boolean | null;
}

export interface TerminalAlert {
  id: string;
  severity: "info" | "warn" | "critical";
  title: string;
  body?: string;
  ts: string;
}

export interface TerminalQuantFactor {
  id: string;
  name: string;
  weight?: number | null;
  contribution?: number | null;
  value?: string | number | null;
  source?: string | null;
  freshness?: string | null;
  confidence?: number | null;
  tip?: string | null;
}

export interface TerminalQuantMetric {
  id: string;
  label: string;
  value: string;
  delta?: number | null;
  hint?: string;
  weight?: number | null;
  contribution?: number | null;
  source?: string | null;
  freshness?: string | null;
  confidence?: number | null;
  tip?: string | null;
}

export interface TerminalAgentCard {
  id: string;
  name: string;
  category: string;
  status: "idle" | "running" | "ready" | "error";
  summary?: string;
}

export interface TerminalChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  body: string;
  ts: string;
}

export interface TerminalChartPoint {
  t: number;
  v: number;
}

export interface TerminalChartBar {
  t: number;
  o: number;
  h: number;
  l: number;
  c: number;
}

export interface TerminalChartSeries {
  symbol: string;
  points: TerminalChartPoint[];
  /** Full OHLC when available (candlestick rendering). */
  bars?: TerminalChartBar[];
}

export interface TerminalTapeItem {
  id: string;
  kind: "index" | "mover" | "vix" | "headline" | "macro";
  symbol?: string;
  label: string;
  value?: number | null;
  change_pct?: number | null;
  text?: string;
}

export interface TerminalMarketHoursRow {
  id: string;
  exchange: string;
  name?: string;
  status: TerminalSessionStatus;
  local_time?: string | null;
  opens_in?: string | null;
  timezone?: string | null;
}

export interface TerminalPortfolioPosition {
  symbol: string;
  shares?: number | null;
  price?: number | null;
  value?: number | null;
  pnl?: number | null;
  pnl_pct?: number | null;
  weight?: number | null;
  sector?: string | null;
}

export interface TerminalPortfolio {
  total_value: number | null;
  day_pnl: number | null;
  day_pnl_pct: number | null;
  total_pnl: number | null;
  total_pnl_pct: number | null;
  holdings: number;
  cash?: number | null;
  drawdown?: number | null;
  concentration?: string | null;
  exposures?: Array<{ label: string; value: number | null; unit?: string }>;
  allocations?: Array<{ label: string; weight: number | null }>;
  positions: TerminalPortfolioPosition[];
  empty_reason?: string | null;
  connected?: boolean;
}

export interface TerminalSnapshot {
  as_of: string;
  source: "live" | "mock" | "partial";
  indices: TerminalIndexRow[];
  performance: TerminalPerformanceRow[];
  pulse: TerminalPulse;
  risk: TerminalRiskSummary;
  news: TerminalNewsItem[];
  calendar: TerminalCalendarEvent[];
  watchlist: TerminalWatchItem[];
  alerts: TerminalAlert[];
  quant: TerminalQuantMetric[];
  quant_factors?: TerminalQuantFactor[];
  agents: TerminalAgentCard[];
  chart: TerminalChartSeries;
  tape?: TerminalTapeItem[];
  market_hours?: TerminalMarketHoursRow[];
  portfolio?: TerminalPortfolio | null;
  data_notes?: string[];
}

export type TerminalWsMessage =
  | { type: "snapshot"; data: TerminalSnapshot }
  | {
      type: "tick";
      data: Partial<
        Pick<TerminalSnapshot, "indices" | "watchlist" | "pulse" | "tape" | "market_hours">
      >;
    }
  | { type: "alert"; data: TerminalAlert }
  | { type: "connected"; message?: string; ts?: string }
  | { type: "heartbeat"; ts?: string }
  | { type: "pong"; ts?: string }
  | { type: "ping" };
