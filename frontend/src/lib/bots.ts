import api from "@/lib/api";

export type BotType = "grid" | "dca" | "momentum";
export type BotStatus = "active" | "paused" | "stopped";

export interface UnifiedBot {
  id: string;
  bot_type: BotType;
  symbol: string;
  status: BotStatus;
  params: Record<string, unknown>;
  total_trades: number;
  pnl: number;
  balance_allocated: number;
  created_at: string | null;
}

export interface CreateBotBody {
  bot_type: BotType;
  symbol: string;
  balance_allocated: number;
  params: Record<string, unknown>;
}

export const botsApi = {
  list: async (botType?: BotType | "all"): Promise<UnifiedBot[]> => {
    const params = botType && botType !== "all" ? { bot_type: botType } : undefined;
    const { data } = await api.get<UnifiedBot[]>("/bots", { params });
    return data;
  },
  create: async (body: CreateBotBody): Promise<UnifiedBot> => {
    const { data } = await api.post<UnifiedBot>("/bots", body);
    return data;
  },
  get: async (id: string): Promise<UnifiedBot> => {
    const { data } = await api.get<UnifiedBot>(`/bots/${id}`);
    return data;
  },
  patch: async (id: string, body: { status?: BotStatus; params?: Record<string, unknown> }): Promise<UnifiedBot> => {
    const { data } = await api.patch<UnifiedBot>(`/bots/${id}`, body);
    return data;
  },
  remove: async (id: string): Promise<void> => {
    await api.delete(`/bots/${id}`);
  },
};

export function compactParams(bot: UnifiedBot): string {
  const p = bot.params || {};
  if (bot.bot_type === "grid") {
    return `${p.lower_price ?? "—"}–${p.upper_price ?? "—"} / ${p.grid_count ?? "—"}`;
  }
  if (bot.bot_type === "dca") {
    const dip = typeof p.dip_pct === "number" ? `${(p.dip_pct * 100).toFixed(1)}%` : "—";
    return `int ${p.interval_ticks ?? "—"} · dd ${dip}`;
  }
  const thr = typeof p.entry_momentum_pct === "number" ? `${(p.entry_momentum_pct * 100).toFixed(1)}%` : "—";
  const size = typeof p.position_size_pct === "number" ? `${(p.position_size_pct * 100).toFixed(0)}%` : "—";
  return `thr ${thr} · size ${size}`;
}

export function formatUsd(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return `$${value.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}
