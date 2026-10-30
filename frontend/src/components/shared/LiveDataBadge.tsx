"use client";

import { clsx } from "clsx";
import { Radio, WifiOff, AlertTriangle } from "lucide-react";
import type { DataFreshnessState } from "@/hooks/useLiveFreshness";

interface LiveDataBadgeProps {
  state: DataFreshnessState;
  ageLabel?: string;
  wsConnected?: boolean;
  compact?: boolean;
  showIcon?: boolean;
  className?: string;
}

const LABELS: Record<DataFreshnessState, string> = {
  live: "Данные свежие",
  stale: "Данные устарели",
  disconnected: "Нет связи",
  unknown: "Подключение…",
};

export function LiveDataBadge({
  state,
  ageLabel,
  wsConnected,
  compact = false,
  showIcon = true,
  className,
}: LiveDataBadgeProps) {
  const Icon =
    state === "live" ? Radio : state === "stale" ? AlertTriangle : WifiOff;

  const title =
    state === "live"
      ? wsConnected
        ? "Live data via WebSocket"
        : "Live data via polling"
      : state === "stale"
        ? `Last update ${ageLabel ?? "unknown"}`
        : state === "disconnected"
          ? "No recent updates — check connection"
          : "Waiting for first update";

  return (
    <span
      className={clsx(
        "inline-flex items-center gap-1 shrink-0 font-mono uppercase tracking-wide",
        compact ? "text-[9px]" : "text-[10px]",
        state === "live" && "text-terminal-up",
        state === "stale" && "text-yellow-500",
        state === "disconnected" && "text-red-400",
        state === "unknown" && "text-terminal-muted",
        className,
      )}
      title={title}
    >
      {showIcon && <Icon size={compact ? 8 : 9} aria-hidden />}
      {!compact && <span>{LABELS[state]}</span>}
      {ageLabel && (state !== "unknown") && (
        <span className={clsx(
          "normal-case tracking-normal opacity-80",
          state === "live" && "text-terminal-up/70",
        )}>
          ({ageLabel})
        </span>
      )}
      {wsConnected && state === "live" && (
        <span className="text-terminal-up/60 normal-case tracking-normal" title="Поток котировок подключён">· поток</span>
      )}
    </span>
  );
}
