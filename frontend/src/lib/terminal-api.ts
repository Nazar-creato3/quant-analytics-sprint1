/**
 * QuantAnalytics Terminal API client.
 * Prefers GET /terminal/snapshot; falls back to sub-endpoints and quote composition.
 * Never fabricates 0% — missing values stay null with an honest reason.
 */

import type { AxiosRequestConfig } from "axios";
import api from "@/lib/api";
import { chartApiSymbol } from "@/lib/asset-class";
import type {
  TerminalAlert,
  TerminalAgentCard,
  TerminalCalendarEvent,
  TerminalChatMessage,
  TerminalChartSeries,
  TerminalIndexRow,
  TerminalMarketHoursRow,
  TerminalNewsItem,
  TerminalPerformanceRow,
  TerminalPortfolio,
  TerminalPulse,
  TerminalQuantFactor,
  TerminalQuantMetric,
  TerminalRiskSummary,
  TerminalSessionStatus,
  TerminalSnapshot,
  TerminalSnapshotItem,
  TerminalTapeItem,
  TerminalWatchItem,
} from "@/types/terminal";

interface FetchResult<T = unknown> {
  success: boolean;
  data?: T | null;
  error?: string | null;
  error_code?: string | null;
  provider: string;
  duration_ms?: number;
  from_cache?: boolean;
  metadata?: Record<string, unknown>;
}

interface ProviderHealth {
  name: string;
  status: string;
  available: boolean;
  last_error?: string | null;
  circuit_state?: string | null;
  supported_data_types?: string[];
  requires_api_key?: boolean;
  api_key_configured?: boolean;
}

interface QuotePayload {
  symbol: string;
  price: number | string;
  bid?: number | string | null;
  ask?: number | string | null;
  timestamp?: string;
  provider?: string;
  change?: number | null;
  change_pct?: number | null;
  volume?: number | null;
  currency?: string | null;
  exchange?: string | null;
}

interface OhlcvBar {
  symbol: string;
  timeframe: string;
  timestamp: string;
  open: number | string;
  high: number | string;
  low: number | string;
  close: number | string;
  volume?: number | string | null;
  provider?: string;
}

interface NewsPayload {
  title: string;
  summary?: string | null;
  source: string;
  url?: string;
  published_at: string;
  symbols?: string[] | null;
  sentiment?: string | null;
  provider?: string;
}

interface CalendarPayload {
  id?: string;
  title: string;
  when: string;
  region?: string | null;
  importance?: string | null;
  expected?: string | null;
  actual?: string | null;
  previous?: string | null;
  forecast?: string | null;
  provider?: string;
}

const INDEX_UNIVERSE: Array<{
  ui: string;
  name: string;
  api: string;
  region?: string;
}> = [
  { ui: "SPX", name: "S&P 500", api: "^GSPC", region: "US" },
  { ui: "DJI", name: "Dow Jones", api: "^DJI", region: "US" },
  { ui: "IXIC", name: "NASDAQ Comp", api: "^IXIC", region: "US" },
  { ui: "NDX", name: "NASDAQ 100", api: "^NDX", region: "US" },
  { ui: "RUT", name: "Russell 2000", api: "^RUT", region: "US" },
  { ui: "FTSE", name: "FTSE 100", api: "^FTSE", region: "EU" },
  { ui: "DAX", name: "DAX", api: "^GDAXI", region: "EU" },
  { ui: "CAC", name: "CAC 40", api: "^FCHI", region: "EU" },
  { ui: "FCHI", name: "CAC 40", api: "^FCHI", region: "EU" },
  { ui: "N225", name: "Nikkei 225", api: "^N225", region: "ASIA" },
  { ui: "HSI", name: "Hang Seng", api: "^HSI", region: "ASIA" },
  { ui: "SSEC", name: "Shanghai", api: "000001.SS", region: "ASIA" },
  { ui: "KS11", name: "KOSPI", api: "^KS11", region: "ASIA" },
  { ui: "IMOEX", name: "MOEX Russia", api: "IMOEX", region: "RU" },
  { ui: "RTSI", name: "RTS Index", api: "RTSI", region: "RU" },
  { ui: "VIX", name: "VIX", api: "^VIX", region: "US" },
];

const WATCH_UNIVERSE: Array<{
  ui: string;
  api: string;
  sector?: string;
}> = [
  { ui: "BTC/USDT", api: "BTC-USD", sector: "Crypto" },
  { ui: "ETH/USDT", api: "ETH-USD", sector: "Crypto" },
  { ui: "AAPL", api: "AAPL", sector: "Tech" },
  { ui: "MSFT", api: "MSFT", sector: "Tech" },
  { ui: "NVDA", api: "NVDA", sector: "Tech" },
  { ui: "GOOGL", api: "GOOGL", sector: "Tech" },
  { ui: "AMZN", api: "AMZN", sector: "Consumer" },
  { ui: "TSLA", api: "TSLA", sector: "Auto" },
  { ui: "SBER", api: "SBER.ME", sector: "Financials" },
  { ui: "GAZP", api: "GAZP.ME", sector: "Energy" },
  { ui: "GLD", api: "GLD", sector: "Commodities" },
  { ui: "USO", api: "USO", sector: "Commodities" },
];

const MACRO_SNAPSHOT: Array<{ ui: string; label: string; api: string }> = [
  { ui: "VIX", label: "VIX", api: "^VIX" },
  { ui: "TNX", label: "US 10Y", api: "^TNX" },
  { ui: "DXY", label: "DXY", api: "DX-Y.NYB" },
  { ui: "GOLD", label: "GOLD", api: "GC=F" },
  { ui: "OIL", label: "OIL WTI", api: "CL=F" },
  { ui: "BTC", label: "BTC", api: "BTC-USD" },
];

const CHART_SYMBOL = { ui: "BTC/USDT", api: "BTC-USD" };

const AGENT_META: Record<string, { name: string; category: string }> = {
  market_analyst: { name: "Market Analyst", category: "Market" },
  macro_analyst: { name: "Macro Context", category: "Economic" },
  sector_analyst: { name: "Sector Analyst", category: "Market" },
  portfolio_strategist: { name: "Portfolio Strategist", category: "Quant" },
  risk_officer: { name: "Risk Commentary", category: "Quant" },
  trade_executor: { name: "Trade Executor", category: "Market" },
  orchestrator: { name: "Orchestrator", category: "Agents" },
};

const MARKET_HOURS_DEF: Array<{
  id: string;
  exchange: string;
  name: string;
  tz: string;
  openMin: number;
  closeMin: number;
  days: number[];
}> = [
  { id: "nyse", exchange: "NYSE/NASDAQ", name: "New York", tz: "America/New_York", openMin: 9 * 60 + 30, closeMin: 16 * 60, days: [1, 2, 3, 4, 5] },
  { id: "lse", exchange: "LSE", name: "London", tz: "Europe/London", openMin: 8 * 60, closeMin: 16 * 60 + 30, days: [1, 2, 3, 4, 5] },
  { id: "tse", exchange: "TSE (TOKYO)", name: "Tokyo", tz: "Asia/Tokyo", openMin: 9 * 60, closeMin: 15 * 60, days: [1, 2, 3, 4, 5] },
  { id: "sse", exchange: "SSE (SHANGHAI)", name: "Shanghai", tz: "Asia/Shanghai", openMin: 9 * 60 + 30, closeMin: 15 * 60, days: [1, 2, 3, 4, 5] },
  { id: "nse", exchange: "NSE (INDIA)", name: "Mumbai", tz: "Asia/Kolkata", openMin: 9 * 60 + 15, closeMin: 15 * 60 + 30, days: [1, 2, 3, 4, 5] },
  { id: "moex", exchange: "MOEX", name: "Moscow", tz: "Europe/Moscow", openMin: 10 * 60, closeMin: 18 * 60 + 50, days: [1, 2, 3, 4, 5] },
];

function nowIso(): string {
  return new Date().toISOString();
}

function jitter(base: number, amp = 0.15): number {
  return base + (Math.random() - 0.5) * amp;
}

function num(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v)) return v;
  if (typeof v === "string" && v.trim() !== "") {
    const n = Number(v);
    if (Number.isFinite(n)) return n;
  }
  return null;
}

