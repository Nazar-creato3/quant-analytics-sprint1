"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "react-hot-toast";
import { Plus, Pause, Play, Square, Trash2 } from "lucide-react";
import { Spinner, Badge, EmptyState } from "@/components/ui";
import {
  dcaBotsApi,
  momentumBotsApi,
  type StrategyBotSummary,
} from "@/lib/strategyBots";

type BotKind = "dca" | "momentum";

const LABELS: Record<BotKind, { title: string; create: string }> = {
  dca: {
    title: "DCA Bots",
    create: "Создать DCA-бота (усреднение по интервалу/просадке)",
  },
  momentum: {
    title: "Momentum Bots",
    create: "Создать momentum-бота (вход по импульсу цены)",
  },
};

function apiFor(kind: BotKind) {
  return kind === "dca" ? dcaBotsApi : momentumBotsApi;
}

function fmtUsd(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `$${v.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

export function StrategyBotsPanel({ kind }: { kind: BotKind }) {
  const qc = useQueryClient();
  const api = apiFor(kind);
  const [ticker, setTicker] = useState("BTCUSDT");
  const [capital, setCapital] = useState("10000");
  const [price, setPrice] = useState("50000");

  const { data: bots = [], isLoading } = useQuery({
    queryKey: ["strategy-bots", kind],
    queryFn: () => api.list(),
  });

  const createMutation = useMutation({
    mutationFn: () =>
      api.create({
        ticker: ticker.trim().toUpperCase(),
        total_capital: Number(capital),
        current_price: Number(price),
        order_size_usd: kind === "dca" ? 500 : undefined,
        max_entries: kind === "dca" ? 10 : undefined,
        interval_ticks: kind === "dca" ? 5 : undefined,
        dip_pct: kind === "dca" ? 0.02 : undefined,
        take_profit_pct: kind === "dca" ? 0.05 : kind === "momentum" ? 0.06 : undefined,
        lookback_ticks: kind === "momentum" ? 20 : undefined,
        entry_momentum_pct: kind === "momentum" ? 0.03 : undefined,
        stop_loss_pct: kind === "momentum" ? 0.04 : undefined,
        position_size_pct: kind === "momentum" ? 0.5 : undefined,
      }),
    onSuccess: () => {
      toast.success("Бот создан");
      qc.invalidateQueries({ queryKey: ["strategy-bots", kind] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  return (
    <div className="space-y-4">
      <div className="cockpit-panel p-4 space-y-3">
        <div className="text-sm font-semibold">{LABELS[kind].create}</div>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-2">
          <input className="cockpit-input" value={ticker} onChange={(e) => setTicker(e.target.value)} placeholder="Ticker" />
          <input className="cockpit-input" value={capital} onChange={(e) => setCapital(e.target.value)} placeholder="Capital USD" />
          <input className="cockpit-input" value={price} onChange={(e) => setPrice(e.target.value)} placeholder="Current price" />
          <button type="button" className="cockpit-action-btn text-terminal-up" disabled={createMutation.isPending} onClick={() => createMutation.mutate()}>
            <Plus size={14} /> Создать
          </button>
        </div>
      </div>

      {isLoading ? (
        <div className="flex justify-center py-12"><Spinner /></div>
      ) : bots.length === 0 ? (
        <EmptyState title="Нет ботов" description="Создайте первого бота выше." />
      ) : (
        <div className="grid gap-3">
          {bots.map((bot: StrategyBotSummary) => (
            <BotRow key={bot.bot_id} bot={bot} kind={kind} />
          ))}
        </div>
      )}
    </div>
  );
}

function BotRow({ bot, kind }: { bot: StrategyBotSummary; kind: BotKind }) {
  const qc = useQueryClient();
  const api = apiFor(kind);
  const mutate = (fn: "pause" | "resume" | "stop" | "remove") =>
    api[fn](bot.bot_id)
      .then(() => qc.invalidateQueries({ queryKey: ["strategy-bots", kind] }))
      .catch((e: Error) => toast.error(e.message));

  return (
    <div className="cockpit-panel p-4 flex flex-wrap items-center justify-between gap-3">
      <div>
        <div className="flex items-center gap-2">
          <span className="font-mono font-semibold">{bot.ticker}</span>
          <Badge variant={bot.is_active ? "success" : "default"}>{bot.executor_state}</Badge>
          {bot.is_paused && <Badge variant="warning">на паузе</Badge>}
        </div>
        <div className="text-xs text-qa-muted mt-1">
          PnL {fmtUsd(bot.total_pnl)} · trades {bot.total_trades} · entries {bot.entries_count}
        </div>
      </div>
      <div className="flex gap-2">
        {bot.is_paused ? (
          <button type="button" className="cockpit-action-btn" onClick={() => mutate("resume")}><Play size={12} /></button>
        ) : (
          <button type="button" className="cockpit-action-btn" onClick={() => mutate("pause")}><Pause size={12} /></button>
        )}
        <button type="button" className="cockpit-action-btn" onClick={() => mutate("stop")}><Square size={12} /></button>
        <button type="button" className="cockpit-action-btn text-terminal-down" onClick={() => mutate("remove")}><Trash2 size={12} /></button>
      </div>
    </div>
  );
}
