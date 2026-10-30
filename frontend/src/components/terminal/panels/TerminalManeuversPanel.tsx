"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { maneuversApi } from "@/lib/api";
import { dedupeManeuvers } from "@/lib/maneuver-dedupe";

export function TerminalManeuversPanel({ symbol }: { symbol: string }) {
  const ticker = symbol.trim().toUpperCase();
  const { data } = useQuery({
    queryKey: ["maneuvers", "terminal", ticker],
    queryFn: () => maneuversApi.list({ ticker, page_size: 40 }),
    enabled: !!ticker,
    staleTime: 20_000,
  });

  const items = useMemo(() => {
    const raw = data?.items ?? [];
    const onlyTicker = raw.filter((m) => (m.ticker || "").toUpperCase() === ticker);
    return dedupeManeuvers(onlyTicker);
  }, [data?.items, ticker]);

  return (
    <div className="flex flex-col min-h-[280px]">
      <div className="flex items-center justify-between px-2 py-1 border-b border-terminal-border text-[10px]">
        <span className="text-terminal-muted">Maneuvers · {ticker} only</span>
      </div>
      <div className="p-2 space-y-1 max-h-[720px] overflow-y-auto">
        {items.length === 0 && (
          <p className="text-[11px] text-terminal-muted">Нет манёвров по {ticker}</p>
        )}
        {items.map((m) => (
          <div
            key={m.id}
            className="term-row !block space-y-0.5 border-b border-terminal-border/50 pb-1"
          >
            <div className="flex justify-between gap-2">
              <span className="font-mono text-[11px]">{m.ticker}</span>
              <span className="text-[10px] text-terminal-muted">{m.status}</span>
            </div>
            <p className="text-[10px] text-terminal-text">
              {m.direction} · conf {m.confidence != null ? `${(m.confidence * 100).toFixed(0)}%` : "—"}
            </p>
            {m.rationale ? (
              <p className="text-[10px] text-terminal-muted leading-snug">{m.rationale}</p>
            ) : null}
          </div>
        ))}
      </div>
      <p className="px-2 py-1 text-[9px] text-terminal-muted">
        Только {ticker}. Дубликаты с тем же обоснованием скрыты. Direct Deals — отдельный экран.
      </p>
    </div>
  );
}