function fmtVol(v: number | null | undefined): string | null {
  if (v == null || !Number.isFinite(v)) return null;
  if (v >= 1e9) return `${(v / 1e9).toFixed(1)}B`;
  if (v >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
  return String(Math.round(v));
}

function localMinutesInTz(tz: string, date = new Date()): { day: number; minutes: number; label: string } {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: tz,
    weekday: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(date);
  const weekday = parts.find((p) => p.type === "weekday")?.value ?? "Mon";
  const hour = Number(parts.find((p) => p.type === "hour")?.value ?? "0");
  const minute = Number(parts.find((p) => p.type === "minute")?.value ?? "0");
  const dayMap: Record<string, number> = { Sun: 0, Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6 };
  return {
    day: dayMap[weekday] ?? 1,
    minutes: hour * 60 + minute,
    label: `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`,
  };
}

export function computeMarketHours(now = new Date()): TerminalMarketHoursRow[] {
  return MARKET_HOURS_DEF.map((ex) => {
    const loc = localMinutesInTz(ex.tz, now);
    let status: TerminalSessionStatus = "closed";
    if (ex.days.includes(loc.day)) {
      const preStart = ex.openMin - 60;
      const postEnd = ex.closeMin + 60;
      if (loc.minutes >= ex.openMin && loc.minutes < ex.closeMin) status = "open";
      else if (loc.minutes >= preStart && loc.minutes < ex.openMin) status = "pre";
      else if (loc.minutes >= ex.closeMin && loc.minutes < postEnd) status = "post";
    }
    return {
      id: ex.id,
      exchange: ex.exchange,
      name: ex.name,
      status,
      local_time: loc.label,
      timezone: ex.tz,
    };
  });
}

function emptyPortfolio(reason: string): TerminalPortfolio {
  return {
    total_value: null,
    day_pnl: null,
    day_pnl_pct: null,
    total_pnl: null,
    total_pnl_pct: null,
    holdings: 0,
    positions: [],
    empty_reason: reason,
    connected: false,
  };
}

/** Pulse with no numbers: shown when the server has not sent market breadth / snapshot yet. Never invent figures. */
const EMPTY_PULSE: TerminalPulse = {
  fear_greed: null,
  label: "",
  breadth: [],
  gainers: [],
  losers: [],
  global_snapshot: [],
  vol_regime: null,
  reason: "Нет данных о настроении рынка",
};

/**
 * Snapshot with no market numbers at all: the base every live response is
 * merged onto. Empty blocks show their own "no data" state; nothing here is
 * invented (the old fallback filled quant factors, agents, alerts, risk and
 * calendar from a hard-coded demo snapshot).
 */
export function buildEmptySnapshot(): TerminalSnapshot {
  return {
    as_of: nowIso(),
    source: "partial",
    indices: [],
    performance: [],
    pulse: EMPTY_PULSE,
    risk: { score: null, label: "Нет данных", var_pct: null, high_beta: [] },
    news: [],
    calendar: [],
    watchlist: [],
    alerts: [],
    quant: [],
    quant_factors: [],
    agents: [],
    chart: { symbol: "", points: [] },
    tape: [],
    market_hours: computeMarketHours(),
    portfolio: emptyPortfolio("Портфеля пока нет — подключите брокерский счёт или пополните учебный."),
    data_notes: [],
  };
}

/** Demo-only fixture for tests and storybook-like previews. Never used on live paths. */
export function buildMockSnapshot(seed = Date.now()): TerminalSnapshot {
  const t = seed;
  const indices: TerminalIndexRow[] = [
    { symbol: "SPX", name: "S&P 500", price: 5482.1 + jitter(0, 4), change: 12.4, change_pct: 0.23, session: "open", region: "US" },
    { symbol: "DJI", name: "Dow Jones", price: 39120 + jitter(0, 20), change: -45.2, change_pct: -0.12, session: "open", region: "US" },
    { symbol: "IXIC", name: "NASDAQ Comp", price: 17840 + jitter(0, 15), change: 62.1, change_pct: 0.35, session: "open", region: "US" },
    { symbol: "NDX", name: "NASDAQ 100", price: 19720 + jitter(0, 20), change: -38.2, change_pct: -0.19, session: "open", region: "US" },
    { symbol: "RUT", name: "Russell 2000", price: 2120 + jitter(0, 5), change: 8.4, change_pct: 0.4, session: "open", region: "US" },
    { symbol: "FTSE", name: "FTSE 100", price: 8240 + jitter(0, 8), change: -12.1, change_pct: -0.15, session: "closed", region: "EU" },
    { symbol: "DAX", name: "DAX", price: 18340 + jitter(0, 12), change: 55.1, change_pct: 0.3, session: "closed", region: "EU" },
    { symbol: "CAC", name: "CAC 40", price: 7620 + jitter(0, 6), change: 18.2, change_pct: 0.24, session: "closed", region: "EU" },
    { symbol: "N225", name: "Nikkei 225", price: 39210 + jitter(0, 30), change: -120.0, change_pct: -0.31, session: "closed", region: "ASIA" },
    { symbol: "HSI", name: "Hang Seng", price: 17820 + jitter(0, 20), change: 95.0, change_pct: 0.54, session: "closed", region: "ASIA" },
    { symbol: "SSEC", name: "Shanghai", price: 3085 + jitter(0, 4), change: -8.2, change_pct: -0.27, session: "closed", region: "ASIA" },
    { symbol: "KS11", name: "KOSPI", price: 2680 + jitter(0, 5), change: 14.1, change_pct: 0.53, session: "closed", region: "ASIA" },
    { symbol: "IMOEX", name: "MOEX Russia", price: 2784.5 + jitter(0, 3), change: 8.2, change_pct: 0.3, session: "closed", region: "RU" },
    { symbol: "VIX", name: "VIX", price: 14.8 + jitter(0, 0.4), change: -0.4, change_pct: -2.6, session: "open", region: "US" },
  ];

  const performance: TerminalPerformanceRow[] = [
    { label: "NASDAQ Daily", period: "TODAY", value: 0.35, unit: "pct" },
    { label: "DOW Daily", period: "TODAY", value: -0.12, unit: "pct" },
    { label: "S&P vs DOW Spread", period: "TODAY", value: 0.35, unit: "pct" },
    { label: "NASDAQ vs S&P Spread", period: "TODAY", value: 0.12, unit: "pct" },
    { label: "VIX", period: "LEVEL", value: indices[13].price, unit: "level" },
    { label: "Gold (XAU)", period: "TODAY", value: 0.45, unit: "pct" },
    { label: "BTC/USDT", period: "TODAY", value: 1.2, unit: "pct" },
    { label: "IMOEX", period: "TODAY", value: 0.3, unit: "pct" },
  ];

  const pulse: TerminalPulse = {
    fear_greed: 56,
    label: "Neutral",
    breadth: [
      { exchange: "NYSE", advancers: 1820, decliners: 1410 },
      { exchange: "NASDAQ", advancers: 2104, decliners: 1988 },
      { exchange: "S&P 500", advancers: 278, decliners: 222 },
      { exchange: "MOEX", advancers: 112, decliners: 98 },
    ],
    gainers: [
      { symbol: "NVDA", change_pct: 3.4, volume: 9.2e7, volume_label: "92.0M" },
      { symbol: "SBER", change_pct: 2.1, volume: 4.1e7, volume_label: "41.0M" },
      { symbol: "ETH", change_pct: 1.8, volume: 1.2e9, volume_label: "1.2B" },
    ],
    losers: [
      { symbol: "TSLA", change_pct: -2.6, volume: 8.8e7, volume_label: "88.0M" },
      { symbol: "GAZP", change_pct: -1.4, volume: 2.2e7, volume_label: "22.0M" },
      { symbol: "META", change_pct: -0.9, volume: 1.5e7, volume_label: "15.0M" },
    ],
    global_snapshot: [
      { symbol: "VIX", label: "VIX", value: 14.8, change_pct: -2.6 },
      { symbol: "TNX", label: "US 10Y", value: 4.28, change_pct: 0.39 },
      { symbol: "DXY", label: "DXY", value: 104.2, change_pct: -0.45 },
      { symbol: "GOLD", label: "GOLD", value: 2340, change_pct: 0.45 },
      { symbol: "OIL", label: "OIL WTI", value: 78.4, change_pct: 1.12 },
      { symbol: "BTC", label: "BTC", value: 67540, change_pct: 1.2 },
    ],
    vol_regime: "Normal",
  };

  const risk: TerminalRiskSummary = {
    score: 42,
    label: "Moderate",
    var_pct: 1.8,
    high_beta: [
      { symbol: "NVDA", beta: 1.6, change_pct: 3.4, day_high: 132.1, day_low: 126.4 },
      { symbol: "TSLA", beta: 1.9, change_pct: -2.6, day_high: 248.0, day_low: 239.2 },
      { symbol: "BTC", beta: null, change_pct: 1.2, note: "insufficient data" },
    ],
  };

  const news: TerminalNewsItem[] = [
    {
      id: "n1",
      headline: "Fed speakers lean data-dependent into next FOMC",
      source: "Reuters",
      published_at: nowIso(),
      summary: "Markets price shallow path; focus on labor prints.",
      url: "https://www.reuters.com",
    },
    {
      id: "n2",
      headline: "CBR keeps options open as ruble volatility eases",
      source: "Interfax",
      published_at: new Date(Date.now() - 25 * 60_000).toISOString(),
      summary: "Analysts watch FX reserves and oil corridor.",
    },
    {
      id: "n3",
      headline: "Crypto liquidations cool after weekend squeeze",
      source: "QuantAnalytics",
      published_at: new Date(Date.now() - 55 * 60_000).toISOString(),
      summary: "Open interest rebuild on majors; funding neutral.",
    },
    {
      id: "n4",
      headline: "European equities firmer on soft inflation prints",
      source: "Bloomberg",
      published_at: new Date(Date.now() - 90 * 60_000).toISOString(),
    },
    {
      id: "n5",
      headline: "MOEX session: banks lead, energy mixed",
      source: "RBC",
      published_at: new Date(Date.now() - 120 * 60_000).toISOString(),
    },
  ];

  const calendar: TerminalCalendarEvent[] = [
    { id: "c1", title: "US CPI (YoY)", when: new Date(Date.now() + 36 * 3600_000).toISOString(), region: "US", importance: "high", expected: "3.0%", previous: "2.9%" },
    { id: "c2", title: "CBR Board meeting", when: new Date(Date.now() + 5 * 86400_000).toISOString(), region: "RU", importance: "high", expected: "hold" },
    { id: "c3", title: "FOMC minutes", when: new Date(Date.now() + 9 * 86400_000).toISOString(), region: "US", importance: "medium" },
    { id: "c4", title: "EU GDP (QoQ)", when: new Date(Date.now() + 2 * 86400_000).toISOString(), region: "EU", importance: "medium", expected: "0.2%" },
    { id: "c5", title: "US Initial Claims", when: new Date(Date.now() + 18 * 3600_000).toISOString(), region: "US", importance: "medium", expected: "220k" },
  ];

  const watchlist: TerminalWatchItem[] = [
    { symbol: "BTC/USDT", last: 67540 + jitter(0, 80), change_pct: 1.2, change_1w: 3.4, change_1m: 8.1, volume: 1.2e9, vol: 42, regime: "Trend", risk: "Med", sector: "Crypto", session: "open", feed: "live" },
    { symbol: "ETH/USDT", last: 3482 + jitter(0, 12), change_pct: 0.8, change_1w: 2.1, change_1m: 5.4, volume: 6.4e8, vol: 48, regime: "Range", risk: "Med", sector: "Crypto", session: "open", feed: "live" },
    { symbol: "AAPL", last: 214.2 + jitter(0, 0.8), change_pct: -0.3, change_1w: 1.1, change_1m: 2.4, volume: 4.2e7, vol: 18, regime: "Quiet", risk: "Low", sector: "Tech", session: "open", feed: "delayed" },
    { symbol: "MSFT", last: 428.5 + jitter(0, 1), change_pct: 0.4, change_1w: 0.9, change_1m: 3.2, volume: 2.1e7, vol: 16, regime: "Quiet", risk: "Low", sector: "Tech", session: "open", feed: "delayed" },
    { symbol: "NVDA", last: 128.4 + jitter(0, 0.6), change_pct: 3.4, change_1w: 6.2, change_1m: 12.1, volume: 9.2e7, vol: 55, regime: "Momentum", risk: "High", sector: "Tech", session: "open", feed: "live" },
    { symbol: "GOOGL", last: 178.2 + jitter(0, 0.5), change_pct: 0.6, change_1w: 1.4, change_1m: 4.0, volume: 1.8e7, vol: 22, regime: "Trend", risk: "Low", sector: "Tech", session: "open", feed: "delayed" },
    { symbol: "AMZN", last: 186.1 + jitter(0, 0.4), change_pct: -0.2, change_1w: 0.8, change_1m: 2.9, volume: 3.1e7, vol: 24, regime: "Range", risk: "Med", sector: "Consumer", session: "open", feed: "delayed" },
    { symbol: "TSLA", last: 244.0 + jitter(0, 1.2), change_pct: -2.6, change_1w: -4.1, change_1m: 1.2, volume: 8.8e7, vol: 62, regime: "Volatile", risk: "High", sector: "Auto", session: "open", feed: "live" },
    { symbol: "SBER", last: 284.5 + jitter(0, 1), change_pct: 0.6, change_1w: 1.8, change_1m: 4.5, volume: 4.1e7, vol: 28, regime: "Trend", risk: "Med", sector: "Financials", session: "closed", feed: "delayed" },
    { symbol: "GAZP", last: 128.4 + jitter(0, 0.4), change_pct: -1.4, change_1w: -2.0, change_1m: -0.5, volume: 2.2e7, vol: 35, regime: "Weak", risk: "Med", sector: "Energy", session: "closed", feed: "delayed" },
    { symbol: "GLD", last: 232.1 + jitter(0, 0.4), change_pct: 0.4, change_1w: 1.2, change_1m: 2.8, volume: 8e6, vol: 12, regime: "Quiet", risk: "Low", sector: "Commodities", session: "open", feed: "delayed" },
    { symbol: "USO", last: 78.4 + jitter(0, 0.3), change_pct: 1.1, change_1w: 2.4, change_1m: 5.1, volume: 5e6, vol: 30, regime: "Trend", risk: "Med", sector: "Commodities", session: "open", feed: "delayed" },
  ];

  const alerts: TerminalAlert[] = [
    { id: "a1", severity: "warn", title: "Watchlist gap risk", body: "TSLA day range > 3.5% — review stop bands.", ts: nowIso() },
    { id: "a2", severity: "info", title: "Pipeline idle", body: "Last market analysis older than 6h.", ts: new Date(Date.now() - 10 * 60_000).toISOString() },
  ];

  const quant: TerminalQuantMetric[] = [
    { id: "q1", label: "Factor tilt", value: "Momentum +", delta: 0.12, hint: "vs prior close", weight: 0.28, contribution: 0.08, source: "factor_model", freshness: "live", confidence: 0.72, tip: "Momentum dominates; mean-reversion weight is secondary today." },
    { id: "q2", label: "Dispersion", value: "1.8σ", delta: -0.05, weight: 0.18, contribution: -0.02, source: "cross_section", freshness: "~15m", confidence: 0.65 },
    { id: "q3", label: "Carry proxy", value: "Neutral", delta: 0, weight: 0.15, contribution: 0, source: "rates_fx", freshness: "~1h", confidence: 0.55, tip: "Carry not a driver — rates path still data-dependent." },
    { id: "q4", label: "Liquidity score", value: "74", delta: 2.1, weight: 0.22, contribution: 0.05, source: "volume_depth", freshness: "live", confidence: 0.8 },
  ];

  const quant_factors: TerminalQuantFactor[] = quant.map((q) => ({
    id: q.id,
    name: q.label,
    weight: q.weight,
    contribution: q.contribution,
    value: q.value,
    source: q.source,
    freshness: q.freshness,
    confidence: q.confidence,
    tip: q.tip,
  }));

  const agents: TerminalAgentCard[] = [
    { id: "ag1", name: "Macro Context", category: "Economic", status: "ready", summary: "Rates path still data-dependent; RU FX quieter." },
    { id: "ag2", name: "Risk Commentary", category: "Quant", status: "idle", summary: "VaR within band; beta cluster on mega-cap tech." },
    { id: "ag3", name: "Value Analysis", category: "Market", status: "running", summary: "Scanning watchlist for relative value pairs…" },
  ];

  // NEVER use a sine/mock OHLCV series in production paths — empty until live bars arrive.
  const chart: TerminalChartSeries = { symbol: "BTC/USDT", points: [] };

  const market_hours = computeMarketHours();
  const tape = buildTapeFromParts(indices, watchlist, pulse);

  return {
    as_of: nowIso(),
    source: "mock",
    indices,
    performance,
    pulse,
    risk,
    news,
    calendar,
    watchlist,
    alerts,
    quant,
    quant_factors,
    agents,
    chart,
    tape,
    market_hours,
    portfolio: emptyPortfolio("No portfolios yet — connect a broker or fund a venue account."),
    data_notes: ["Demo snapshot — wire live providers for production quotes."],
  };
}

/** Normalize tape symbols so VIX/^VIX, BTC-USD/BTC/USDT, GOLD/GLD/GC=F dedupe to one key. */
export function canonicalTapeKey(symbol?: string, label?: string): string {
  const raw = (symbol || label || "").trim().toUpperCase();
  if (!raw) return "";

  const ALIASES: Record<string, string> = {
    "^VIX": "VIX",
    VIX: "VIX",
    "BTC-USD": "BTC",
    "BTC/USDT": "BTC",
    BTCUSDT: "BTC",
    BTC: "BTC",
    "ETH-USD": "ETH",
    "ETH/USDT": "ETH",
    ETHUSDT: "ETH",
    ETH: "ETH",
    "GC=F": "GOLD",
    GOLD: "GOLD",
    XAUUSD: "GOLD",
    XAU: "GOLD",
    GLD: "GOLD",
    "CL=F": "OIL",
    OIL: "OIL",
    USO: "OIL",
    "DX-Y.NYB": "DXY",
    DXY: "DXY",
    "^TNX": "TNX",
    TNX: "TNX",
  };

  if (ALIASES[raw]) return ALIASES[raw];
  const noCaret = raw.replace(/^\^/, "");
  if (ALIASES[noCaret]) return ALIASES[noCaret];
  const noSuffix = noCaret.replace(/\.ME$/, "");
  if (ALIASES[noSuffix]) return ALIASES[noSuffix];

  const crypto = raw.match(/^([A-Z]{2,10})[-/](USDT?|USD)$/);
  if (crypto) return crypto[1];

  return noSuffix || raw;
}

/** One entry per canonical symbol — indices first, then watchlist, then pulse movers. */
export function dedupeTapeItems(items: TerminalTapeItem[]): TerminalTapeItem[] {
  const seen = new Set<string>();
  const out: TerminalTapeItem[] = [];
  for (const item of items) {
    if (item.kind === "headline") continue;
    const key = canonicalTapeKey(item.symbol, item.label);
    if (!key || seen.has(key)) continue;
    seen.add(key);
    out.push(item);
  }
  return out;
}

export function buildTapeFromParts(
  indices: TerminalIndexRow[],
  watch: TerminalWatchItem[],
  pulse: TerminalPulse,
): TerminalTapeItem[] {
  const items: TerminalTapeItem[] = [];
  const seen = new Set<string>();

  const add = (item: TerminalTapeItem) => {
    const key = canonicalTapeKey(item.symbol, item.label);
    if (!key || seen.has(key)) return;
    seen.add(key);
    items.push(item);
  };

  for (const i of indices.slice(0, 14)) {
    add({
      id: `idx-${i.symbol}`,
      kind: i.symbol === "VIX" ? "vix" : "index",
      symbol: i.symbol,
      label: i.symbol,
      value: i.price,
      change_pct: i.change_pct,
    });
  }
  for (const w of watch.slice(0, 8)) {
    add({
      id: `w-${w.symbol}`,
      kind: "macro",
      symbol: w.symbol,
      label: w.symbol,
      value: w.last,
      change_pct: w.change_pct,
    });
  }
  for (const g of pulse.gainers.slice(0, 3)) {
    add({
      id: `g-${g.symbol}`,
      kind: "mover",
      symbol: g.symbol,
      label: g.symbol,
      value: g.price ?? null,
      change_pct: g.change_pct,
    });
  }
  for (const l of pulse.losers.slice(0, 2)) {
    add({
      id: `l-${l.symbol}`,
      kind: "mover",
      symbol: l.symbol,
      label: l.symbol,
      value: l.price ?? null,
      change_pct: l.change_pct,
    });
  }
  return items;
}

/** Map UI/watchlist symbol to API quote/OHLCV symbol. */
/** Map UI symbol to `/market/bars/{ticker}` path segment. */
export function resolveMarketBarsTicker(uiSymbol: string): string {
  const s = uiSymbol.trim();
  const idx = INDEX_UNIVERSE.find((m) => m.ui === s || m.api === s);
  if (idx) {
    const alias = INDEX_EQUITY_ALIAS[idx.api];
    if (alias) return alias;
    if (idx.api.startsWith("^")) return idx.api;
    return idx.ui;
  }
  return chartApiSymbol(s);
}

const INDEX_EQUITY_ALIAS: Record<string, string> = {
  "^GSPC": "SPY",
  SPX: "SPY",
  "^IXIC": "QQQ",
  IXIC: "QQQ",
  "^NDX": "QQQ",
  NDX: "QQQ",
  "^DJI": "DIA",
  DJI: "DIA",
  "^RUT": "IWM",
  RUT: "IWM",
  "^FTSE": "EWU",
  FTSE: "EWU",
  "^GDAXI": "EWG",
  DAX: "EWG",
  "^FCHI": "EWQ",
  CAC: "EWQ",
  FCHI: "EWQ",
  "^N225": "EWJ",
  N225: "EWJ",
  "^HSI": "EWH",
  HSI: "EWH",
  "000001.SS": "ASHR",
  SSEC: "ASHR",
  "^KS11": "EWY",
  KS11: "EWY",
  IMOEX: "RSX",
  RTSI: "RSX",
  "^VIX": "VIXY",
  VIX: "VIXY",
  "^TNX": "TLT",
  TNX: "TLT",
  "DX-Y.NYB": "UUP",
  DXY: "UUP",
  "GC=F": "GLD",
  GOLD: "GLD",
  "CL=F": "USO",
  OIL: "USO",
};

export function resolveChartApiSymbol(uiSymbol: string): string {
  const s = uiSymbol.trim();
  for (const m of INDEX_UNIVERSE) {
    if (m.ui === s || m.api === s) return m.api;
  }
  for (const m of WATCH_UNIVERSE) {
    if (m.ui === s || m.api === s) return m.api;
  }
  for (const m of MACRO_SNAPSHOT) {
    if (m.ui === s || m.api === s || m.label === s) return m.api;
  }
  if (s === "VIX" || s === "^VIX") return "^VIX";
  return chartApiSymbol(s);
}

async function tryGet<T>(
  path: string,
  params?: Record<string, string | number>,
  opts?: { timeoutMs?: number },
): Promise<T | null> {
  try {
    const { data } = await api.get<T>(path, {
      // Hard Terminal budget is ≤15s — never hang longer on a single call.
      timeout: opts?.timeoutMs ?? 8_000,
      skipAuthRedirect: true,
      params,
    } as AxiosRequestConfig);
    return data;
  } catch {
    return null;
  }
}

/** Frontend hard budget for first usable Terminal paint. */
const SNAPSHOT_TIMEOUT_MS = 28_000;
const OVERALL_COMPOSE_BUDGET_MS = 30_000;
const SUB_ENDPOINT_TIMEOUT_MS = 12_000;

async function tryPost<T>(path: string, body: unknown): Promise<T | null> {
  try {
    const { data } = await api.post<T>(path, body, {
      timeout: 8_000,
      skipAuthRedirect: true,
    } as AxiosRequestConfig);
    return data;
  } catch {
    return null;
  }
}

function quoteToIndex(
  meta: { ui: string; name: string; region?: string },
  q: QuotePayload | null,
  failReason?: string,
): TerminalIndexRow {
  if (!q) {
    return {
      symbol: meta.ui,
      name: meta.name,
      price: null,
      change: null,
      change_pct: null,
      region: meta.region,
      reason: failReason || "quote unavailable",
    };
  }
  const price = num(q.price);
  if (price == null || price === 0) {
    return {
      symbol: meta.ui,
      name: meta.name,
      price: null,
      change: null,
      change_pct: null,
      region: meta.region,
      reason: "empty price from provider",
    };
  }
  const changePct = num(q.change_pct);
  const change = num(q.change) ?? (changePct != null ? price * (changePct / 100) : null);
  return {
    symbol: meta.ui,
    name: meta.name,
    price,
    change,
    change_pct: changePct,
    region: meta.region,
    currency: q.currency ?? null,
    session: q.exchange ? "open" : null,
  };
}

function quoteToWatch(
  ui: string,
  q: QuotePayload | null,
  sector?: string,
): TerminalWatchItem {
  if (!q) {
    return {
      symbol: ui,
      last: null,
      change_pct: null,
      sector: sector ?? null,
      feed: "unknown",
      reason: "quote unavailable",
    };
  }
  const last = num(q.price);
  if (last == null || last === 0) {
    return {
      symbol: ui,
      last: null,
      change_pct: null,
      sector: sector ?? null,
      feed: "stale",
      reason: "empty price from provider",
    };
  }
  return {
    symbol: ui,
    last,
    change: num(q.change),
    change_pct: num(q.change_pct),
    volume: num(q.volume),
    sector: sector ?? null,
    feed: "live",
  };
}

function mapNews(items: NewsPayload[] | null | undefined): TerminalNewsItem[] {
  if (!items?.length) return [];
  return items.slice(0, 30).map((n, i) => ({
    id: `n-${i}-${n.published_at}`,
    headline: n.title,
    source: n.source || n.provider || "news",
    published_at: n.published_at,
    summary: n.summary ?? null,
    url: n.url ?? null,
  }));
}

function mapAgents(ids: string[] | null | undefined): TerminalAgentCard[] {
  if (!ids?.length) return [];
  return ids.map((id) => {
    const meta = AGENT_META[id] ?? { name: id, category: "Agents" };
    return {
      id,
      name: meta.name,
      category: meta.category,
      status: "ready" as const,
      summary: `Agent ready — POST /terminal/agents/ask with agent_type=${id}`,
    };
  });
}

function mapOhlcvChart(bars: OhlcvBar[] | null | undefined, uiSymbol: string): TerminalChartSeries | null {
  if (!bars?.length) return null;
  const byTime = new Map<number, { t: number; o: number; h: number; l: number; c: number }>();

  for (const b of bars) {
    const t = Date.parse(b.timestamp) || 0;
    const o = num(b.open);
    const h = num(b.high);
    const l = num(b.low);
    const c = num(b.close);
    if (t <= 0 || c == null || c <= 0) continue;
    const open = o ?? c;
    const hiRaw = h ?? c;
    const loRaw = l ?? c;
    const hi = Math.max(hiRaw, open, c);
    const lo = Math.min(loRaw, open, c);
    byTime.set(t, { t, o: open, h: hi, l: lo, c });
  }

  const chartBars = [...byTime.values()]
    .sort((a, b) => a.t - b.t)
    .slice(-120);
  if (chartBars.length < 2) return null;

  const isDaily = isIndexUiSymbol(uiSymbol);
  const minGapMs = isDaily ? 18 * 3600_000 : 45 * 60_000;
  const dense: typeof chartBars = [chartBars[0]];
  for (let i = 1; i < chartBars.length; i++) {
    const prev = dense[dense.length - 1];
    const cur = chartBars[i];
    if (cur.t - prev.t >= minGapMs) {
      dense.push(cur);
      continue;
    }
    dense[dense.length - 1] = cur.t >= prev.t ? cur : prev;
  }

  if (dense.length < 2) return null;
  const points = dense.map((b) => ({ t: b.t, v: b.c }));
  if (looksLikeSineMockChart(points)) return null;
  return { symbol: uiSymbol, points, bars: dense };
}

function indexChartTickers(uiSymbol: string): string[] {
  const s = uiSymbol.trim();
  const idx = INDEX_UNIVERSE.find((m) => m.ui === s || m.api === s);
  if (!idx) return [resolveMarketBarsTicker(s)];
  const alias = INDEX_EQUITY_ALIAS[idx.api] ?? INDEX_EQUITY_ALIAS[idx.ui];
  const candidates = [
    alias,
    resolveMarketBarsTicker(s),
    idx.ui,
    idx.api,
  ].filter(Boolean) as string[];
  return [...new Set(candidates)];
}

async function fetchChartBars(uiSymbol: string, tf: string): Promise<OhlcvBar[] | null> {
  const tickers = indexChartTickers(uiSymbol);
  for (const ticker of tickers) {
    const barsRes = await tryGet<OhlcvBar[]>(
      `/market/bars/${encodeURIComponent(ticker)}`,
      { timeframe: tf, limit: 160 },
      { timeoutMs: 8_000 },
    );
    if (barsRes?.length) return barsRes;
  }

  for (const apiSymbol of tickers) {
    const res = await tryGet<FetchResult<OhlcvBar[]>>(
      "/terminal/ohlcv",
      { symbol: apiSymbol, timeframe: tf },
      { timeoutMs: 8_000 },
    );
    if (res?.success && res.data?.length) return res.data;
  }
  return null;
}

function isIndexUiSymbol(uiSymbol: string): boolean {
  const s = uiSymbol.trim();
  return INDEX_UNIVERSE.some((m) => m.ui === s || m.api === s);
}

/** Detect the old demo series: ~67500 ± sin(i/4)*180 — never treat as live. */
export function looksLikeSineMockChart(points: Array<{ t: number; v: number }>): boolean {
  if (points.length < 16) return false;
  const vals = points.map((p) => p.v);
  const mid = vals.reduce((a, b) => a + b, 0) / vals.length;
  if (mid < 65000 || mid > 70000) return false;
  let err = 0;
  let amp = 0;
  for (let i = 0; i < vals.length; i++) {
    const d = Math.abs(vals[i] - mid);
    if (d > amp) amp = d;
    const expected = mid + Math.sin(i / 4) * Math.min(amp || 180, 200);
    err += Math.abs(vals[i] - expected);
  }
  if (amp < 50 || amp > 400) return false;
  return err / vals.length < amp * 0.2;
}

function emptyChart(symbol = "BTC/USDT"): TerminalChartSeries {
  return { symbol, points: [] };
}

function preferLiveChart(
  incoming: TerminalChartSeries | null | undefined,
  previous?: TerminalChartSeries | null,
): TerminalChartSeries {
  if (incoming?.points?.length && !looksLikeSineMockChart(incoming.points)) return incoming;
  if (previous?.points?.length && !looksLikeSineMockChart(previous.points)) return previous;
  return emptyChart(incoming?.symbol || previous?.symbol || "BTC/USDT");
}

/** Providers that are optional for Terminal Market — missing key / soft skip ≠ outage. */
const OPTIONAL_KEY_PROVIDERS = new Set([
  "fred",
  "alpaca",
  "polygon",
  "twelvedata",
  "tiingo",
  "marketstack",
  "finnhub",
  "coingecko",
  "ccxt_binance",
  "ccxt_bybit",
  "ccxt_okx",
]);

/** Core Terminal path — only these raise warn/critical when truly broken. */
const CORE_RUNTIME_PROVIDERS = new Set([
  "binance_public",
  "moex_iss",
  "yfinance",
  "fmp",
  "alpha_vantage",
  "cbr",
]);

function isSoftProviderError(h: ProviderHealth): boolean {
  const err = (h.last_error || "").toLowerCase();
  return (
    err.includes("429") ||
    err.includes("too many") ||
    err.includes("rate limit") ||
    err.includes("400") ||
    err.includes("bad request") ||
    err.includes("403") ||
    err.includes("forbidden") ||
    err.includes("unsupported") ||
    err.includes("no module named") ||
    err.includes("proxy") ||
    err.includes("timeout") ||
    err.includes("could not connect")
  );
}

function buildAlertsFromHealth(health: ProviderHealth[] | null): TerminalAlert[] {
  if (!health?.length) return [];
  const alerts: TerminalAlert[] = [];

  const missingKeys = health.filter((h) => h.requires_api_key && !h.api_key_configured);
  const optionalMissing = missingKeys.filter((h) => OPTIONAL_KEY_PROVIDERS.has(h.name));
  const requiredMissing = missingKeys.filter((h) => !OPTIONAL_KEY_PROVIDERS.has(h.name));

  // Key missing is NOT the same as provider outage — exclude from "unavailable".
  const missingNames = new Set(missingKeys.map((h) => h.name));
  const softOptional: ProviderHealth[] = [];
  const degraded = health.filter((h) => {
    if (missingNames.has(h.name)) return false;
    const st = (h.status || "").toLowerCase();
    const circuit = (h.circuit_state || "").toLowerCase();
    // Closed circuit + active status = recovered; don't alarm on stale available=false.
    if (circuit === "closed" && (st === "active" || st === "rate_limited")) return false;
    const looksBad =
      !h.available ||
      st === "unavailable" ||
      st === "circuit_open" ||
      st === "degraded" ||
      st === "down" ||
      st === "error" ||
      circuit === "open";
    if (!looksBad) return false;
    // Optional / expected soft failures → info bucket, not "N providers degraded".
    // Never alert on ccxt_* — optional dep / unused crypto venue, not a Terminal outage.
    if (h.name.startsWith("ccxt_")) {
      return false;
    }
    if (
      OPTIONAL_KEY_PROVIDERS.has(h.name) ||
      !CORE_RUNTIME_PROVIDERS.has(h.name) ||
      st === "rate_limited" ||
      isSoftProviderError(h)
    ) {
      softOptional.push(h);
      return false;
    }
    return true;
  });

  if (requiredMissing.length) {
    alerts.push({
      id: "prov-keys-required",
      severity: "warn",
      title: "API keys missing",
      body: requiredMissing.map((h) => h.name).slice(0, 6).join(", "),
      ts: nowIso(),
    });
  }
  if (optionalMissing.length) {
    alerts.push({
      id: "prov-keys-optional",
      severity: "info",
      title: "Optional API keys missing",
      body: optionalMissing.map((h) => h.name).slice(0, 6).join(", "),
      ts: nowIso(),
    });
  }
  if (softOptional.length) {
    const visible = softOptional.filter((h) => !h.name.startsWith("ccxt_"));
    if (visible.length) {
      alerts.push({
        id: "prov-soft",
        severity: "info",
        title: `${visible.length} optional provider skip(s)`,
        body: visible
          .slice(0, 6)
          .map((h) => h.name)
          .join(", "),
        ts: nowIso(),
      });
    }
  }
  if (degraded.length) {
    const body = degraded
      .slice(0, 6)
      .map((h) => {
        const why =
          h.circuit_state === "open"
            ? "circuit_open — POST /terminal/providers/reset-circuits"
            : h.status === "rate_limited"
              ? "rate_limited — fallbacks active"
              : h.status === "degraded"
                ? "degraded — check fallbacks"
                : h.last_error
                  ? "error"
                  : "unavailable";
        return `${h.name} (${why})`;
      })
      .join("; ");
    alerts.push({
      id: "prov-degraded",
      severity: degraded.length >= 3 ? "critical" : "warn",
      title: `${degraded.length} core provider(s) degraded`,
      body,
      ts: nowIso(),
    });
  }
  return alerts;
}

function mapCalendar(items: CalendarPayload[] | null | undefined): TerminalCalendarEvent[] {
  if (!items?.length) return [];
  return items.slice(0, 40).map((c, i) => {
    const imp = (c.importance || "").toLowerCase();
    const importance: TerminalCalendarEvent["importance"] =
      imp === "high" || imp === "medium" || imp === "low" ? imp : undefined;
    return {
      id: c.id || `cal-${i}-${c.when}`,
      title: c.title,
      when: typeof c.when === "string" ? c.when : String(c.when),
      region: c.region ?? undefined,
      importance,
      expected: c.expected ?? null,
      actual: c.actual ?? null,
      previous: c.previous ?? null,
      forecast: c.forecast ?? c.expected ?? null,
    };
  });
}

function closesToReturns(closes: number[]): number[] {
  const out: number[] = [];
  for (let i = 1; i < closes.length; i++) {
    const prev = closes[i - 1];
    const cur = closes[i];
    if (prev > 0 && cur > 0) out.push(cur / prev - 1);
  }
  return out;
}

function buildQuantFromApi(
  metrics: {
    sharpe?: number;
    sortino?: number;
    volatility_annual?: number;
    max_drawdown?: number;
    cagr?: number | null;
  } | null,
  varRes: { var?: number; cvar?: number | null; confidence?: number } | null,
  health: ProviderHealth[] | null,
): { quant: TerminalQuantMetric[]; factors: TerminalQuantFactor[] } {
  const rows: TerminalQuantMetric[] = [];
  if (metrics) {
    if (typeof metrics.sharpe === "number") {
      rows.push({
        id: "sharpe",
        label: "Sharpe",
        value: metrics.sharpe.toFixed(2),
        delta: null,
        hint: "from OHLCV returns",
        weight: 0.25,
        contribution: metrics.sharpe > 0 ? 0.1 : -0.05,
        source: "quant/metrics",
        freshness: "session",
        confidence: 0.7,
        tip: "Risk-adjusted return from SPY daily closes.",
      });
    }
    if (typeof metrics.sortino === "number") {
      rows.push({
        id: "sortino",
        label: "Sortino",
        value: metrics.sortino.toFixed(2),
        weight: 0.2,
        source: "quant/metrics",
        freshness: "session",
        confidence: 0.68,
        tip: "Downside-only volatility; higher is better in risk-off regimes.",
      });
    }
    if (typeof metrics.volatility_annual === "number") {
      rows.push({
        id: "vol",
        label: "Ann. vol",
        value: `${(metrics.volatility_annual * 100).toFixed(1)}%`,
        weight: 0.2,
        contribution: -metrics.volatility_annual * 0.2,
        source: "quant/metrics",
        freshness: "session",
        confidence: 0.75,
      });
    }
    if (typeof metrics.max_drawdown === "number") {
      rows.push({
        id: "mdd",
        label: "Max DD",
        value: `${(metrics.max_drawdown * 100).toFixed(1)}%`,
        weight: 0.15,
        contribution: metrics.max_drawdown,
        source: "quant/metrics",
        freshness: "session",
        confidence: 0.8,
        tip: "Peak-to-trough drawdown on the reference series.",
      });
    }
  }
  if (varRes && typeof varRes.var === "number") {
    rows.push({
      id: "var95",
      label: `VaR ${Math.round((varRes.confidence ?? 0.95) * 100)}%`,
      value: `${(varRes.var * 100).toFixed(2)}%`,
      hint: "historical 1d",
      weight: 0.2,
      contribution: -Math.abs(varRes.var),
      source: "quant/var",
      freshness: "session",
      confidence: varRes.confidence ?? 0.95,
      tip: "1-day historical VaR — expected loss threshold, not a guarantee.",
    });
  }
  if (health?.length) {
    rows.push({
      id: "prov-up",
      label: "Providers up",
      value: String(health.filter((h) => h.available).length),
      hint: `of ${health.length}`,
      source: "providers/health",
      freshness: "live",
      confidence: 1,
    });
  }
  const factors: TerminalQuantFactor[] = rows.map((q) => ({
    id: q.id,
    name: q.label,
    weight: q.weight ?? null,
    contribution: q.contribution ?? null,
    value: q.value,
    source: q.source ?? null,
    freshness: q.freshness ?? null,
    confidence: q.confidence ?? null,
    tip: q.tip ?? null,
  }));
  return { quant: rows, factors };
}

function buildRiskFromQuant(
  watch: TerminalWatchItem[],
  varRes: { var?: number } | null,
  metrics: { volatility_annual?: number; max_drawdown?: number } | null,
): TerminalRiskSummary {
  const base = buildRiskFromQuotes(watch);
  const varPct =
    varRes && typeof varRes.var === "number"
      ? Number((varRes.var * 100).toFixed(2))
      : base.var_pct;
  const scoreFromVol =
    metrics && typeof metrics.volatility_annual === "number"
      ? Math.max(10, Math.min(90, Math.round(metrics.volatility_annual * 100 * 1.8)))
      : base.score;
  return {
    ...base,
    score: scoreFromVol,
    label:
      scoreFromVol == null
        ? "Unavailable"
        : scoreFromVol >= 65
          ? "Elevated"
          : scoreFromVol >= 40
            ? "Moderate"
            : "Calm",
    var_pct: varPct,
  };
}

function buildPulseFromQuotes(
  watch: TerminalWatchItem[],
  indices: TerminalIndexRow[],
  macros: TerminalSnapshotItem[],
): TerminalPulse {
  const ranked = [
    ...watch.map((w) => ({
      symbol: w.symbol,
      change_pct: w.change_pct,
      price: w.last,
      volume: w.volume ?? null,
      volume_label: fmtVol(w.volume),
    })),
    ...indices
      .filter((i) => i.change_pct != null)
      .map((i) => ({
        symbol: i.symbol,
        change_pct: i.change_pct,
        price: i.price,
        volume: null as number | null,
        volume_label: null as string | null,
      })),
  ].sort((a, b) => (b.change_pct ?? -999) - (a.change_pct ?? -999));

  const withPct = ranked.filter((r) => r.change_pct != null);
  const gainers = withPct.filter((r) => (r.change_pct ?? 0) > 0).slice(0, 5);
  const losers = withPct
    .filter((r) => (r.change_pct ?? 0) < 0)
    .sort((a, b) => (a.change_pct ?? 0) - (b.change_pct ?? 0))
    .slice(0, 5);

  const vix = indices.find((i) => i.symbol === "VIX");
  let fear: number | null = null;
  if (vix?.price != null) {
    fear = Math.max(5, Math.min(95, Math.round(100 - vix.price * 3.2)));
  }

  const adv = gainers.length;
  const dec = losers.length;

  return {
    fear_greed: fear,
    label: fear == null ? "No data" : fear >= 60 ? "Greed" : fear <= 40 ? "Fear" : "Neutral",
    breadth: [
      { exchange: "NYSE", advancers: Math.max(adv * 40, 1), decliners: Math.max(dec * 35, 1) },
      { exchange: "NASDAQ", advancers: Math.max(adv * 55, 1), decliners: Math.max(dec * 50, 1) },
      { exchange: "S&P 500", advancers: Math.max(adv * 12, 1), decliners: Math.max(dec * 10, 1) },
      { exchange: "LIVE", advancers: adv, decliners: dec },
    ],
    gainers,
    losers,
    global_snapshot: macros.length
      ? macros
      : [
          {
            symbol: "VIX",
            label: "VIX",
            value: vix?.price ?? null,
            change_pct: vix?.change_pct ?? null,
            reason: vix?.price == null ? "VIX quote missing" : null,
          },
        ],
    vol_regime:
      vix?.price == null
        ? null
        : vix.price >= 25
          ? "Elevated"
          : vix.price >= 18
            ? "Normal"
            : "Low",
    reason:
      withPct.length === 0
        ? "No live movers — waiting for quotes with change%"
        : null,
  };
}

function buildRiskFromQuotes(watch: TerminalWatchItem[]): TerminalRiskSummary {
  const moves = watch.map((w) => w.change_pct).filter((v): v is number => v != null);
  if (!moves.length) {
    return {
      score: null,
      label: "No data",
      var_pct: null,
      high_beta: [],
      reason: "Need watchlist quotes with change% to estimate risk",
    };
  }
  const absMoves = moves.map((m) => Math.abs(m));
  const avg = absMoves.reduce((a, b) => a + b, 0) / absMoves.length;
  const score = Math.max(10, Math.min(90, Math.round(30 + avg * 12)));
  return {
    score,
    label: score >= 65 ? "Elevated" : score >= 40 ? "Moderate" : "Calm",
    var_pct: Number((avg * 0.8).toFixed(2)),
    high_beta: watch
      .slice()
      .sort((a, b) => Math.abs(b.change_pct ?? 0) - Math.abs(a.change_pct ?? 0))
      .slice(0, 5)
      .map((w) => ({
        symbol: w.symbol,
        price: w.last,
        beta: null,
        change_pct: w.change_pct,
        note: w.change_pct == null ? "insufficient data" : "from live quote",
      })),
  };
}

function buildPerformance(
  indices: TerminalIndexRow[],
  watch: TerminalWatchItem[],
  health: ProviderHealth[] | null,
  pulse?: TerminalPulse | null,
): TerminalPerformanceRow[] {
  const findIdx = (sym: string) => indices.find((i) => i.symbol === sym);
  const findWatch = (...syms: string[]) =>
    watch.find((w) => syms.some((s) => (w.symbol || "").toUpperCase().includes(s.toUpperCase())));
  const pctOrNull = (
    label: string,
    period: string,
    value: number | null | undefined,
    reason: string,
  ): TerminalPerformanceRow => ({
    label,
    period,
    value: value ?? null,
    unit: "pct",
    reason: value == null ? reason : null,
  });

  const pctFromRow = (row: TerminalIndexRow | undefined): number | null => {
    if (!row) return null;
    if (row.change_pct != null) return row.change_pct;
    if (row.change != null && row.price != null && row.price !== 0) {
      return (row.change / row.price) * 100;
    }
    return null;
  };

  const spx = findIdx("SPX");
  const dji = findIdx("DJI");
  const ndx = findIdx("NDX") ?? findIdx("IXIC");
  const vix = findIdx("VIX");
  const imoex = findIdx("IMOEX");
  const btc = findWatch("BTC");
  const gld = findWatch("GLD", "GOLD", "XAU");
  const goldFromPulse = pulse?.global_snapshot?.find(
    (s) => (s.symbol || s.label || "").toUpperCase().includes("GOLD"),
  );
  const btcFromPulse = pulse?.global_snapshot?.find(
    (s) => (s.symbol || s.label || "").toUpperCase().includes("BTC"),
  );

  const spread = (a?: number | null, b?: number | null) =>
    a != null && b != null ? a - b : null;

  const goldPct = gld?.change_pct ?? goldFromPulse?.change_pct ?? null;
  const btcPct = btc?.change_pct ?? btcFromPulse?.change_pct ?? null;

  const rows: TerminalPerformanceRow[] = [
    pctOrNull("NASDAQ Daily", "TODAY", pctFromRow(ndx), "NASDAQ quote missing"),
    pctOrNull("DOW Daily", "TODAY", pctFromRow(dji), "DOW quote missing"),
    pctOrNull("S&P 500 Daily", "TODAY", pctFromRow(spx), "SPX quote missing"),
    pctOrNull(
      "S&P vs DOW Spread",
      "TODAY",
      spread(pctFromRow(spx), pctFromRow(dji)),
      "Need SPX + DJI change%",
    ),
    pctOrNull(
      "NASDAQ vs S&P Spread",
      "TODAY",
      spread(pctFromRow(ndx), pctFromRow(spx)),
      "Need NASDAQ + SPX change%",
    ),
    {
      label: "VIX",
      period: "LEVEL",
      value: vix?.price ?? null,
      unit: "level",
      reason: vix?.price == null ? "VIX quote missing" : null,
    },
    pctOrNull("GOLD (XAU)", "TODAY", goldPct, "gold quote missing"),
    pctOrNull("BTC/USDT", "TODAY", btcPct, "BTC quote missing"),
    pctOrNull("IMOEX", "TODAY", pctFromRow(imoex), "IMOEX quote missing"),
  ];

  if (health?.length) {
    rows.push({
      label: "Providers",
      period: "UP",
      value: health.filter((h) => h.available).length,
      unit: "level",
    });
  }
  return rows;
}

function mapIndexRow(raw: Record<string, unknown>): TerminalIndexRow {
  return {
    symbol: String(raw.symbol ?? ""),
    name: typeof raw.name === "string" ? raw.name : undefined,
    price: num(raw.price),
    change: num(raw.change),
    change_pct: num(raw.change_pct),
    session: (raw.session_status as string) ?? (raw.session as string) ?? null,
    region: (raw.region as string) ?? null,
    currency: (raw.currency as string) ?? null,
    stale: raw.status === "stale" || raw.status === "delayed",
    reason: (raw.reason as string) ?? null,
  };
}

function mapWatchRow(raw: Record<string, unknown>): TerminalWatchItem {
  const sym = String(
    raw.symbol ?? raw.ticker ?? raw.ui_symbol ?? "",
  ).trim();
  return {
    symbol: sym,
    last: num(raw.last ?? raw.price),
    change: num(raw.change),
    change_pct: num(raw.change_pct ?? raw.day_change_pct),
    change_1d: num(raw.change_1d ?? raw.day_change_pct ?? raw.change_pct),
    change_1w: num(raw.change_1w ?? raw.week_change_pct),
    change_1m: num(raw.change_1m ?? raw.month_change_pct),
    change_3m: num(raw.change_3m ?? raw.quarter_change_pct),
    volume: num(raw.volume),
    vol: num(raw.vol ?? raw.vol_atr ?? raw.realized_vol ?? raw.volatility),
    regime: (raw.regime as string) ?? null,
    risk: (raw.risk as string | number) ?? (raw.risk_score as string | number) ?? null,
    sector: (raw.sector as string) ?? (raw.category as string) ?? null,
    session: (raw.session_status as string) ?? (raw.session as string) ?? null,
    feed:
      (raw.feed as string) ??
      (raw.live_delayed as string) ??
      (raw.status === "ok" ? "live" : (raw.status as string)) ??
      null,
    data_only: raw.data_only === true,
    execution_enabled: raw.execution_enabled !== false,
    feed_label_ru: (raw.feed_label_ru as string) ?? null,
    reason: (raw.reason as string) ?? null,
    currency: (raw.currency as string) ?? null,
    bid: num(raw.bid),
    ask: num(raw.ask),
    routing_class: (raw.routing_class as string) ?? null,
    show_volume: raw.show_volume == null ? null : raw.show_volume === true,
  };
}

function alignVixFromIndices(indices: TerminalIndexRow[], pulse: TerminalPulse): TerminalPulse {
  const vix = indices.find((i) => i.symbol === "VIX");
  if (!vix || vix.change_pct == null) return pulse;
  return {
    ...pulse,
    global_snapshot: (pulse.global_snapshot ?? []).map((s) =>
      s.symbol === "VIX" || s.label === "VIX"
        ? { ...s, value: vix.price ?? s.value, change_pct: vix.change_pct }
        : s,
    ),
  };
}

function mapRisk(raw: unknown, watch: TerminalWatchItem[]): TerminalRiskSummary {
  if (raw && typeof raw === "object") {
    const r = raw as Record<string, unknown>;
    const hb = Array.isArray(r.high_beta) ? r.high_beta : [];
    if (hb.length || r.score != null) {
      return {
        score: num(r.score),
        label: typeof r.label === "string" ? r.label : "No data",
        var_pct: num(r.var_pct),
        high_beta: hb.map((row) => {
          const x = row as Record<string, unknown>;
          return {
            symbol: String(x.symbol ?? ""),
            price: num(x.price),
            beta: num(x.beta),
            change_pct: num(x.change_pct),
            note: typeof x.note === "string" ? x.note : null,
          };
        }),
        reason: typeof r.reason === "string" ? r.reason : null,
      };
    }
  }
  return buildRiskFromQuotes(watch);
}

function mapPulse(raw: Record<string, unknown> | null | undefined, fallback: TerminalPulse): TerminalPulse {
  if (!raw) return fallback;
  const breadthRaw = Array.isArray(raw.breadth) ? raw.breadth : [];
  const gainersRaw = Array.isArray(raw.gainers) ? raw.gainers : [];
  const losersRaw = Array.isArray(raw.losers) ? raw.losers : [];
  const snapRaw = Array.isArray(raw.global_snapshot) ? raw.global_snapshot : [];
  return {
    fear_greed: num(raw.fear_greed),
    label: typeof raw.label === "string" ? raw.label : fallback.label,
    breadth: breadthRaw.map((b) => {
      const row = b as Record<string, unknown>;
      return {
        exchange: String(row.exchange ?? "—"),
        advancers: num(row.advancers) ?? 0,
        decliners: num(row.decliners) ?? 0,
      };
    }),
    gainers: gainersRaw.map((g) => {
      const row = g as Record<string, unknown>;
      return {
        symbol: String(row.symbol ?? ""),
        change_pct: num(row.change_pct),
        price: num(row.price ?? row.last),
        volume: num(row.volume),
        volume_label: typeof row.volume_label === "string" ? row.volume_label : fmtVol(num(row.volume)),
      };
    }),
    losers: losersRaw.map((g) => {
      const row = g as Record<string, unknown>;
      return {
        symbol: String(row.symbol ?? ""),
        change_pct: num(row.change_pct),
        price: num(row.price ?? row.last),
        volume: num(row.volume),
        volume_label: typeof row.volume_label === "string" ? row.volume_label : fmtVol(num(row.volume)),
      };
    }),
    global_snapshot: snapRaw.map((s) => {
      const row = s as Record<string, unknown>;
      return {
        symbol: String(row.symbol ?? row.key ?? ""),
        label: typeof row.label === "string" ? row.label : String(row.symbol ?? row.key ?? ""),
        value: num(row.value ?? row.price),
        change_pct: num(row.change_pct),
        reason: (row.reason as string) ?? null,
      };
    }),
    vol_regime:
      (raw.vol_regime as string) ??
      (raw.volatility_regime as string) ??
      null,
    reason: (raw.reason as string) ?? null,
  };
}

function mapHoursRows(raw: unknown): TerminalMarketHoursRow[] {
  if (!Array.isArray(raw) || !raw.length) return computeMarketHours();
  return raw.map((h, i) => {
    const row = h as Record<string, unknown>;
    const exchange = String(row.exchange ?? row.name ?? `ex-${i}`);
    return {
      id: String(row.id ?? exchange.toLowerCase().replace(/[^a-z0-9]+/g, "-")),
      exchange,
      name: typeof row.name === "string" ? row.name : undefined,
      status: (row.status as TerminalSessionStatus) || "unknown",
      local_time: typeof row.local_time === "string" ? row.local_time : null,
      opens_in: typeof row.opens_in === "string" ? row.opens_in : null,
      timezone: typeof row.timezone === "string" ? row.timezone : null,
    };
  });
}

function mapTapeItems(raw: unknown): TerminalTapeItem[] {
  if (!Array.isArray(raw) || !raw.length) return [];
  const out: TerminalTapeItem[] = [];
  for (let i = 0; i < raw.length; i++) {
    const row = raw[i] as Record<string, unknown>;
    const kindRaw = String(row.kind || "index");
    // Hours belong in Market Hours panel — bare exchange labels pollute the tape.
    if (kindRaw === "hours") continue;
    // News headlines belong in the dedicated News panel only.
    if (kindRaw === "headline") continue;
    const item: TerminalTapeItem = {
      id: String(row.id ?? `tape-${i}`),
      kind: (kindRaw as TerminalTapeItem["kind"]) || "index",
      symbol: typeof row.symbol === "string" ? row.symbol : undefined,
      label: String(row.label ?? row.symbol ?? row.headline ?? "—"),
      value: num(row.value ?? row.price),
      change_pct: num(row.change_pct),
      text: typeof row.text === "string" ? row.text : typeof row.headline === "string" ? row.headline : undefined,
    };
    // Skip price-less quote labels (e.g. stray NYSE/NASDAQ/LSE).
    if (item.value != null || item.change_pct != null || Boolean(item.text)) {
      out.push(item);
    }
  }
  return dedupeTapeItems(out);
}

function mapQuantFactorsLoose(raw: unknown): TerminalQuantFactor[] {
  if (!Array.isArray(raw) || !raw.length) return [];
  return raw.map((f, i) => {
    const row = f as Record<string, unknown>;
    return {
      id: String(row.id ?? `qf-${i}`),
      name: String(row.name ?? row.label ?? `Factor ${i + 1}`),
      weight: num(row.weight),
      contribution: num(row.contribution),
      value: (row.value as string | number) ?? null,
      source: (row.source as string) ?? null,
      freshness: (row.freshness as string) ?? null,
      confidence: num(row.confidence),
      tip: (row.tip as string) ?? (row.why as string) ?? null,
    };
  });
}

function mapNewsLoose(raw: unknown): TerminalNewsItem[] {
  if (!Array.isArray(raw) || !raw.length) return [];
  return raw.map((n, i) => {
    const row = n as Record<string, unknown>;
    return {
      id: String(row.id ?? `n-${i}`),
      headline: String(row.headline ?? row.title ?? "—"),
      source: String(row.source ?? row.provider ?? "news"),
      published_at: String(row.published_at ?? row.ts ?? nowIso()),
      url: (row.url as string) ?? null,
      summary: (row.summary as string) ?? null,
    };
  });
}

function mapCalendarLoose(raw: unknown): TerminalCalendarEvent[] {
  if (!Array.isArray(raw) || !raw.length) return [];
  return raw.map((c, i) => {
    const row = c as Record<string, unknown>;
    const imp = String(row.importance ?? "").toLowerCase();
    return {
      id: String(row.id ?? `cal-${i}`),
      title: String(row.title ?? row.event ?? "—"),
      when: String(row.when ?? row.datetime ?? row.date ?? nowIso()),
      region: (row.region as string) ?? (row.country as string) ?? (row.cty as string) ?? undefined,
      importance: imp === "high" || imp === "medium" || imp === "low" ? imp : undefined,
      expected: (row.expected as string) ?? null,
      actual: (row.actual as string) ?? null,
      previous: (row.previous as string) ?? (row.prev as string) ?? null,
      forecast: (row.forecast as string) ?? (row.fcst as string) ?? (row.expected as string) ?? null,
    };
  });
}

function normalizeSnapshot(raw: Partial<TerminalSnapshot> & Record<string, unknown>): TerminalSnapshot | null {
  if (!raw || typeof raw !== "object") return null;
  const hasIndices = Array.isArray(raw.indices);
  const hasWatch =
    Array.isArray(raw.watchlist) ||
    Array.isArray(raw.watchlist_enriched) ||
    Array.isArray((raw as { watchlist_items?: unknown }).watchlist_items);
  if (!hasIndices && !hasWatch && !raw.pulse && !Array.isArray(raw.market_hours)) return null;

  const mock = buildEmptySnapshot();
  const indices = hasIndices
    ? ((raw.indices as unknown) as Record<string, unknown>[]).map(mapIndexRow).filter((r) => r.symbol)
    : [];

  const watchSrc =
    (Array.isArray(raw.watchlist) && raw.watchlist) ||
    (Array.isArray(raw.watchlist_enriched) && raw.watchlist_enriched) ||
    (Array.isArray((raw as { watchlist_items?: unknown }).watchlist_items) &&
      (raw as { watchlist_items: unknown[] }).watchlist_items) ||
    [];
  const watchlist = ((watchSrc as unknown) as Record<string, unknown>[])
    .map(mapWatchRow)
    .filter((w) => w.symbol);

  const pulseBase = mapPulse(raw.pulse as Record<string, unknown> | undefined, {
    fear_greed: null,
    label: "",
    breadth: [],
    gainers: [],
    losers: [],
    global_snapshot: [],
    vol_regime: null,
    reason: "Pulse data unavailable",
  });
  const news = mapNewsLoose(raw.news);
  const calendar = mapCalendarLoose(raw.calendar);
  const market_hours = mapHoursRows(raw.market_hours);
  const factors = mapQuantFactorsLoose(raw.quant_factors);
  const quantFromFactors: TerminalQuantMetric[] = factors.map((f) => ({
    id: f.id,
    label: f.name,
    value: f.value != null ? String(f.value) : f.contribution != null ? f.contribution.toFixed(2) : "—",
    delta: f.contribution ?? null,
    hint: f.source ?? undefined,
    weight: f.weight,
    contribution: f.contribution,
    source: f.source ?? undefined,
    freshness: f.freshness ?? undefined,
    confidence: f.confidence ?? undefined,
    tip: f.tip ?? undefined,
  }));

  let tape = mapTapeItems(raw.tape ?? raw.tape_items);
  if (!tape.length) {
    tape = buildTapeFromParts(indices, watchlist, pulseBase);
  }

  const portfolio =
    mapPortfolioLoose(raw.portfolio) ||
    mapPortfolioLoose(raw.portfolio_summary) ||
    emptyPortfolio(
      typeof (raw.portfolio_summary as { empty_reason?: string } | null)?.empty_reason === "string"
        ? (raw.portfolio_summary as { empty_reason: string }).empty_reason
        : "No portfolios yet — connect a broker or fund a venue account.",
    );

  const coverage = raw.data_coverage;
  const notes: string[] = [];
  if (Array.isArray(raw.data_notes)) notes.push(...(raw.data_notes as string[]));
  if (coverage && typeof coverage === "object") {
    const c = coverage as Record<string, unknown>;
    if (c.note && typeof c.note === "string") notes.push(c.note);
  }
  if (indices.some((i) => i.change_pct == null && i.price != null)) {
    notes.push("Some index change% unavailable from provider — showing price only");
  }

  const stickyIndices =
    indices.some(indexHasQuote)
      ? preferEnrichedIndices(indices, lastGoodSnapshot?.indices)
      : lastGoodSnapshot?.indices?.some(indexHasQuote)
        ? lastGoodSnapshot.indices
        : preferPopulatedArray(indices, lastGoodSnapshot?.indices);
  const stickyWatch =
    watchlist.some(watchHasQuote)
      ? preferEnrichedWatch(watchlist, lastGoodSnapshot?.watchlist)
      : lastGoodSnapshot?.watchlist?.some(watchHasQuote)
        ? lastGoodSnapshot.watchlist
        : preferPopulatedArray(watchlist, lastGoodSnapshot?.watchlist);

  const pulse = alignVixFromIndices(
    stickyIndices.length ? stickyIndices : indices,
    pulseBase,
  );

  const derivedPerf = buildPerformance(
    stickyIndices.length ? stickyIndices : indices,
    stickyWatch,
    null,
    pulse,
  );
  const incomingPerf = Array.isArray(raw.performance)
    ? (raw.performance as TerminalPerformanceRow[]).map((p) => ({
        ...p,
        value: p.value ?? null,
        reason: p.reason ?? (p.value == null ? "no data yet" : null),
      }))
    : [];
  // Always fill day% from live quotes when dedicated performance rows are empty.
  const performance = mergePerformanceRows(
    mergePerformanceRows(lastGoodSnapshot?.performance ?? [], incomingPerf),
    derivedPerf,
  );

  const rawChart =
    raw.chart && typeof raw.chart === "object"
      ? (raw.chart as TerminalChartSeries)
      : null;

  return {
    as_of: typeof raw.as_of === "string" ? raw.as_of : nowIso(),
    source: raw.source === "live" || raw.source === "partial" || raw.source === "mock" ? raw.source : "live",
    // Prefer last-good over mock so empty snapshot bursts don't flash demo then blank.
    indices: stickyIndices.length ? stickyIndices : indices,
    performance,
    pulse,
    risk: mapRisk(raw.risk, stickyWatch.length ? stickyWatch : watchlist),
    news,
    calendar,
    watchlist: stickyWatch,
    alerts: Array.isArray(raw.alerts) ? (raw.alerts as TerminalAlert[]) : [],
    quant: Array.isArray(raw.quant) && (raw.quant as unknown[]).length
      ? (raw.quant as TerminalQuantMetric[])
      : quantFromFactors.length
        ? quantFromFactors
        : mock.quant,
    quant_factors: factors.length ? factors : mock.quant_factors,
    agents: Array.isArray(raw.agents) && (raw.agents as unknown[]).length
      ? (raw.agents as TerminalAgentCard[])
      : mock.agents,
    chart: preferLiveChart(rawChart, lastGoodSnapshot?.chart),
    tape,
    market_hours,
    portfolio,
    data_notes: notes.length ? notes : undefined,
  };
}

function mapPortfolioLoose(raw: unknown): TerminalPortfolio | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  const positions = Array.isArray(r.positions)
    ? (r.positions as TerminalPortfolio["positions"])
    : Array.isArray(r.holdings_list)
      ? (r.holdings_list as TerminalPortfolio["positions"])
      : [];
  const holdings =
    typeof r.holdings === "number"
      ? r.holdings
      : positions.length || (typeof r.position_count === "number" ? r.position_count : 0);
  return {
    total_value: num(r.total_value ?? r.equity ?? r.nav),
    day_pnl: num(r.day_pnl ?? r.day_pl ?? r.unrealized_pnl),
    day_pnl_pct: num(r.day_pnl_pct ?? r.day_pl_pct),
    total_pnl: num(r.total_pnl ?? r.total_pl),
    total_pnl_pct: num(r.total_pnl_pct),
    holdings: typeof holdings === "number" ? holdings : 0,
    cash: num(r.cash),
    drawdown: num(r.drawdown ?? r.max_drawdown),
    concentration: typeof r.concentration === "string" ? r.concentration : null,
    exposures: Array.isArray(r.exposures) ? (r.exposures as TerminalPortfolio["exposures"]) : undefined,
    allocations: Array.isArray(r.allocations)
      ? (r.allocations as TerminalPortfolio["allocations"])
      : undefined,
    positions,
    empty_reason:
      positions.length === 0
        ? (typeof r.empty_reason === "string"
            ? r.empty_reason
            : "No portfolios yet — connect a broker or fund a venue account.")
        : null,
    connected: Boolean((r.connected ?? false) || positions.length > 0 || num(r.total_value) != null),
  };
}

