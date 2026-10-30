"use client";

import { useQuery } from "@tanstack/react-query";
import { useHealth } from "@/hooks";
import Link from "next/link";
import { portfolioApi, tradingAccountsApi } from "@/lib/api";
import { useAuth } from "@/hooks";
import { useProductContext } from "@/contexts/ProductContext";
import { clsx } from "clsx";
import { Clock } from "lucide-react";
import { StatusDot } from "./StatusDot";
import type { StatusLevel } from "./types";
import { RegimeIndicator } from "@/components/market/RegimeIndicator";
import { useActiveTicker } from "@/contexts/ActiveTickerContext";
import { useBrokerAutoSync } from "@/hooks/useBrokerAutoSync";

/** User-facing copy — no English ops jargon (AUD-K-03). */
export const CONTROL_BAR_COPY = {
  paper: "Учебный",
  live: "Боевой",
  db: "База",
  cache: "Кэш",
  venue: "Площадка",
} as const;

function brokerLevel(status: string | undefined): StatusLevel {
  if (!status) return "none";
  if (status === "ok" || status === "connected") return "ok";
  if (status === "degraded") return "caution";
  return "block";
}

export function ControlBar() {
  const { activeTicker } = useActiveTicker();
  const { data: health } = useHealth();
  const { data: riskStatus } = useQuery({
    queryKey: ["portfolio-risk-status"],
    queryFn: portfolioApi.riskStatus,
    refetchInterval: 30_000,
    staleTime: 15_000,
  });

  const { mode, setMode } = useProductContext();
  const brokerSync = useBrokerAutoSync(mode);
  const { isStaff } = useAuth();
  const { data: accounts } = useQuery({
    queryKey: ["trading-accounts"],
    queryFn: tradingAccountsApi.list,
    staleTime: 60_000,
  });
  const connected = (accounts?.venues || []).flatMap((v) =>
    (v.connected_accounts || []).length ? [v.title || v.venue] : [],
  );
  const dbOk = health?.db === "ok";
  const redisOk = health?.redis === "ok";
  const dataFresh: StatusLevel = dbOk && redisOk ? "ok" : dbOk || redisOk ? "caution" : "block";

  const risk: StatusLevel = riskStatus?.level ?? "none";

  const switchTo = (next: "paper" | "live") => {
    if (next === mode) return;
    if (next === "live" && !window.confirm("Перейти в боевой режим? Будут показаны ваши реальные брокерские счета, а одобренные манёвры и заявки будут уходить брокеру (если реальная торговля включена).")) return;
    setMode(next);
  };

  return (
    <div className="cockpit-control-bar shrink-0">
      <div className="flex items-center gap-2">
        <span className="cockpit-label">Режим</span>
        <div
          className="flex rounded-md overflow-hidden border border-cockpit-border"
          role="group"
          aria-label="Учебный или боевой режим"
          data-testid="paper-live-badge"
        >
          <button
            type="button"
            onClick={() => switchTo("paper")}
            aria-pressed={mode === "paper"}
            title="Учебный: сделки исполняются на виртуальном счёте"
            className={clsx(
              "px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide transition-colors",
              mode === "paper" ? "bg-cockpit-panel-raised text-terminal-up" : "bg-cockpit-panel text-qa-muted hover:text-qa-text",
            )}
          >
            {CONTROL_BAR_COPY.paper}
          </button>
          <button
            type="button"
            onClick={() => switchTo("live")}
            aria-pressed={mode === "live"}
            title="Боевой: ваши реальные брокерские счета"
            className={clsx(
              "px-2.5 py-1 text-[10px] font-bold uppercase tracking-wide border-l border-cockpit-border transition-colors",
              mode === "live" ? "bg-qa-danger-bg text-terminal-down" : "bg-cockpit-panel text-qa-muted hover:text-qa-text",
            )}
          >
            {CONTROL_BAR_COPY.live}
          </button>
        </div>
      </div>

      <div className="cockpit-divider" />

      <div className="flex items-center gap-2">
        <span className="cockpit-label">Брокер</span>
        {connected.length ? (
          <StatusDot
            level={brokerSync.syncing ? "caution" : "ok"}
            label={brokerSync.syncing ? "загружаю счёт…" : connected.slice(0, 2).join(", ")}
          />
        ) : (
          <Link href="/account#brokers" className="text-[11px] text-terminal-accent hover:underline" data-testid="connect-broker-link">
            Подключить счёт
          </Link>
        )}
      </div>

      {isStaff ? (
        <>
          <div className="cockpit-divider" />
          <div className="flex items-center gap-3">
            <span className="cockpit-label">Система</span>
            <StatusDot level={brokerLevel(health?.db)} label={CONTROL_BAR_COPY.db} />
            <StatusDot level={brokerLevel(health?.redis)} label={CONTROL_BAR_COPY.cache} />
          </div>
        </>
      ) : null}

      <div className="cockpit-divider" />

      <div className="flex items-center gap-2">
        <span className="cockpit-label">Риск</span>
        <StatusDot
          level={risk}
          label={riskStatus?.label ?? (risk === "ok" ? "В норме" : risk === "caution" ? "Внимание" : risk === "block" ? "Лимит" : "—")}
          explanation={riskStatus?.explanation}
          contributingFactors={riskStatus?.contributing_factors}
        />
      </div>

      <div className="cockpit-divider" />

      <div className="flex items-center gap-2 min-w-0">
        <RegimeIndicator ticker={activeTicker} compact />
      </div>

      <div className="cockpit-divider" />

      <div className="flex items-center gap-2">
        <Clock size={11} className="text-qa-muted" />
        <span className="cockpit-label">Данные</span>
        <StatusDot
          level={dataFresh}
          label={dataFresh === "ok" ? "Свежие" : dataFresh === "caution" ? "Частично" : "Устарели"}
        />
      </div>
    </div>
  );
}
