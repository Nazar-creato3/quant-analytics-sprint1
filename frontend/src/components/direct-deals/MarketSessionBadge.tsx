"use client";

import { clsx } from "clsx";
import type { TerminalSessionStatus } from "@/types/terminal";

function resolveSession(
  session?: string | null,
  market?: string | null,
): { label: string; cls: string } | null {
  const v = (session || "").toLowerCase() as TerminalSessionStatus | string;
  if (v === "open") return { label: "OPEN", cls: "text-terminal-up border-terminal-up/40" };
  if (v === "pre") return { label: "PRE", cls: "text-terminal-accent border-terminal-accent/40" };
  if (v === "post") return { label: "POST", cls: "text-terminal-accent border-terminal-accent/40" };
  if (v === "closed") return { label: "CLOSED", cls: "text-terminal-down border-terminal-down/40" };
  if (v === "holiday") return { label: "HOL", cls: "text-qa-muted border-qa-border" };
  if (market?.toLowerCase().includes("crypto")) {
    return { label: "24/7", cls: "text-terminal-up border-terminal-up/40" };
  }
  return null;
}

/** Compact market session badge for Direct Deals quote header. */
export function MarketSessionBadge({
  session,
  market,
  className,
}: {
  session?: string | null;
  market?: string | null;
  className?: string;
}) {
  const badge = resolveSession(session, market);
  if (!badge) return null;
  return (
    <span
      className={clsx(
        "text-[10px] uppercase font-bold px-1.5 py-0.5 rounded border tabular-nums",
        badge.cls,
        className,
      )}
    >
      {badge.label}
    </span>
  );
}