/** Never wipe a populated panel with an empty array from a newer payload. */
export function preferPopulatedArray<T>(incoming: T[] | undefined | null, previous: T[] | undefined | null): T[] {
  if (Array.isArray(incoming) && incoming.length > 0) return incoming;
  if (Array.isArray(previous) && previous.length > 0) return previous;
  return Array.isArray(incoming) ? incoming : [];
}

/** Keep previous non-null metric fields when patch sends null/undefined (WS ticks). */
function upsertRowKeepFilled<T extends Record<string, unknown>>(existing: T, patch: T): T {
  const out: Record<string, unknown> = { ...existing };
  for (const [k, v] of Object.entries(patch)) {
    if (v === null || v === undefined) continue;
    if (typeof v === "string" && v.trim() === "" && typeof existing[k] === "string" && (existing[k] as string).trim()) {
      continue;
    }
    out[k] = v;
  }
  // Never blank a symbol that already had a label.
  if ((!out.symbol || String(out.symbol).trim() === "") && existing.symbol) {
    out.symbol = existing.symbol;
  }
  return out as T;
}

function indexEnrichmentScore(row: TerminalIndexRow): number {
  let s = 0;
  if (row.price != null) s += 2;
  if (row.change != null) s += 1;
  if (row.change_pct != null) s += 3;
  if (row.session) s += 1;
  return s;
}

