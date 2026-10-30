"use client";

import type { ReactNode } from "react";
import { clsx } from "clsx";

export function TermPanel({
  title,
  children,
  className,
  actions,
  bodyClassName,
}: {
  title: string;
  children: ReactNode;
  className?: string;
  actions?: ReactNode;
  bodyClassName?: string;
}) {
  return (
    <section className={clsx("term-panel", className)}>
      <header className="term-panel-header">
        <span>{title}</span>
        {actions ? (
          <div className="flex items-center gap-1 text-terminal-muted normal-case tracking-normal font-medium">
            {actions}
          </div>
        ) : null}
      </header>
      <div className={clsx("flex-1 min-h-0 overflow-y-auto", bodyClassName)}>{children}</div>
    </section>
  );
}

export function fmtNum(n: number | null | undefined, digits = 2): string {
  if (n == null || !Number.isFinite(n)) return "—";
  return n.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

const LABEL_RU: Record<string, string> = {
  calm: "спокойно",
  moderate: "умеренно",
  elevated: "повышенно",
  high: "высокая",
  normal: "обычная",
  low: "низкая",
  unavailable: "нет данных",
  "no data": "нет данных",
  greed: "жадность",
  "extreme greed": "сильная жадность",
  fear: "страх",
  "extreme fear": "сильный страх",
  neutral: "нейтрально",
};

/** Russian label for status words that arrive in English from data sources. */
export function ruLabel(value: string | null | undefined): string {
  if (!value) return "";
  return LABEL_RU[value.trim().toLowerCase()] ?? value;
}

export function fmtPct(n: number | null | undefined, digits = 2): string {
  if (n == null || !Number.isFinite(n)) return "—";
  const sign = n > 0 ? "+" : "";
  return `${sign}${n.toFixed(digits)}%`;
}

export function changeClass(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "term-flat";
  if (n > 0.0001) return "term-up";
  if (n < -0.0001) return "term-down";
  return "term-flat";
}

export const TERMINAL_TZ = "Europe/Moscow";

export function fmtMskDateTime(iso: string, opts?: Intl.DateTimeFormatOptions): string {
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return "—";
  return new Date(t).toLocaleString("ru-RU", {
    timeZone: TERMINAL_TZ,
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    ...opts,
  });
}

export function fmtMskTime(date = new Date()): string {
  return date.toLocaleTimeString("ru-RU", {
    timeZone: TERMINAL_TZ,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}

export function relativeTime(iso: string, now = Date.now()): string {
  const t = Date.parse(iso);
  if (!Number.isFinite(t)) return "—";
  const sec = Math.max(0, Math.round((now - t) / 1000));
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h`;
  return `${Math.floor(sec / 86400)}d`;
}

export function fmtVol(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  if (v >= 1e9) return `${(v / 1e9).toFixed(1)}B`;
  if (v >= 1e6) return `${(v / 1e6).toFixed(1)}M`;
  if (v >= 1e3) return `${(v / 1e3).toFixed(1)}K`;
  return String(Math.round(v));
}

export function EmptyHint({ text }: { text: string }) {
  return <p className="p-2 text-[10px] text-terminal-muted leading-snug">{text}</p>;
}
