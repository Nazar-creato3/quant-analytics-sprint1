"use client";

import { clsx } from "clsx";
import { CandlestickChart, LineChart } from "lucide-react";

export type ChartDisplayType = "candlestick" | "line";

export function ChartTypeToggle({
  value,
  onChange,
  className,
}: {
  value: ChartDisplayType;
  onChange: (next: ChartDisplayType) => void;
  className?: string;
}) {
  return (
    <div className={clsx("inline-flex items-center gap-1 text-[10px] font-mono uppercase", className)}>
      <button
        type="button"
        title="Свечи"
        aria-pressed={value === "candlestick"}
        onClick={() => onChange("candlestick")}
        className={clsx(
          "p-1 rounded transition-colors",
          value === "candlestick"
            ? "text-terminal-accent bg-[var(--qa-active)] border border-terminal-accent/40"
            : "text-qa-muted hover:text-qa-text border border-transparent",
        )}
      >
        <CandlestickChart size={12} strokeWidth={2.25} />
      </button>
      <span className="text-qa-muted select-none">/</span>
      <button
        type="button"
        title="Линия"
        aria-pressed={value === "line"}
        onClick={() => onChange("line")}
        className={clsx(
          "p-1 rounded transition-colors",
          value === "line"
            ? "text-terminal-accent bg-[var(--qa-active)] border border-terminal-accent/40"
            : "text-qa-muted hover:text-qa-text border border-transparent",
        )}
      >
        <LineChart size={12} strokeWidth={2.25} />
      </button>
    </div>
  );
}