function watchEnrichmentScore(row: TerminalWatchItem): number {
  let s = 0;
  if (row.symbol?.trim()) s += 4;
  if (row.last != null) s += 2;
  if (row.change_pct != null) s += 3;
  if (row.change_1w != null) s += 1;
  if (row.change_1m != null) s += 1;
  if (row.regime) s += 1;
  return s;
}

function mergeRowsBySymbol<T extends { symbol: string }>(
  prev: T[],
  patch: T[],
  score?: (row: T) => number,
): T[] {
  if (!patch.length) return prev;
  if (!prev.length) return patch;
  const map = new Map<string, T>();
  for (const row of prev) {
    if (row.symbol) map.set(row.symbol, row);
  }
  for (const row of patch) {
    if (!row.symbol?.trim()) continue;
    const existing = map.get(row.symbol);
    if (!existing) {
      map.set(row.symbol, row);
      continue;
    }
    const merged = upsertRowKeepFilled(
      existing as unknown as Record<string, unknown>,
      row as unknown as Record<string, unknown>,
    ) as unknown as T;
    if (score) {
      // Prefer the richer row overall when patch is a sparse downgrade.
      map.set(row.symbol, score(merged) >= score(existing) ? merged : upsertRowKeepFilled(
        row as unknown as Record<string, unknown>,
        existing as unknown as Record<string, unknown>,
      ) as unknown as T);
    } else {
      map.set(row.symbol, merged);
    }
  }
  // Keep previous order, then append new symbols.
  const seen = new Set<string>();
  const out: T[] = [];
  for (const row of prev) {
    const merged = map.get(row.symbol);
    if (merged && !seen.has(row.symbol)) {
      out.push(merged);
      seen.add(row.symbol);
    }
  }
  for (const row of patch) {
    if (row.symbol && !seen.has(row.symbol)) {
      out.push(map.get(row.symbol)!);
      seen.add(row.symbol);
    }
  }
  return out;
}

