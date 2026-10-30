"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { clsx } from "clsx";

/** One analytics block on the Portfolio page: title, one-line meaning, content. */
export function Block({
  title,
  hint,
  children,
  method,
  testId,
  className,
}: {
  title: string;
  hint?: string;
  children: ReactNode;
  method?: string;
  testId?: string;
  className?: string;
}) {
  return (
    <section className={clsx("card p-5 space-y-4", className)} data-testid={testId}>
      <header className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold text-qa-text">{title}</h2>
          {hint ? <p className="text-xs text-qa-muted mt-1 max-w-2xl">{hint}</p> : null}
        </div>
        {method ? (
          <Link href={method} className="shrink-0 text-[11px] text-qa-muted hover:text-terminal-accent underline-offset-2 hover:underline">
            Как считается
          </Link>
        ) : null}
      </header>
      {children}
    </section>
  );
}

export function Stat({
  label,
  value,
  sub,
  tone = "neutral",
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  tone?: "neutral" | "up" | "down" | "accent";
}) {
  return (
    <div className="rounded-lg border border-cockpit-border bg-cockpit-panel-raised px-4 py-3 min-w-0">
      <p className="text-[11px] uppercase tracking-wide text-qa-muted">{label}</p>
      <p
        className={clsx(
          "mt-1 text-lg font-semibold tabular-nums truncate",
          tone === "up" && "text-terminal-up",
          tone === "down" && "text-terminal-down",
          tone === "accent" && "text-terminal-accent",
          tone === "neutral" && "text-qa-text",
        )}
      >
        {value}
      </p>
      {sub ? <p className="mt-0.5 text-[11px] text-qa-muted">{sub}</p> : null}
    </div>
  );
}

export function StatGrid({ children }: { children: ReactNode }) {
  return <div className="grid gap-3 grid-cols-2 lg:grid-cols-4">{children}</div>;
}

/** Shown instead of a block's numbers when the portfolio gives nothing to compute. */
export function Quiet({ children }: { children: ReactNode }) {
  return <p className="text-xs text-qa-muted">{children}</p>;
}

export const rub = (v: unknown, digits = 0): string | null => {
  const n = Number(v);
  if (v == null || v === "" || !Number.isFinite(n)) return null;
  return `${n.toLocaleString("ru-RU", { maximumFractionDigits: digits, minimumFractionDigits: digits })} ₽`;
};

export const pct = (v: unknown, digits = 1, fraction = true): string | null => {
  const n = Number(v);
  if (v == null || v === "" || !Number.isFinite(n)) return null;
  return `${(fraction ? n * 100 : n).toLocaleString("ru-RU", { maximumFractionDigits: digits, minimumFractionDigits: digits })}%`;
};

export const DASH = "—";
