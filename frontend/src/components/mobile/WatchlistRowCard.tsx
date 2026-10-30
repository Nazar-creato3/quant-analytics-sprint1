"use client";

import { clsx } from "clsx";

export interface WatchlistRowCardProps {
  symbol: string;
  price?: number | null;
  changePct?: number | null;
  volume?: number | null;
  freshnessLabel?: string | null;
  label?: string;
  selected?: boolean;
  onSelect?: (symbol: string) => void;
}

export function quoteChangeTone(
  changePct: number | null | undefined,
): "up" | "down" | "flat" {
  if (changePct == null || !Number.isFinite(changePct) || changePct === 0) return "flat";
  return changePct > 0 ? "up" : "down";
}

function fmtPrice(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return v >= 1000 ? v.toFixed(0) : v.toFixed(2);
}

function fmtPct(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  const sign = v > 0 ? "+" : "";
  return `${sign}${v.toFixed(2)}%`;
}

export function WatchlistRowCard({
  symbol,
  price,
  changePct,
  freshnessLabel,
  label,
  selected,
  onSelect,
}: WatchlistRowCardProps) {
  const tone = quoteChangeTone(changePct);

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onSelect?.(symbol)}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect?.(symbol);
        }
      }}
      className={clsx(
        "w-full text-left rounded-xl border p-3 min-h-[44px] transition-colors cursor-pointer",
        selected
          ? "border-terminal-accent/50 bg-terminal-accent/5"
          : "border-cockpit-border bg-cockpit-panel-raised active:bg-cockpit-panel",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0">
          <p className="font-mono font-semibold text-white text-base">{symbol}</p>
          {label && <p className="text-[10px] text-qa-muted truncate">{label}</p>}
        </div>
        <div className="text-right shrink-0">
          <p className="font-mono tabular-nums text-white text-base">{fmtPrice(price)}</p>
          <p data-testid="quote-freshness" className="text-[10px] text-qa-muted">
            {freshnessLabel?.trim() || "нет данных"}
          </p>
          <p
            className={clsx(
              "font-mono tabular-nums text-sm",
              tone === "up" && "text-terminal-up",
              tone === "down" && "text-terminal-down",
              tone === "flat" && "text-qa-muted",
            )}
          >
            {fmtPct(changePct)}
          </p>
        </div>
      </div>
    </div>
  );
}