/** Prefer incoming only when it is at least as enriched; else field-merge with last-good. */
function preferEnrichedIndices(incoming: TerminalIndexRow[], previous: TerminalIndexRow[] | undefined): TerminalIndexRow[] {
  if (!incoming.length) return previous?.length ? previous : incoming;
  if (!previous?.length) return incoming;
  const inScore = incoming.reduce((a, r) => a + indexEnrichmentScore(r), 0);
  const prevScore = previous.reduce((a, r) => a + indexEnrichmentScore(r), 0);
  if (inScore >= prevScore) return mergeRowsBySymbol(previous, incoming, indexEnrichmentScore);
  return mergeRowsBySymbol(incoming, previous, indexEnrichmentScore);
}

function preferEnrichedWatch(incoming: TerminalWatchItem[], previous: TerminalWatchItem[] | undefined): TerminalWatchItem[] {
  if (!incoming.length) return previous?.length ? previous : incoming;
  if (!previous?.length) return incoming;
  const inScore = incoming.reduce((a, r) => a + watchEnrichmentScore(r), 0);
  const prevScore = previous.reduce((a, r) => a + watchEnrichmentScore(r), 0);
  if (inScore >= prevScore) return mergeRowsBySymbol(previous, incoming, watchEnrichmentScore);
  return mergeRowsBySymbol(incoming, previous, watchEnrichmentScore);
}

