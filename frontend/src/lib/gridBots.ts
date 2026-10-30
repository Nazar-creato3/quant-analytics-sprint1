import api from "@/lib/api";

export interface GridBot {
  bot_id: string;
  ticker: string;
  lower_price: number;
  upper_price: number;
  grid_count: number;
  grid_type?: string;
  total_capital: number;
  is_active: boolean;
  is_paused: boolean;
  total_trades: number;
  realized_pnl: number;
  unrealized_pnl: number;
  total_pnl: number;
  last_price: number | null;
  pending_orders: number;
  filled_orders: number;
  last_activity_at: string | null;
  session_pnl: number;
  executor_state?: string;
}

export interface GridLevel {
  price: number;
  side: string;
  status: string;
  quantity: number;
  fill_price: number | null;
  pnl: number;
  barrier_id?: string | null;
  barrier_status?: string;
}

export interface GridEvent {
  ts: string;
  type: string;
  message: string;
  price: number | null;
  pnl_delta: number | null;
  side: string | null;
}

export interface GridActivity {
  bot_id: string;
  ticker: string;
  last_price: number | null;
  last_activity_at: string | null;
  session_pnl: number;
  total_pnl: number;
  realized_pnl: number;
  unrealized_pnl: number;
  pending_levels: GridLevel[];
  recent_fills: GridLevel[];
  grid_levels: GridLevel[];
  recent_events: GridEvent[];
  pnl_snapshots: { ts: string; total_pnl: number }[];
  paper_trades: PaperTrade[];
  open_positions: OpenPosition[];
  pending_orders: number;
  filled_orders: number;
  lower_price: number;
  upper_price: number;
  grid_count: number | null;
  total_capital: number | null;
  is_active: boolean;
  is_paused: boolean;
  total_trades: number;
  executor_state?: string;
  circuit_breaker?: Record<string, unknown> | null;
  dca_state?: Record<string, unknown> | null;
  barrier_positions?: Record<string, unknown>[];
  grid_type?: string;
  trailing_enabled?: boolean;
}

export interface PaperTrade {
  id: string;
  ts: string;
  side: string;
  price: number;
  quantity: number;
  level_price: number;
  notional_usd: number;
  pnl: number;
}

export interface OpenPosition {
  bot_id: string;
  ticker: string;
  side: string;
  quantity: number;
  avg_entry: number;
  mark_price: number;
  notional_usd: number;
  unrealized_pnl: number;
}

export interface GridSuggest {
  ticker: string;
  current_price: number;
  lower_price: number;
  upper_price: number;
  stop_loss: number;
  take_profit: number;
  grid_count: number;
  grid_type?: string;
  realized_volatility?: number;
  volatility_regime?: string;
}

export interface AutoCalibrateResult {
  config: Record<string, unknown>;
  current_price: number;
  realized_volatility: number;
  volatility_regime: string;
  num_levels: number;
  grid_type: string;
}

export interface GridBacktestResult {
  total_return: number;
  sharpe: number;
  max_drawdown: number;
  n_trades: number;
  n_grid_cycles: number;
  total_fees: number;
  liquidation_events: number;
  equity_curve: number[];
  metadata: Record<string, unknown>;
}

export interface UpdateGridConfigBody {
  grid_count?: number;
  lower_price?: number;
  upper_price?: number;
  total_capital?: number;
}

export const gridBotsApi = {
  list: async (): Promise<GridBot[]> => {
    const { data } = await api.get("/grid");
    return data;
  },
  create: async (body: Record<string, unknown>): Promise<GridBot> => {
    const { data } = await api.post("/grid", body);
    return data;
  },
  suggest: async (ticker: string, opts?: { riskLevel?: string; totalCapital?: number }): Promise<GridSuggest> => {
    const { data } = await api.get<GridSuggest>(`/grid/suggest/${encodeURIComponent(ticker)}`, {
      params: {
        risk_level: opts?.riskLevel ?? "medium",
        total_capital: opts?.totalCapital ?? 10000,
      },
    });
    return data;
  },
  autoCalibrate: async (body: {
    ticker: string;
    total_capital: number;
    risk_level?: string;
    grid_type?: string;
  }): Promise<AutoCalibrateResult> => {
    const { data } = await api.post<AutoCalibrateResult>("/grid/auto-calibrate", body);
    return data;
  },
  backtest: async (body: Record<string, unknown>): Promise<GridBacktestResult> => {
    const { data } = await api.post<GridBacktestResult>("/grid/backtest", body);
    return data;
  },
  updateConfig: async (botId: string, body: UpdateGridConfigBody): Promise<GridBot> => {
    const { data } = await api.patch(`/grid/${botId}`, body);
    return data;
  },
  pause: async (botId: string): Promise<GridBot> => {
    const { data } = await api.post(`/grid/${botId}/pause`);
    return data;
  },
  resume: async (botId: string): Promise<GridBot> => {
    const { data } = await api.post(`/grid/${botId}/resume`);
    return data;
  },
  stop: async (botId: string): Promise<GridBot> => {
    const { data } = await api.post(`/grid/${botId}/stop`);
    return data;
  },
  remove: async (botId: string): Promise<void> => {
    await api.delete(`/grid/${botId}`);
  },
  updatePrice: async (botId: string, price: number): Promise<GridBot> => {
    const { data } = await api.post(`/grid/${botId}/price`, null, { params: { price } });
    return data;
  },
  activity: async (botId: string): Promise<GridActivity> => {
    const { data } = await api.get(`/grid/bots/${botId}/activity`);
    return data;
  },
};

export function formatRelativeTime(iso: string | null): string {
  if (!iso) return "—";
  const diff = Date.now() - new Date(iso).getTime();
  if (diff < 60_000) return "только что";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)} мин назад`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)} ч назад`;
  return new Date(iso).toLocaleString("ru-RU");
}

export const GRID_RECONFIG_WARNING =
  "После первой сделки диапазон, шаг и капитал изменить нельзя. Остановите бота и создайте новый.";
