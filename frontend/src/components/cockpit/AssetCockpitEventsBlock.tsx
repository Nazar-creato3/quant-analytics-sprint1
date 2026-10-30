"use client";

import { format, parseISO, differenceInCalendarDays } from "date-fns";
import { ru } from "date-fns/locale";
import { clsx } from "clsx";
import { Calendar, TrendingUp } from "lucide-react";
import type { CockpitMacroEvent } from "@/types";
import { CockpitPanelHeader } from "@/components/operator/CockpitPanelHeader";

const EVENT_TYPE_RU: Record<string, string> = {
  earnings: "Отчётность",
  dividend: "Дивиденды",
  macro: "Макро",
  rebalance: "Ребаланс",
};

const EVENT_ACCENT: Record<string, string> = {
  earnings: "border-l-amber-500",
  dividend: "border-l-terminal-up",
  macro: "border-l-terminal-accent",
};

function formatEventDate(iso: string): string {
  try {
    return format(parseISO(iso), "d MMMM yyyy", { locale: ru });
  } catch {
    return iso;
  }
}

function daysUntilLabel(iso: string): string {
  try {
    const days = differenceInCalendarDays(parseISO(iso), new Date());
    if (days < 0) return `${Math.abs(days)} дн. назад`;
    if (days === 0) return "сегодня";
    if (days === 1) return "завтра";
    return `через ${days} дн.`;
  } catch {
    return "";
  }
}

interface AssetCockpitEventsBlockProps {
  events: CockpitMacroEvent[];
  className?: string;
}

export function AssetCockpitEventsBlock({ events, className }: AssetCockpitEventsBlockProps) {
  const sorted = [...events].sort((a, b) => {
    if (!a.scheduled_at) return 1;
    if (!b.scheduled_at) return -1;
    return a.scheduled_at.localeCompare(b.scheduled_at);
  });

  return (
    <div className={clsx("cockpit-panel flex flex-col", className)}>
      <CockpitPanelHeader title="Macro / Earnings" subtitle="Близость событий" />
      <div className="p-2 space-y-2">
        {sorted.length === 0 ? (
          <p className="text-xs text-qa-muted px-2 py-4">Нет предстоящих событий</p>
        ) : (
          sorted.map((event) => {
            const typeRu = EVENT_TYPE_RU[event.event_type] ?? event.event_type;
            const accent = EVENT_ACCENT[event.event_type] ?? "border-l-qa-border";
            return (
              <div
                key={event.id}
                className={clsx(
                  "cockpit-feed-item border-l-2 pl-2.5 text-[11px]",
                  accent,
                  event.is_stub && "border-dashed opacity-80",
                )}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="text-qa-text leading-snug font-medium">{event.title}</div>
                    <div className="flex flex-wrap items-center gap-x-2 gap-y-1 mt-1.5 text-[10px] text-qa-muted">
                      <span className="inline-flex items-center gap-1 uppercase tracking-wide">
                        <TrendingUp size={10} />
                        {typeRu}
                      </span>
                      {event.is_stub && (
                        <span className="text-terminal-accent/80">· ожидаются данные</span>
                      )}
                    </div>
                  </div>
                  {event.scheduled_at && (
                    <div className="text-right shrink-0">
                      <time
                        className="block text-[10px] font-mono tabular-nums text-qa-text"
                        dateTime={event.scheduled_at}
                      >
                        {formatEventDate(event.scheduled_at)}
                      </time>
                      <span className="inline-flex items-center gap-1 text-[9px] text-terminal-accent/90 mt-0.5">
                        <Calendar size={9} />
                        {daysUntilLabel(event.scheduled_at)}
                      </span>
                    </div>
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