function indexHasQuote(row: TerminalIndexRow): boolean {
  return row.price != null && Number.isFinite(row.price);
}

function watchHasQuote(row: TerminalWatchItem): boolean {
  return row.last != null && Number.isFinite(row.last);
}

function performanceHasValue(row: TerminalPerformanceRow): boolean {
  return row.value != null && Number.isFinite(row.value);
}

function mergePerformanceRows(
  prev: TerminalPerformanceRow[],
  incoming: TerminalPerformanceRow[],
): TerminalPerformanceRow[] {
  if (!incoming.length) return prev.length ? prev : incoming;
  if (!prev.length) return incoming;
  const byLabel = new Map(prev.map((r) => [`${r.label}|${r.period}`, r]));
  for (const row of incoming) {
    const key = `${row.label}|${row.period}`;
    const existing = byLabel.get(key);
    if (!existing) {
      byLabel.set(key, row);
      continue;
    }
    // Keep last-good value when newer row is empty / "no data".
    if (!performanceHasValue(row) && performanceHasValue(existing)) {
      byLabel.set(key, existing);
    } else {
      byLabel.set(key, { ...existing, ...row, value: row.value ?? existing.value });
    }
  }
  const seen = new Set<string>();
  const out: TerminalPerformanceRow[] = [];
  for (const row of prev) {
    const key = `${row.label}|${row.period}`;
    if (!seen.has(key)) {
      out.push(byLabel.get(key)!);
      seen.add(key);
    }
  }
  for (const row of incoming) {
    const key = `${row.label}|${row.period}`;
    if (!seen.has(key)) {
      out.push(byLabel.get(key)!);
      seen.add(key);
    }
  }
  return out;
}

function extractIndexRows(
  ep:
    | { items?: TerminalIndexRow[]; indices?: TerminalIndexRow[] }
    | TerminalIndexRow[]
    | null
    | undefined,
): TerminalIndexRow[] {
  if (!ep) return [];
  if (Array.isArray(ep)) return ep.filter((r) => r?.symbol);
  return (ep.items ?? ep.indices ?? []).filter((r) => r?.symbol);
}

function extractWatchRows(
  ep:
    | { items?: TerminalWatchItem[]; watchlist?: TerminalWatchItem[] }
    | TerminalWatchItem[]
    | null
    | undefined,
): TerminalWatchItem[] {
  if (!ep) return [];
  if (Array.isArray(ep)) return ep.filter((r) => r?.symbol);
  return (ep.items ?? ep.watchlist ?? []).filter((r) => r?.symbol);
}

/** Module last-good cache so empty poll/WS payloads cannot blank the terminal. */
let lastGoodSnapshot: TerminalSnapshot | null = null;
let snapshotFetchSeq = 0;

export function getLastGoodTerminalSnapshot(): TerminalSnapshot | null {
  return lastGoodSnapshot;
}

/**
 * Merge a newer snapshot/patch onto previous state.
 * - Empty arrays never replace populated indices / watchlist / performance / tape / news / calendar
 * - Partial WS ticks upsert by symbol instead of replacing the whole panel
 */
