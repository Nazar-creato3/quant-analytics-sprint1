"use client";

import Link from "next/link";
import { clsx } from "clsx";
import type { AssetCockpitData } from "@/types";

const REGIME_STYLES: Record<string, string> = {
  BULL: "text-terminal-up border-terminal-up/40 bg-qa-success-bg/30",
  BEAR: "text-terminal-down border-terminal-down/40 bg-qa-danger-bg/30",
  RANGE: "text-terminal-accent border-terminal-accent/40 bg-[var(--qa-active)]",
  VOLATILE: "text-terminal-accent border-terminal-accent/40 bg-[var(--qa-active)]",
  UNKNOWN: "text-qa-muted border-qa-border-strong bg-qa-panel-secondary/50",
};

function formatPrice(value: number | null): string {
  if (value == null) return "—";
  if (value >= 1000) return `$${value.toLocaleString("en-US", { maximumFractionDigits: 2 })}`;
  if (value >= 1) return `$${value.toFixed(2)}`;
  return `$${value.toFixed(4)}`;
}

interface AssetCockpitHeaderProps {
  data: AssetCockpitData;
}

export function AssetCockpitHeader({ data }: AssetCockpitHeaderProps) {
  const positive = (data.change_pct ?? 0) >= 0;
  const regimeClass = REGIME_STYLES[data.regime_label] ?? REGIME_STYLES.UNKNOWN;

  return (
    <header className="cockpit-panel px-4 py-3 flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <div className="flex items-center gap-3 flex-wrap">
          <h1 className="text-lg font-bold font-mono text-white tracking-tight">{data.symbol}</h1>
          <span className={clsx("badge text-[10px] font-bold uppercase tracking-wider", regimeClass)}>
            {data.regime_label}
          </span>
          {data.category && (
            <span className="text-[10px] uppercase tracking-wider text-qa-muted">{data.category}</span>
          )}
        </div>
        <p className="text-[11px] text-qa-muted mt-1">{data.sector_relation}</p>
      </div>

      <div className="text-right shrink-0">
        <div className="flex items-baseline justify-end gap-2">
          <span className="text-2xl font-mono font-bold tabular-nums text-white">
            {formatPrice(data.price)}
          </span>
          <span className="text-[10px] uppercase text-qa-muted">/ {data.tradable_unit.replace("_", " ")}</span>
        </div>
        {data.change_pct != null && (
          <div
            className={clsx(
              "text-sm font-mono tabular-nums mt-0.5",
              positive ? "text-terminal-up" : "text-terminal-down",
            )}
          >
            {positive ? "+" : ""}
            {data.change_pct.toFixed(2)}%
          </div>
        )}
        {data.quote_source && (
          <div className="text-[10px] text-qa-muted mt-1 uppercase tracking-wide">{data.quote_source}</div>
        )}
      </div>

      <div className="w-full flex items-center gap-3 text-[10px] text-qa-muted border-t border-cockpit-border pt-2 mt-1">
        <Link href={`/operator/chart?symbol=${encodeURIComponent(data.symbol)}`} className="hover:text-qa-text">
          Operator chart →
        </Link>
        <span className="text-cockpit-border">|</span>
        <span>
          Spread {data.spread_bps.toFixed(1)} bps · Liquidity {data.liquidity_state}
        </span>
      </div>
    </header>
  );
}
