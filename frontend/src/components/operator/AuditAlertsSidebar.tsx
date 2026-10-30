"use client";

import { useQuery } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import { clsx } from "clsx";
import { auditApi } from "@/lib/api";
import { StatusDot } from "./StatusDot";
import { ReasonState } from "./ReasonState";
import { CockpitPanelHeader } from "./CockpitPanelHeader";
import type { StatusLevel } from "./types";

function auditLevel(success: boolean): StatusLevel {
  return success ? "ok" : "block";
}

export function AuditAlertsSidebar({ enabled = true }: { enabled?: boolean }) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["audit-alerts-compact"],
    queryFn: () => auditApi.list({ page: 1, page_size: 12 }),
    refetchInterval: 45_000,
    enabled,
  });

  const logs = data?.items ?? [];

  return (
    <aside className="cockpit-sidebar w-56 shrink-0 flex flex-col overflow-hidden">
      <CockpitPanelHeader
        title="Audit / Alerts"
        badge={logs.length}
        href="/operator/audit"
      />

      <div className="flex-1 overflow-y-auto p-2 space-y-1">
        {isLoading ? (
          <ReasonState code="loading" title="Загрузка аудита…" compact />
        ) : error ? (
          <ReasonState
            code="permissions"
            title="Аудит недоступен"
            detail={
              (error as { response?: { status?: number } })?.response?.status === 403
                ? "Нет прав доступа"
                : "API offline или ошибка сети"
            }
            compact
          />
        ) : logs.length === 0 ? (
          <ReasonState
            code="no-data"
            title="Записей нет"
            detail="Audit log пуст — события появятся после действий в системе"
            compact
          />
        ) : (
          logs.map(log => (
            <div key={log.id} className="cockpit-feed-item">
              <div className="flex items-center justify-between gap-1 mb-0.5">
                <span className="text-[10px] font-mono text-qa-muted truncate">
                  {log.action}
                </span>
                <StatusDot level={auditLevel(log.success)} />
              </div>
              {log.resource_type && (
                <p className="text-[10px] text-qa-muted truncate">
                  {log.resource_type}
                  {log.resource_id ? ` · ${log.resource_id.slice(0, 8)}…` : ""}
                </p>
              )}
              <p className="text-[10px] text-qa-muted mt-0.5 tabular-nums">
                {format(parseISO(log.timestamp), "HH:mm · dd.MM")}
              </p>
              {!log.success && log.error && (
                <p className={clsx("text-[10px] text-terminal-down/80 mt-0.5 line-clamp-1")}>
                  {log.error}
                </p>
              )}
            </div>
          ))
        )}
      </div>
    </aside>
  );
}
