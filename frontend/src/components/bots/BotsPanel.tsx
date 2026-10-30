"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "react-hot-toast";
import Link from "next/link";
import { Plus, Trash2 } from "lucide-react";
import { clsx } from "clsx";
import { Badge, EmptyState, Spinner } from "@/components/ui";
import {
  botsApi,
  compactParams,
  formatUsd,
  type BotType,
  type UnifiedBot,
} from "@/lib/bots";

const TYPE_TABS: { id: BotType; label: string }[] = [
  { id: "grid", label: "Сетка" },
  { id: "dca", label: "Усреднение" },
  { id: "momentum", label: "Импульс" },
];

const FILTERS: { id: "all" | BotType; label: string }[] = [
  { id: "all", label: "Все" },
  ...TYPE_TABS,
];

const TYPE_LABEL: Record<BotType, string> = {
  grid: "Сетка",
  dca: "Усреднение",
  momentum: "Импульс",
};

const STATUS_LABEL: Record<UnifiedBot["status"], string> = {
  active: "работает",
  paused: "на паузе",
  stopped: "остановлен",
};

function statusVariant(status: UnifiedBot["status"]): "success" | "warning" | "default" {
  if (status === "active") return "success";
  if (status === "paused") return "warning";
  return "default";
}

export function BotsPanel() {
  const qc = useQueryClient();
  const [createType, setCreateType] = useState<BotType>("grid");
  const [listFilter, setListFilter] = useState<"all" | BotType>("all");
  const [symbol, setSymbol] = useState("BTCUSDT");
  const [capital, setCapital] = useState("10000");
  const [lower, setLower] = useState("45000");
  const [upper, setUpper] = useState("55000");
  const [gridCount, setGridCount] = useState("10");
  const [interval, setInterval] = useState("5");
  const [drawdown, setDrawdown] = useState("2");
  const [threshold, setThreshold] = useState("3");
  const [size, setSize] = useState("50");

  const { data: bots = [], isLoading } = useQuery({
    queryKey: ["unified-bots"],
    queryFn: () => botsApi.list(),
  });

  const stats = useMemo(() => {
    const active = bots.filter((bot) => bot.status === "active").length;
    const trades = bots.reduce((sum, bot) => sum + (bot.total_trades || 0), 0);
    const pnl = bots.reduce((sum, bot) => sum + (bot.pnl || 0), 0);
    return { active, trades, pnl, total: bots.length };
  }, [bots]);

  const visible = useMemo(() => {
    const rows = listFilter === "all" ? bots : bots.filter((bot) => bot.bot_type === listFilter);
    return [...rows].sort((a, b) => a.bot_type.localeCompare(b.bot_type) || a.symbol.localeCompare(b.symbol));
  }, [bots, listFilter]);

  const createMutation = useMutation({
    mutationFn: () => {
      const params: Record<string, unknown> =
        createType === "grid"
          ? {
              lower_price: Number(lower),
              upper_price: Number(upper),
              grid_count: Number(gridCount),
            }
          : createType === "dca"
            ? {
                interval_ticks: Number(interval),
                dip_pct: Number(drawdown) / 100,
              }
            : {
                entry_momentum_pct: Number(threshold) / 100,
                position_size_pct: Number(size) / 100,
              };
      return botsApi.create({
        bot_type: createType,
        symbol: symbol.trim().toUpperCase(),
        balance_allocated: Number(capital),
        params,
      });
    },
    onSuccess: () => {
      toast.success("Бот создан");
      qc.invalidateQueries({ queryKey: ["unified-bots"] });
    },
    onError: () => toast.error("Не удалось создать бота"),
  });

  return (
    <div className="space-y-4">
      <div className="rounded-md border border-sky-500/40 bg-sky-500/10 px-3 py-2.5 text-xs text-qa-text/90 leading-relaxed space-y-1.5">
        <p className="font-semibold text-sky-300">Где основной робот</p>
        <p>
          Сетку, DCA и уровни собирайте на{" "}
          <Link href="/" className="text-terminal-accent underline underline-offset-2">
            терминале
          </Link>
          : тикер → панель <span className="text-sky-300 font-semibold">«Робот»</span> над
          графиком → уровни на свечах. Здесь — отдельные боты сетки, усреднения и импульса.
        </p>
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatCard label="Активные" value={String(stats.active)} />
        <StatCard label="Сделок" value={String(stats.trades)} />
        <StatCard label="P&L всего" value={formatUsd(stats.pnl)} />
        <StatCard label="Ботов всего" value={String(stats.total)} />
      </div>

      <div className="cockpit-panel p-4 space-y-3">
        <div className="flex flex-wrap gap-1.5">
          {TYPE_TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              onClick={() => setCreateType(tab.id)}
              className={clsx(
                "px-2.5 py-1.5 rounded-md text-xs min-h-[36px] transition-colors",
                createType === tab.id
                  ? "text-terminal-accent bg-[var(--qa-active)] border border-terminal-accent/40"
                  : "text-qa-muted hover:text-qa-text hover:bg-[var(--qa-hover)] border border-transparent",
              )}
            >
              {tab.label}
            </button>
          ))}
        </div>
        <div className="text-sm font-semibold">
          {createType === "grid" && "Создать сеточного бота"}
          {createType === "dca" && "Создать бота усреднения"}
          {createType === "momentum" && "Создать импульсного бота"}
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-5 gap-3">
          <label className="space-y-1">
            <span className="text-[10px] uppercase tracking-wide text-qa-muted">Тикер</span>
            <input className="cockpit-input" value={symbol} onChange={(e) => setSymbol(e.target.value)} placeholder="BTCUSDT" />
          </label>
          <label className="space-y-1">
            <span className="text-[10px] uppercase tracking-wide text-qa-muted">Баланс, $</span>
            <input className="cockpit-input" value={capital} onChange={(e) => setCapital(e.target.value)} placeholder="10000" />
          </label>
          {createType === "grid" && (
            <>
              <label className="space-y-1">
                <span className="text-[10px] uppercase tracking-wide text-qa-muted">Низ</span>
                <input className="cockpit-input" value={lower} onChange={(e) => setLower(e.target.value)} placeholder="45000" />
              </label>
              <label className="space-y-1">
                <span className="text-[10px] uppercase tracking-wide text-qa-muted">Верх</span>
                <input className="cockpit-input" value={upper} onChange={(e) => setUpper(e.target.value)} placeholder="55000" />
              </label>
              <label className="space-y-1">
                <span className="text-[10px] uppercase tracking-wide text-qa-muted">Уровней</span>
                <input className="cockpit-input" value={gridCount} onChange={(e) => setGridCount(e.target.value)} placeholder="10" />
              </label>
            </>
          )}
          {createType === "dca" && (
            <>
              <label className="space-y-1">
                <span className="text-[10px] uppercase tracking-wide text-qa-muted">Интервал тиков</span>
                <input className="cockpit-input" value={interval} onChange={(e) => setInterval(e.target.value)} placeholder="5" />
              </label>
              <label className="space-y-1">
                <span className="text-[10px] uppercase tracking-wide text-qa-muted">Просадка %</span>
                <input className="cockpit-input" value={drawdown} onChange={(e) => setDrawdown(e.target.value)} placeholder="2" />
              </label>
            </>
          )}
          {createType === "momentum" && (
            <>
              <label className="space-y-1">
                <span className="text-[10px] uppercase tracking-wide text-qa-muted">Порог %</span>
                <input className="cockpit-input" value={threshold} onChange={(e) => setThreshold(e.target.value)} placeholder="3" />
              </label>
              <label className="space-y-1">
                <span className="text-[10px] uppercase tracking-wide text-qa-muted">Размер %</span>
                <input className="cockpit-input" value={size} onChange={(e) => setSize(e.target.value)} placeholder="50" />
              </label>
            </>
          )}
          <div className="flex items-end">
            <button
              type="button"
              className="btn-primary w-full justify-center min-h-[38px]"
              disabled={createMutation.isPending}
              onClick={() => createMutation.mutate()}
            >
              <Plus size={14} /> Создать
            </button>
          </div>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-xs text-qa-muted">Фильтр</span>
        {FILTERS.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => setListFilter(item.id)}
            className={clsx(
              "px-2 py-1 rounded-md text-xs min-h-[32px] transition-colors",
              listFilter === item.id
                ? "text-terminal-accent bg-[var(--qa-active)] border border-terminal-accent/40"
                : "text-qa-muted hover:text-qa-text hover:bg-[var(--qa-hover)] border border-transparent",
            )}
          >
            {item.label}
          </button>
        ))}
      </div>

      {isLoading ? (
        <div className="flex justify-center py-12"><Spinner /></div>
      ) : visible.length === 0 ? (
        <EmptyState title="Пока нет ботов" description="Создайте первого бота в форме выше." />
      ) : (
        <div className="cockpit-panel p-4 overflow-auto">
          <table className="w-full text-xs font-mono">
            <thead>
              <tr className="text-qa-muted border-b border-cockpit-border">
                <th className="text-left py-1.5">Тип</th>
                <th className="text-left py-1.5">Инструмент</th>
                <th className="text-left py-1.5">Параметры</th>
                <th className="text-left py-1.5">Состояние</th>
                <th className="text-right py-1.5">Сделки</th>
                <th className="text-right py-1.5">Результат</th>
                <th className="text-right py-1.5">Баланс</th>
                <th className="text-right py-1.5" />
              </tr>
            </thead>
            <tbody>
              {visible.map((bot) => (
                <BotTableRow key={bot.id} bot={bot} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="cockpit-panel p-4">
      <div className="text-[10px] uppercase text-qa-muted tracking-wide">{label}</div>
      <div className="font-mono font-semibold mt-1">{value}</div>
    </div>
  );
}

function BotTableRow({ bot }: { bot: UnifiedBot }) {
  const qc = useQueryClient();
  const mutate = (status?: UnifiedBot["status"]) => {
    const action = status
      ? botsApi.patch(bot.id, { status })
      : botsApi.remove(bot.id);
    action
      .then(() => qc.invalidateQueries({ queryKey: ["unified-bots"] }))
      .catch(() => toast.error("Не удалось изменить бота"));
  };

  return (
    <tr className="border-b border-cockpit-border/50">
      <td className="py-2 pr-2">
        <div className="flex items-center gap-1">
          <Badge>{TYPE_LABEL[bot.bot_type]}</Badge>
          {(bot.bot_type === "grid" || bot.bot_type === "dca") && (
            <span className="text-[9px] uppercase tracking-wide text-amber-400" title="Устаревший способ. Соберите заново на терминале.">
              Устар.
            </span>
          )}
        </div>
      </td>
      <td className="py-2 pr-2 font-semibold">{bot.symbol}</td>
      <td className="py-2 pr-2 text-qa-muted">{compactParams(bot)}</td>
      <td className="py-2 pr-2">
        <Badge variant={statusVariant(bot.status)}>{STATUS_LABEL[bot.status]}</Badge>
      </td>
      <td className="py-2 pr-2 text-right">{bot.total_trades}</td>
      <td className="py-2 pr-2 text-right">{formatUsd(bot.pnl)}</td>
      <td className="py-2 pr-2 text-right">{formatUsd(bot.balance_allocated)}</td>
      <td className="py-2 text-right">
        <div className="inline-flex gap-1">
          {bot.status !== "active" ? (
            <button type="button" className="cockpit-action-btn" onClick={() => mutate("active")}>Старт</button>
          ) : (
            <button type="button" className="cockpit-action-btn" onClick={() => mutate("paused")}>Пауза</button>
          )}
          {bot.status !== "stopped" && (
            <button type="button" className="cockpit-action-btn" onClick={() => mutate("stopped")}>Стоп</button>
          )}
          <button type="button" className="cockpit-action-btn text-terminal-down" onClick={() => mutate()}>
            <Trash2 size={12} />
          </button>
        </div>
      </td>
    </tr>
  );
}
