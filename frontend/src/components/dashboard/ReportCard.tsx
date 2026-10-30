"use client";

import { ManeuverReport, HealthStatus } from "@/types";
import { clsx } from "clsx";
import { format, formatDistanceToNow } from "date-fns";
import { ru } from "date-fns/locale";
import { Activity, Database, Server, Wifi, WifiOff } from "lucide-react";

// ── ReportCard ────────────────────────────────────────────────────────────────

interface ReportCardProps {
  report: ManeuverReport;
  isSelected: boolean;
  onClick: () => void;
}

export function ReportCard({ report, isSelected, onClick }: ReportCardProps) {
  const tradeable = report.maneuvers.filter(m => m.strategy_type !== "no_trade").length;
  const avgConf =
    report.maneuvers.length > 0
      ? report.maneuvers.reduce((s, m) => s + m.confidence, 0) / report.maneuvers.length
      : 0;

  const regimeColor: Record<string, string> = {
    bull: "text-terminal-up",
    bear: "text-terminal-down",
    volatile: "text-terminal-accent",
    sideways: "text-terminal-accent",
    unknown: "text-qa-muted",
  };

  return (
    <button
      onClick={onClick}
      className={clsx(
        "w-full text-left px-3 py-2.5 rounded-lg border transition-all",
        isSelected
          ? "bg-[var(--qa-active)] border-terminal-accent/50 "
          : "bg-qa-panel-secondary border-qa-border hover:border-qa-border-strong hover:bg-qa-panel-secondary/80"
      )}
    >
      <div className="flex items-center justify-between mb-1">
        <span className="text-xs font-mono text-qa-muted">
          {format(new Date(report.created_at), "dd MMM, HH:mm")}
        </span>
        <span className={clsx("text-xs font-semibold", regimeColor[report.regime || "unknown"])}>
          {report.regime || "—"}
        </span>
      </div>
      <div className="flex items-center justify-between">
        <span className="text-xs text-qa-muted">
          Торгуемых:{" "}
          <span className={clsx("font-semibold", tradeable > 5 ? "text-terminal-up" : "text-terminal-accent")}>
            {tradeable}/10
          </span>
        </span>
        <span className="text-xs text-qa-muted">
          Уверенность:{" "}
          <span className="text-qa-text font-semibold">{Math.round(avgConf * 100)}%</span>
        </span>
      </div>
      <div className="mt-1.5 flex flex-wrap gap-1">
        {report.watchlist.slice(0, 5).map(t => (
          <span key={t} className="text-[10px] font-mono text-terminal-accent bg-[var(--qa-active)] px-1.5 py-0.5 rounded">
            {t}
          </span>
        ))}
        {report.watchlist.length > 5 && (
          <span className="text-[10px] text-qa-muted">+{report.watchlist.length - 5}</span>
        )}
      </div>
    </button>
  );
}

// ── SystemStatus ──────────────────────────────────────────────────────────────

interface SystemStatusProps {
  health?: HealthStatus;
}

function StatusDot({ ok }: { ok: boolean }) {
  return (
    <span className={clsx(
      "inline-block w-1.5 h-1.5 rounded-full",
      ok ? "bg-terminal-up shadow-sm " : "bg-terminal-down"
    )} />
  );
}

export function SystemStatus({ health }: SystemStatusProps) {
  if (!health) {
    return (
      <div className="flex items-center gap-1.5 text-xs text-qa-muted">
        <Activity size={12} className="animate-pulse" />
        <span>Connecting…</span>
      </div>
    );
  }

  const dbOk = health.db === "ok";
  const redisOk = health.redis === "ok";
  const allOk = dbOk && redisOk;

  return (
    <div className="flex items-center gap-3 text-xs text-qa-muted bg-qa-panel-secondary border border-qa-border px-3 py-1.5 rounded-lg">
      <span className="flex items-center gap-1.5">
        <StatusDot ok={dbOk} />
        <Database size={11} />
        <span className={dbOk ? "text-qa-muted" : "text-terminal-down"}>DB</span>
      </span>
      <span className="flex items-center gap-1.5">
        <StatusDot ok={redisOk} />
        <Server size={11} />
        <span className={redisOk ? "text-qa-muted" : "text-terminal-down"}>Redis</span>
      </span>
      <span className="flex items-center gap-1.5 border-l border-qa-border pl-3">
        {allOk ? <Wifi size={11} className="text-terminal-up" /> : <WifiOff size={11} className="text-terminal-down" />}
        <span className={clsx(
          "font-semibold",
          health.trading_mode === "live" ? "text-terminal-down" : "text-terminal-up"
        )}>
          {health.trading_mode.toUpperCase()}
        </span>
      </span>
    </div>
  );
}
