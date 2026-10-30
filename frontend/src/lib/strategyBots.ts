import api from "@/lib/api";

export interface StrategyBotSummary {
  bot_id: string;
  ticker: string;
  total_capital: number;
  is_active: boolean;
  is_paused: boolean;
  total_trades: number;
  realized_pnl: number;
  unrealized_pnl: number;
  total_pnl: number;
  last_price: number | null;
  last_activity_at: string | null;
  session_pnl: number;
  executor_state: string;
  entries_count: number;
  position_qty: number;
}

function makeBotsApi(prefix: "/dca" | "/momentum") {
  return {
    list: async (): Promise<StrategyBotSummary[]> => {
      const { data } = await api.get(prefix);
      return data;
    },
    create: async (body: Record<string, unknown>): Promise<StrategyBotSummary> => {
      const { data } = await api.post(prefix, body);
      return data;
    },
    pause: async (botId: string): Promise<StrategyBotSummary> => {
      const { data } = await api.post(`${prefix}/${botId}/pause`);
      return data;
    },
    resume: async (botId: string): Promise<StrategyBotSummary> => {
      const { data } = await api.post(`${prefix}/${botId}/resume`);
      return data;
    },
    stop: async (botId: string): Promise<StrategyBotSummary> => {
      const { data } = await api.post(`${prefix}/${botId}/stop`);
      return data;
    },
    remove: async (botId: string): Promise<void> => {
      await api.delete(`${prefix}/${botId}`);
    },
  };
}

export const dcaBotsApi = makeBotsApi("/dca");
export const momentumBotsApi = makeBotsApi("/momentum");
