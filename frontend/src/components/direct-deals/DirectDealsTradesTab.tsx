"use client";

import { useQuery } from "@tanstack/react-query";
import { clsx } from "clsx";
import { Loader2 } from "lucide-react";
import { ordersApi } from "@/lib/api";
import { DIRECT_DEALS_POLL } from "@/lib/direct-deals";
import { useVisiblePollInterval } from "@/hooks/useDocumentVisibility";

interface DirectDealsTradesTabProps {
  ticker: string;
}

function formatMsk(iso: string): string {
  return new Intl.DateTimeFormat("ru-RU", {
    timeZone: "Europe/Moscow",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(new Date(iso));
}

function fmtPrice(price: number): string {
  if (price >= 1000) return price.toFixed(2);
  if (price >= 1) return price.toFixed(4);
  return price.toFixed(6);
}

function fmtSize(size: number): string {
  if (size >= 1_000_000) return `${(size / 1_000_000).toFixed(2)}M`;
  if (size >= 1_000) return `${(size / 1_000).toFixed(2)}K`;
  if (size >= 1) return size.toFixed(2);
  return size.toFixed(6);
}

/** Live trades tape from venue APIs (Binance / Alpaca / MOEX ISS). */
export function DirectDealsTradesTab({ ticker }: DirectDealsTradesTabProps) {
  const pollMs = useVisiblePollInterval(DIRECT_DEALS_POLL.orderBookMs);

  const { data: trades, isLoading, isFetched, isError } = useQuery({
    queryKey: ["recent-trades", ticker],
    queryFn: () => ordersApi.recentTrades(ticker, 80),
    enabled: Boolean(ticker),
    refetchInterval: pollMs,
    staleTime: 250,
    placeholderData: (prev) => prev,
  });

  if (isLoading && !trades) {
    return (
      <div className="flex items-center justify-center gap-2 py-12 text-xs text-qa-muted">
        <Loader2 size={14} className="animate-spin" /> Загрузка ленты…
      </div>
    );
  }

  const rows = trades ?? [];
  const source = rows[0]?.source ?? "—";

  return (
    <div className="flex flex-col min-h-0 h-full">
      <div className="px-3 py-2 border-b border-qa-border text-[10px] text-qa-muted uppercase tracking-wide shrink-0">
        Последние сделки · {source} · MSK
      </div>
      <div className="flex-1 overflow-y-auto min-h-0">
        {isError ? (
          <p className="text-xs text-qa-warning text-center py-10">Ошибка загрузки ленты</p>
        ) : isFetched && rows.length === 0 ? (
          <p className="text-xs text-qa-muted text-center py-10">
            Нет сделок за текущую сессию
          </p>
        ) : (
          <table className="w-full text-[11px] font-mono tabular-nums">
            <thead className="sticky top-0 bg-qa-panel text-qa-muted text-[9px] uppercase">
              <tr>
                <th className="text-left px-3 py-1.5 font-medium">Время (MSK)</th>
                <th className="text-right px-3 py-1.5 font-medium">Цена</th>
                <th className="text-right px-3 py-1.5 font-medium">Объём</th>
                <th className="text-right px-3 py-1.5 font-medium">Стор.</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const side = row.side ?? "buy";
                return (
                  <tr
                    key={row.id}
                    className="border-t border-qa-border/50 hover:bg-[var(--qa-hover)]"
                  >
                    <td className="px-3 py-1 text-qa-muted">{formatMsk(row.ts)}</td>
                    <td
                      className={clsx(
                        "px-3 py-1 text-right",
                        side === "buy" ? "text-terminal-up" : "text-terminal-down",
                      )}
                    >
                      {fmtPrice(row.price)}
                    </td>
                    <td className="px-3 py-1 text-right text-qa-text">{fmtSize(row.size)}</td>
                    <td
                      className={clsx(
                        "px-3 py-1 text-right uppercase text-[10px]",
                        side === "buy" ? "text-terminal-up" : "text-terminal-down",
                      )}
                    >
                      {side === "buy" ? "B" : "S"}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