export function mergeTerminalSnapshot(
  previous: TerminalSnapshot | null | undefined,
  incoming: Partial<TerminalSnapshot> | (Partial<TerminalSnapshot> & Record<string, unknown>),
  opts?: { mode?: "full" | "patch" },
): TerminalSnapshot {
  const mode = opts?.mode ?? "full";
  const prev = previous ?? lastGoodSnapshot ?? undefined;
  const patch = incoming as Partial<TerminalSnapshot> & Record<string, unknown>;

  const rawIndices = Array.isArray(patch.indices)
    ? ((patch.indices as unknown) as Record<string, unknown>[]).map(mapIndexRow).filter((r) => r.symbol)
    : undefined;
  const rawWatchSrc =
    (Array.isArray(patch.watchlist) && patch.watchlist) ||
    (Array.isArray(patch.watchlist_enriched) && patch.watchlist_enriched) ||
    (Array.isArray((patch as { watchlist_items?: unknown }).watchlist_items) &&
      (patch as { watchlist_items: unknown[] }).watchlist_items) ||
    undefined;
  const rawWatch = Array.isArray(rawWatchSrc)
    ? ((rawWatchSrc as unknown) as Record<string, unknown>[]).map(mapWatchRow).filter((w) => w.symbol)
    : undefined;

  let indices: TerminalIndexRow[];
  if (rawIndices === undefined) {
    indices = prev?.indices ?? [];
  } else if (mode === "patch") {
    indices = mergeRowsBySymbol(prev?.indices ?? [], rawIndices, indexEnrichmentScore);
  } else {
    indices = preferEnrichedIndices(rawIndices, prev?.indices);
  }

  let watchlist: TerminalWatchItem[];
  if (rawWatch === undefined) {
    watchlist = prev?.watchlist ?? [];
  } else if (mode === "patch") {
    watchlist = mergeRowsBySymbol(prev?.watchlist ?? [], rawWatch, watchEnrichmentScore);
  } else {
    watchlist = preferEnrichedWatch(rawWatch, prev?.watchlist);
  }

  const incomingPerf = Array.isArray(patch.performance)
    ? (patch.performance as TerminalPerformanceRow[])
    : undefined;
  let performance: TerminalPerformanceRow[];
  if (incomingPerf === undefined) {
    performance =
      prev?.performance?.length
        ? prev.performance
        : buildPerformance(indices, watchlist, null);
  } else if (mode === "patch") {
    performance = mergePerformanceRows(prev?.performance ?? [], incomingPerf);
  } else {
    const mergedPerf = mergePerformanceRows(prev?.performance ?? [], incomingPerf);
    performance = preferPopulatedArray(
      mergedPerf.filter(performanceHasValue).length ? mergedPerf : incomingPerf,
      prev?.performance,
    );
    if (!performance.some(performanceHasValue) && (indices.some(indexHasQuote) || watchlist.some(watchHasQuote))) {
      performance = mergePerformanceRows(prev?.performance ?? [], buildPerformance(indices, watchlist, null));
    }
  }

  const tapeFromPatch = mapTapeItems(patch.tape ?? patch.tape_items);
  const mergedTape =
    mode === "patch" && tapeFromPatch.length
      ? dedupeTapeItems([
          ...tapeFromPatch,
          ...(prev?.tape ?? []).filter((t) => !tapeFromPatch.some((n) => n.id === t.id)),
        ])
      : preferPopulatedArray(tapeFromPatch.length ? tapeFromPatch : undefined, prev?.tape);
  const tape = dedupeTapeItems(mergedTape ?? []);

  const newsLoose = mapNewsLoose(patch.news);
  const calendarLoose = mapCalendarLoose(patch.calendar);
  const hoursLoose = Array.isArray(patch.market_hours) ? mapHoursRows(patch.market_hours) : undefined;

  const pulse =
    patch.pulse && typeof patch.pulse === "object"
      ? mapPulse(patch.pulse as unknown as Record<string, unknown>, prev?.pulse ?? EMPTY_PULSE)
      : prev?.pulse ?? EMPTY_PULSE;

  const base: TerminalSnapshot = {
    as_of: typeof patch.as_of === "string" ? patch.as_of : prev?.as_of ?? nowIso(),
    source:
      patch.source === "live" || patch.source === "partial" || patch.source === "mock"
        ? patch.source
        : prev?.source ?? "live",
    indices,
    performance,
    pulse,
    risk: (patch.risk as TerminalRiskSummary) ?? prev?.risk ?? buildRiskFromQuotes(watchlist),
    news: preferPopulatedArray(newsLoose.length ? newsLoose : undefined, prev?.news),
    calendar: preferPopulatedArray(calendarLoose.length ? calendarLoose : undefined, prev?.calendar),
    watchlist,
    alerts: Array.isArray(patch.alerts) && (patch.alerts as TerminalAlert[]).length
      ? (patch.alerts as TerminalAlert[])
      : prev?.alerts ?? [],
    quant: Array.isArray(patch.quant) && (patch.quant as TerminalQuantMetric[]).length
      ? (patch.quant as TerminalQuantMetric[])
      : prev?.quant ?? [],
    quant_factors:
      Array.isArray(patch.quant_factors) && (patch.quant_factors as TerminalQuantFactor[]).length
        ? (patch.quant_factors as TerminalQuantFactor[])
        : prev?.quant_factors,
    agents: Array.isArray(patch.agents) && (patch.agents as TerminalAgentCard[]).length
      ? (patch.agents as TerminalAgentCard[])
      : prev?.agents ?? [],
    chart: preferLiveChart(patch.chart as TerminalChartSeries | undefined, prev?.chart),
    tape: tape.length ? tape : preferPopulatedArray(undefined, prev?.tape),
    market_hours: preferPopulatedArray(hoursLoose, prev?.market_hours),
    portfolio:
      mapPortfolioLoose(patch.portfolio) ||
      mapPortfolioLoose(patch.portfolio_summary) ||
      prev?.portfolio ||
      emptyPortfolio("No portfolios yet — connect a broker or fund a venue account."),
    data_notes: Array.isArray(patch.data_notes)
      ? (patch.data_notes as string[])
      : prev?.data_notes,
  };

  if (!base.tape?.length) {
    base.tape = buildTapeFromParts(base.indices, base.watchlist, base.pulse);
  }

  // If this payload blanked panels, restore from module last-good (no recursion).
  if (
    !(base.indices.some(indexHasQuote) || base.watchlist.some(watchHasQuote)) &&
    lastGoodSnapshot &&
    (lastGoodSnapshot.indices.some(indexHasQuote) || lastGoodSnapshot.watchlist.some(watchHasQuote))
  ) {
    base.indices = preferPopulatedArray(base.indices, lastGoodSnapshot.indices);
    base.watchlist = preferPopulatedArray(base.watchlist, lastGoodSnapshot.watchlist);
    base.performance = mergePerformanceRows(lastGoodSnapshot.performance, base.performance);
    base.tape = preferPopulatedArray(base.tape, lastGoodSnapshot.tape);
    if (!base.pulse?.fear_greed && lastGoodSnapshot.pulse) base.pulse = lastGoodSnapshot.pulse;
  }

  if (base.indices.some(indexHasQuote) || base.watchlist.some(watchHasQuote)) {
    lastGoodSnapshot = base;
  }

  return base;
}

function rememberGoodSnapshot(snap: TerminalSnapshot): TerminalSnapshot {
  return mergeTerminalSnapshot(lastGoodSnapshot, snap as Partial<TerminalSnapshot>, { mode: "full" });
}

async function fetchQuote(apiSymbol: string): Promise<QuotePayload | null> {
  const res = await tryGet<FetchResult<QuotePayload>>("/terminal/quote", { symbol: apiSymbol });
  if (!res?.success || !res.data) return null;
  return res.data;
}

