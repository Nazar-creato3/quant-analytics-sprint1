"use client";

import { clsx } from "clsx";

interface RangeSliderProps {
  label: string;
  low: number | null;
  high: number | null;
  current: number | null;
  className?: string;
}

function clampPct(pct: number): number {
  return Math.min(100, Math.max(0, pct));
}

/** Horizontal range bar with marker for current price position. */
export function DirectDealsRangeSlider({
  label,
  low,
  high,
  current,
  className,
}: RangeSliderProps) {
  const valid =
    low != null &&
    high != null &&
    current != null &&
    Number.isFinite(low) &&
    Number.isFinite(high) &&
    Number.isFinite(current) &&
    high > low;

  const pct = valid ? clampPct(((current - low) / (high - low)) * 100) : 50;

  return (
    <div className={clsx("space-y-1", className)}>
      <div className="flex items-center justify-between text-[10px]">
        <span className="text-qa-muted uppercase tracking-wide">{label}</span>
        {valid ? (
          <span className="text-qa-text font-mono tabular-nums">
            {low.toLocaleString(undefined, { maximumFractionDigits: 2 })}
            {" – "}
            {high.toLocaleString(undefined, { maximumFractionDigits: 2 })}
          </span>
        ) : (
          <span className="text-qa-muted">—</span>
        )}
      </div>
      <div className="relative h-1.5 rounded-full bg-qa-panel-secondary border border-qa-border overflow-hidden">
        {valid && (
          <>
            <div
              className="absolute inset-y-0 left-0 bg-gradient-to-r from-terminal-down/30 via-qa-muted/20 to-terminal-up/30"
              style={{ width: "100%" }}
            />
            <div
              className="absolute top-1/2 -translate-y-1/2 w-2 h-2 rounded-full border border-terminal-accent transition-[left] duration-300 ease-out"
              style={{
                left: `calc(${pct}% - 4px)`,
                backgroundColor: "var(--qa-slider-thumb)",
                boxShadow: "0 0 6px var(--qa-slider-glow)",
              }}
              title={`${current.toLocaleString(undefined, { maximumFractionDigits: 2 })} (${pct.toFixed(1)}%)`}
            />
          </>
        )}
      </div>
    </div>
  );
}
