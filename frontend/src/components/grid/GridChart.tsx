"use client";

import { useMemo } from "react";
import { LineStyle } from "lightweight-charts";
import { LightweightChartLoader } from "@/components/charts/LightweightChartLoader";
import { useChartColors } from "@/hooks/useChartColors";
import type { GridLevel } from "@/lib/gridBots";

interface GridChartProps {
  ticker: string;
  lowerPrice: number;
  upperPrice: number;
  gridLevels: GridLevel[];
  currentPrice?: number | null;
  height?: number;
}

/** Grid bot chart with price levels overlaid on Lightweight Charts. */
export function GridChart({
  ticker,
  lowerPrice,
  upperPrice,
  gridLevels,
  currentPrice,
  height = 320,
}: GridChartProps) {
  const colors = useChartColors();
  const entryPrice = currentPrice ?? (lowerPrice + upperPrice) / 2;

  const levelOverlays = useMemo(() => {
    const unique = new Map<number, GridLevel>();
    for (const l of gridLevels) {
      unique.set(l.price, l);
    }
    return [...unique.values()].sort((a, b) => a.price - b.price);
  }, [gridLevels]);

  return (
    <div className="relative">
      <LightweightChartLoader
        ticker={ticker}
        height={height}
        showVolume={false}
        limit={90}
      />
      {/* Level legend */}
      <div className="mt-2 flex flex-wrap gap-1 max-h-20 overflow-y-auto">
        <span
          className="text-[10px] font-mono px-1.5 py-0.5 rounded border border-terminal-accent/40 text-terminal-accent"
        >
          L ${lowerPrice.toFixed(2)}
        </span>
        {levelOverlays.slice(0, 12).map((l) => (
          <span
            key={`${l.side}-${l.price}`}
            className="text-[10px] font-mono px-1.5 py-0.5 rounded border tabular-nums"
            style={{
              borderColor: l.side === "buy" ? colors.success : colors.danger,
              color: l.status === "filled"
                ? colors.success
                : l.side === "buy"
                  ? colors.success
                  : colors.danger,
              opacity: l.status === "filled" ? 1 : 0.7,
            }}
          >
            {l.side[0].toUpperCase()} ${l.price.toFixed(2)}
            {l.barrier_status && l.barrier_status !== "none" && l.barrier_status !== "active"
              ? ` [${l.barrier_status}]`
              : ""}
          </span>
        ))}
        <span
          className="text-[10px] font-mono px-1.5 py-0.5 rounded border border-terminal-accent/40 text-terminal-accent"
        >
          U ${upperPrice.toFixed(2)}
        </span>
      </div>
    </div>
  );
}

export { LineStyle };