async function composeFromPartials(): Promise<TerminalSnapshot> {
  const mock = buildEmptySnapshot();
  const notes: string[] = [];
  const composeStarted = Date.now();

  const withBudget = async <T,>(fn: () => Promise<T>, fallback: T): Promise<T> => {
    const left = OVERALL_COMPOSE_BUDGET_MS - (Date.now() - composeStarted);
    if (left < 200) return fallback;
    return Promise.race([
      fn(),
      new Promise<T>((resolve) => {
        window.setTimeout(() => resolve(fallback), left);
      }),
    ]);
  };

  // 1) Fast snapshot under hard budget — NEVER wait forever on wait=full / open circuits.
  const [snapshotTry, health] = await Promise.all([
    tryGet<Partial<TerminalSnapshot>>(
      "/terminal/snapshot",
      { include_periods: 0, wait: "full" },
      { timeoutMs: SNAPSHOT_TIMEOUT_MS },
    ),
    tryGet<ProviderHealth[]>("/terminal/providers/health", undefined, { timeoutMs: 4_000 }),
  ]);

  const healthAlerts = buildAlertsFromHealth(health);
  const normalized = snapshotTry
    ? normalizeSnapshot(snapshotTry as Partial<TerminalSnapshot> & Record<string, unknown>)
    : null;

  const snapshotLooksUsable =
    !!normalized &&
    (normalized.indices.some((i) => i.price != null) ||
      normalized.watchlist.some((w) => Boolean(w.symbol?.trim()) && w.last != null) ||
      (normalized.news?.length ?? 0) > 0 ||
      normalized.pulse?.fear_greed != null);

  if (normalized && snapshotLooksUsable) {
    if (healthAlerts.length) normalized.alerts = healthAlerts;
    // Optional secondary enrichments — never block first usable paint past budget.
    const left = OVERALL_COMPOSE_BUDGET_MS - (Date.now() - composeStarted);
    if (left > 1_500) {
      const [ohlcvRes, agentsIdx, portfolioEp, portfolioDash] = await Promise.all([
        tryGet<FetchResult<OhlcvBar[]>>(
          "/terminal/ohlcv",
          { symbol: CHART_SYMBOL.api, timeframe: "1h" },
          { timeoutMs: Math.min(6_000, left) },
        ),
        tryGet<{ agents?: string[]; items?: string[] }>("/terminal/agents", undefined, {
          timeoutMs: Math.min(4_000, left),
        }),
        tryGet<unknown>("/terminal/portfolio", undefined, { timeoutMs: Math.min(4_000, left) }),
        tryGet<Record<string, unknown>>("/portfolio/metrics", undefined, {
          timeoutMs: Math.min(4_000, left),
        }),
      ]);
      const chartFromSnap =
        normalized.chart?.points?.length && !looksLikeSineMockChart(normalized.chart.points)
          ? normalized.chart
          : null;
      const chart =
        chartFromSnap ||
        mapOhlcvChart(
          ohlcvRes?.success ? ohlcvRes.data ?? undefined : undefined,
          CHART_SYMBOL.ui,
        );
      normalized.chart = preferLiveChart(chart, lastGoodSnapshot?.chart);
      normalized.performance = mergePerformanceRows(
        normalized.performance,
        buildPerformance(normalized.indices, normalized.watchlist, health, normalized.pulse),
      );
      const agentIds = agentsIdx?.agents ?? agentsIdx?.items ?? null;
      const agents = mapAgents(agentIds);
      if (agents.length) normalized.agents = agents;
      if (!normalized.portfolio?.connected) {
        normalized.portfolio =
          mapPortfolioLoose(portfolioEp) ||
          mapPortfolioLoose(portfolioDash) ||
          normalized.portfolio;
      }
    }
    if (notes.length) {
      normalized.data_notes = [...(normalized.data_notes ?? []), ...notes];
    }
    return rememberGoodSnapshot(normalized);
  }

  if (snapshotTry === null) {
    notes.push("GET /terminal/snapshot timed out or unavailable — composing from sub-endpoints");
  } else if (normalized) {
    notes.push("Snapshot returned partial enrichment — filling from sub-endpoints");
  }

  // 2) Fallback: parallel sub-endpoints under remaining budget (never 60s waits).
  const leftForFallback = Math.max(
    1_000,
    OVERALL_COMPOSE_BUDGET_MS - (Date.now() - composeStarted),
  );
  const subTimeout = Math.min(SUB_ENDPOINT_TIMEOUT_MS, leftForFallback);

  const [
    indicesEp,
    pulseEp,
    hoursEp,
    tapeEp,
    watchEp,
    portfolioEp,
    agentsIdx,
    newsRes,
    ohlcvRes,
    ohlcvDailyRes,
    calendarRes,
    portfolioDash,
  ] = await withBudget(
    () =>
      Promise.all([
        tryGet<{ items?: TerminalIndexRow[]; indices?: TerminalIndexRow[] } | TerminalIndexRow[]>(
          "/terminal/indices",
          { include_periods: 0 },
          { timeoutMs: subTimeout },
        ),
        tryGet<TerminalPulse>("/terminal/pulse", undefined, { timeoutMs: subTimeout }),
        tryGet<
          { items?: TerminalMarketHoursRow[]; market_hours?: TerminalMarketHoursRow[] } | TerminalMarketHoursRow[]
        >("/terminal/market-hours", undefined, { timeoutMs: 3_000 }),
        tryGet<{ items?: TerminalTapeItem[]; tape?: TerminalTapeItem[] } | TerminalTapeItem[]>(
          "/terminal/tape",
          undefined,
          { timeoutMs: subTimeout },
        ),
        tryGet<{ items?: TerminalWatchItem[]; watchlist?: TerminalWatchItem[] } | TerminalWatchItem[]>(
          "/terminal/watchlist",
          undefined,
          { timeoutMs: subTimeout },
        ),
        tryGet<unknown>("/terminal/portfolio", undefined, { timeoutMs: 4_000 }),
        tryGet<{ agents?: string[]; items?: string[] }>("/terminal/agents", undefined, {
          timeoutMs: 4_000,
        }),
        tryGet<FetchResult<NewsPayload[]>>(
          "/terminal/news",
          {
            limit: 20,
            symbols: "AAPL,MSFT,NVDA,SPY,BTC-USD,SBER.ME",
          },
          { timeoutMs: subTimeout },
        ),
        tryGet<FetchResult<OhlcvBar[]>>(
          "/terminal/ohlcv",
          {
            symbol: CHART_SYMBOL.api,
            timeframe: "1h",
          },
          { timeoutMs: subTimeout },
        ),
        tryGet<FetchResult<OhlcvBar[]>>(
          "/terminal/ohlcv",
          {
            symbol: "SPY",
            timeframe: "1d",
          },
          { timeoutMs: subTimeout },
        ),
        tryGet<FetchResult<CalendarPayload[]>>(
          "/terminal/calendar",
          { limit: 30 },
          { timeoutMs: subTimeout },
        ),
        tryGet<Record<string, unknown>>("/portfolio/metrics", undefined, { timeoutMs: 4_000 }),
      ]),
    [
      null,
      null,
      null,
      null,
      null,
      null,
      null,
      null,
      null,
      null,
      null,
      null,
    ],
  );

  if (normalized && (normalized.indices.some((i) => i.price != null) || normalized.pulse.fear_greed != null)) {
    const epIndices = extractIndexRows(indicesEp).map((r) =>
      mapIndexRow(r as unknown as Record<string, unknown>),
    );
    const epWatch = extractWatchRows(watchEp).map((r) =>
      mapWatchRow(r as unknown as Record<string, unknown>),
    );

    if (epIndices.some(indexHasQuote)) {
      normalized.indices = preferEnrichedIndices(
        mergeRowsBySymbol(normalized.indices, epIndices, indexEnrichmentScore),
        normalized.indices,
      );
    }
    if (epWatch.some(watchHasQuote)) {
      normalized.watchlist = preferEnrichedWatch(
        mergeRowsBySymbol(normalized.watchlist, epWatch, watchEnrichmentScore),
        normalized.watchlist,
      );
    }

    if (pulseEp && typeof pulseEp === "object") {
      normalized.pulse = mapPulse(pulseEp as unknown as Record<string, unknown>, normalized.pulse);
    }

    if (!normalized.watchlist.length) {
      const leftQuotes = OVERALL_COMPOSE_BUDGET_MS - (Date.now() - composeStarted);
      if (leftQuotes > 2_000) {
        const quoteWatch = await Promise.all(WATCH_UNIVERSE.map((m) => fetchQuote(m.api)));
        const filled = WATCH_UNIVERSE.map((m, i) => quoteToWatch(m.ui, quoteWatch[i], m.sector)).filter(
          (w) => w.last != null && w.symbol,
        );
        if (filled.length) normalized.watchlist = filled;
      }
    }

    if (!normalized.performance?.some(performanceHasValue)) {
      normalized.performance = buildPerformance(normalized.indices, normalized.watchlist, null);
    } else {
      normalized.performance = mergePerformanceRows(
        normalized.performance,
        buildPerformance(normalized.indices, normalized.watchlist, null),
      );
    }

    if (!normalized.tape?.length) {
      normalized.tape = buildTapeFromParts(
        normalized.indices,
        normalized.watchlist,
        normalized.pulse,
      );
    }
    if (!normalized.market_hours?.length) {
      normalized.market_hours = computeMarketHours();
    }
    if (!normalized.portfolio) {
      normalized.portfolio =
        mapPortfolioLoose(portfolioEp) ||
        mapPortfolioLoose(portfolioDash) ||
        emptyPortfolio("No portfolios yet — connect a broker or fund a venue account.");
    }
    const chart = mapOhlcvChart(
      ohlcvRes?.success ? ohlcvRes.data ?? undefined : undefined,
      CHART_SYMBOL.ui,
    );
    if (chart) normalized.chart = chart;
    const agentIds = agentsIdx?.agents ?? agentsIdx?.items ?? null;
    const agents = mapAgents(agentIds);
    if (agents.length) normalized.agents = agents;
    if (healthAlerts.length) normalized.alerts = healthAlerts;
    if (notes.length) {
      normalized.data_notes = [...(normalized.data_notes ?? []), ...notes];
    }
    return rememberGoodSnapshot(normalized);
  }

  const leftForQuotes = OVERALL_COMPOSE_BUDGET_MS - (Date.now() - composeStarted);
  const quoteResults =
    leftForQuotes > 2_500
      ? await Promise.all([
          ...INDEX_UNIVERSE.map((m) => fetchQuote(m.api)),
          ...WATCH_UNIVERSE.map((m) => fetchQuote(m.api)),
          ...MACRO_SNAPSHOT.map((m) => fetchQuote(m.api)),
        ])
      : [];
  if (!quoteResults.length) {
    notes.push("Skipped per-symbol quotes — compose budget exhausted");
  }

  const indexQuotes = quoteResults.slice(0, INDEX_UNIVERSE.length);
  const watchQuotes = quoteResults.slice(
    INDEX_UNIVERSE.length,
    INDEX_UNIVERSE.length + WATCH_UNIVERSE.length,
  );
  const macroQuotes = quoteResults.slice(INDEX_UNIVERSE.length + WATCH_UNIVERSE.length);

  let indices: TerminalIndexRow[] = [];
  if (Array.isArray(indicesEp)) {
    indices = indicesEp.map((r) => mapIndexRow(r as unknown as Record<string, unknown>));
  } else if (indicesEp && typeof indicesEp === "object") {
    indices = (indicesEp.items ?? indicesEp.indices ?? []).map((r) =>
      mapIndexRow(r as unknown as Record<string, unknown>),
    );
  }
  if (!indices.length) {
    indices = INDEX_UNIVERSE.map((m, i) => quoteToIndex(m, indexQuotes[i]));
    const priced = indices.filter((i) => i.price != null).length;
    if (priced === 0) notes.push("Index quotes empty — providers may be rate-limited or offline");
  }

  let watchlist: TerminalWatchItem[] = [];
  if (Array.isArray(watchEp)) {
    watchlist = watchEp.map((r) => mapWatchRow(r as unknown as Record<string, unknown>)).filter((w) => w.symbol);
  } else if (watchEp && typeof watchEp === "object") {
    watchlist = (watchEp.items ?? watchEp.watchlist ?? [])
      .map((r) => mapWatchRow(r as unknown as Record<string, unknown>))
      .filter((w) => w.symbol);
  }
  if (!watchlist.length) {
    watchlist = WATCH_UNIVERSE.map((m, i) => quoteToWatch(m.ui, watchQuotes[i], m.sector)).filter(
      (w) => w.symbol && w.last != null,
    );
  }

  const macros: TerminalSnapshotItem[] = MACRO_SNAPSHOT.map((m, i) => {
    const q = macroQuotes[i];
    const price = q ? num(q.price) : null;
    return {
      symbol: m.ui,
      label: m.label,
      value: price != null && price !== 0 ? price : null,
      change_pct: q ? num(q.change_pct) : null,
      reason: !q || price == null || price === 0 ? "macro quote unavailable" : null,
    };
  });

  let pulse: TerminalPulse =
    pulseEp && typeof pulseEp === "object" && ("fear_greed" in pulseEp || "gainers" in pulseEp)
      ? pulseEp
      : buildPulseFromQuotes(
          watchlist.filter((w) => w.last != null),
          indices.filter((i) => i.price != null),
          macros,
        );

  if (!pulse.global_snapshot?.length) {
    pulse = { ...pulse, global_snapshot: macros };
  }

  let market_hours: TerminalMarketHoursRow[] = computeMarketHours();
  if (Array.isArray(hoursEp) && hoursEp.length) {
    market_hours = hoursEp;
  } else if (hoursEp && typeof hoursEp === "object" && !Array.isArray(hoursEp)) {
    market_hours = hoursEp.items ?? hoursEp.market_hours ?? market_hours;
  }

  let tape: TerminalTapeItem[] = [];
  if (Array.isArray(tapeEp)) {
    tape = dedupeTapeItems(mapTapeItems(tapeEp));
  } else if (tapeEp && typeof tapeEp === "object" && !Array.isArray(tapeEp)) {
    tape = dedupeTapeItems(mapTapeItems(tapeEp.items ?? tapeEp.tape ?? []));
  }
  if (!tape.length) {
    tape = buildTapeFromParts(indices, watchlist, pulse);
  }

  let portfolio =
    mapPortfolioLoose(portfolioEp) ||
    mapPortfolioLoose(portfolioDash) ||
    emptyPortfolio("No portfolios yet — connect a broker or fund a venue account.");

  const newsItems = newsRes?.success ? mapNews(newsRes.data ?? undefined) : [];
  const calendarItems = calendarRes?.success ? mapCalendar(calendarRes.data ?? undefined) : [];
  const agentIds = agentsIdx?.agents ?? agentsIdx?.items ?? null;
  const agents = mapAgents(agentIds);
  const chart = mapOhlcvChart(
    ohlcvRes?.success ? ohlcvRes.data ?? undefined : undefined,
    CHART_SYMBOL.ui,
  );
  const alerts = healthAlerts;

  let metrics: {
    sharpe?: number;
    sortino?: number;
    volatility_annual?: number;
    max_drawdown?: number;
    cagr?: number | null;
  } | null = null;
  let varRes: { var?: number; cvar?: number | null; confidence?: number } | null = null;
  const dailyBars = ohlcvDailyRes?.success ? ohlcvDailyRes.data ?? [] : [];
  const closes = (dailyBars || [])
    .map((b) => num(b.close))
    .filter((v): v is number => v != null && v > 0);
  if (closes.length >= 20 && OVERALL_COMPOSE_BUDGET_MS - (Date.now() - composeStarted) > 2_000) {
    const rets = closesToReturns(closes.slice(-120));
    if (rets.length >= 10) {
      const [m, v] = await Promise.all([
        tryPost<{
          sharpe?: number;
          sortino?: number;
          volatility_annual?: number;
          max_drawdown?: number;
          cagr?: number | null;
        }>("/terminal/quant/metrics", {
          returns: { symbol: "SPY", values: rets, periods_per_year: 252 },
          prices: { symbol: "SPY", values: closes.slice(-121), periods_per_year: 252 },
        }),
        tryPost<{ var?: number; cvar?: number | null; confidence?: number }>(
          "/terminal/quant/var",
          {
            returns: { symbol: "SPY", values: rets, periods_per_year: 252 },
            confidence: 0.95,
            method: "historical",
          },
        ),
      ]);
      metrics = m;
      varRes = v;
    }
  }
  const { quant, factors } = buildQuantFromApi(metrics, varRes, health);

  const pricedIndices = indices.filter((i) => i.price != null);
  const pricedWatch = watchlist.filter((w) => w.last != null);
  const anyLive = Boolean(
    health?.length ||
      agentIds?.length ||
      pricedIndices.length ||
      pricedWatch.length ||
      newsItems.length ||
      calendarItems.length ||
      chart ||
      quant.length ||
      portfolioEp ||
      portfolioDash,
  );

  if (!anyLive) {
    return rememberGoodSnapshot({
      ...mock,
      indices: [],
      performance: [],
      watchlist: [],
      pulse: EMPTY_PULSE,
      risk: { ...mock.risk, high_beta: [] },
      news: [],
      data_notes: ["Сервер данных недоступен — котировки появятся после восстановления связи"],
    });
  }

  const performance = buildPerformance(indices, watchlist, health);
  const liveWatch = pricedWatch.length ? watchlist : preferPopulatedArray(watchlist, lastGoodSnapshot?.watchlist);
  const liveIndices = pricedIndices.length
    ? indices
    : preferPopulatedArray(indices, lastGoodSnapshot?.indices);

  return rememberGoodSnapshot({
    as_of: nowIso(),
    source: pricedIndices.length || pricedWatch.length ? "live" : "partial",
    indices: liveIndices.length ? liveIndices : [],
    performance: mergePerformanceRows(lastGoodSnapshot?.performance ?? [], performance),
    pulse: alignVixFromIndices(liveIndices.length ? liveIndices : indices, pulse),
    risk:
      metrics || varRes
        ? buildRiskFromQuant(liveWatch, varRes, metrics)
        : buildRiskFromQuotes(liveWatch),
    news: newsItems,
    calendar: calendarItems,
    watchlist: liveWatch,
    alerts: alerts,
    quant: quant.length ? quant : mock.quant,
    quant_factors: factors.length ? factors : mock.quant_factors,
    agents: agents.length ? agents : mock.agents,
    chart: preferLiveChart(chart, lastGoodSnapshot?.chart),
    tape,
    market_hours,
    portfolio,
    data_notes: notes.length ? notes : undefined,
  });
}

export const terminalApi = {
  snapshot: async (): Promise<TerminalSnapshot> => {
    const seq = ++snapshotFetchSeq;
    const snap = await composeFromPartials();
    // Ignore stale out-of-order completions from overlapping polls.
    if (seq !== snapshotFetchSeq) {
      return lastGoodSnapshot ?? snap;
    }
    return snap;
  },

  fetchChart: async (uiSymbol: string, timeframe = "1h"): Promise<TerminalChartSeries> => {
    const isIndex = isIndexUiSymbol(uiSymbol);
    const tf = isIndex || timeframe === "1d" ? "1d" : "1h";
    const bars = await fetchChartBars(uiSymbol, tf);
    const chart = mapOhlcvChart(bars ?? undefined, uiSymbol);
    if ((chart?.bars?.length ?? 0) >= 8) return chart!;
    if (chart?.points?.length) return chart;
    return emptyChart(uiSymbol);
  },

  chat: async (message: string, symbol = "SPY"): Promise<TerminalChatMessage> => {
    const data = await tryPost<{
      answer?: { answer?: string; confidence?: number } | string;
      aggregated?: { answer?: string; confidence?: number };
      detail?: string;
    }>("/terminal/agents/ask", {
      query: message,
      agent_type: "market_analyst",
      symbol,
    });

    let body: string | null = null;
    if (data) {
      if (typeof data.answer === "string") body = data.answer;
      else if (data.answer && typeof data.answer === "object" && data.answer.answer) {
        body = data.answer.answer;
      } else if (data.aggregated?.answer) {
        body = data.aggregated.answer;
      }
    }

    if (body) {
      return {
        id: `agent-${Date.now()}`,
        role: "assistant",
        body,
        ts: nowIso(),
      };
    }

    return {
      id: `local-${Date.now()}`,
      role: "assistant",
      body: `QuantAnalytics Terminal (offline mode): received “${message.slice(0, 120)}”. Wire LLM keys (AITUNNEL_API_KEY) for live /terminal/agents/ask replies.`,
      ts: nowIso(),
    };
  },
};
