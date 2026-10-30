"use client";

import { clsx } from "clsx";
import { useFeedFreshness } from "@/hooks/useFeedFreshness";

export function FeedFreshnessIndicators({ compact = false }: { compact?: boolean }) {
  const { stale, label, isLoading } = useFeedFreshness();

  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] uppercase tracking-wide",
        compact ? "text-[9px]" : "",
        isLoading && "text-qa-muted bg-qa-panel-secondary/40",
        !isLoading && stale && "text-amber-300 bg-amber-500/10 border border-amber-500/30",
        !isLoading && !stale && "text-emerald-300 bg-emerald-500/10 border border-emerald-500/20",
      )}
      title="Свежесть котировок Terminal Market"
    >
      <span
        className={clsx(
          "h-1.5 w-1.5 rounded-full",
          isLoading ? "bg-qa-muted" : stale ? "bg-amber-400" : "bg-emerald-400",
        )}
      />
      {isLoading ? "…" : label}
    </span>
  );
}
