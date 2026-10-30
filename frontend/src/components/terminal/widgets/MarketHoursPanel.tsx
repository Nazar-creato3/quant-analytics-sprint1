"use client";

import { Zap } from "lucide-react";
import type { TerminalMarketHoursRow } from "@/types/terminal";
import { EmptyHint } from "../TermPanel";

function statusView(status: TerminalMarketHoursRow["status"]): {
  label: string;
  color: string;
  dot: string;
  underline?: boolean;
} {
  if (status === "open") return { label: "OPEN", color: "term-up", dot: "bg-[var(--terminal-up)]" };
  if (status === "pre") return { label: "PRE", color: "text-terminal-accent", dot: "bg-terminal-accent" };
  if (status === "post") return { label: "POST", color: "text-terminal-accent", dot: "bg-terminal-accent" };
  if (status === "holiday") return { label: "HOLIDAY", color: "term-flat", dot: "bg-terminal-muted" };
  return { label: "CLOSED", color: "term-down", dot: "bg-[var(--terminal-down)]", underline: true };
}

export function MarketHoursPanel({ rows }: { rows: TerminalMarketHoursRow[] }) {
  if (!rows.length) {
    return <EmptyHint text="Часы торгов недоступны." />;
  }

  return (
    <div>
      <div className="flex items-center gap-1.5 px-2 py-1 text-[9px] text-terminal-muted uppercase tracking-wider border-b border-terminal-border">
        <Zap size={10} className="text-terminal-accent" aria-hidden />
        <span>Session clock (local exchange)</span>
      </div>
      {rows.map((r) => {
        const s = statusView(r.status);
        return (
          <div key={r.id} className="term-row grid-cols-[1fr_auto] !py-1">
            <div className="min-w-0">
              <p className="text-terminal-text truncate">{r.exchange}</p>
              <p className="text-[8px] text-terminal-muted">
                {r.name ?? ""}
                {r.local_time ? ` · ${r.local_time}` : ""}
              </p>
            </div>
            <span className={`inline-flex items-center gap-1.5 text-[10px] font-bold uppercase ${s.color}`}>
              <span className={`w-1.5 h-1.5 rounded-full ${s.dot}`} aria-hidden />
              <span className={s.underline ? "underline decoration-[var(--terminal-down)] underline-offset-2" : undefined}>
                {s.label}
              </span>
            </span>
          </div>
        );
      })}
    </div>
  );
}
