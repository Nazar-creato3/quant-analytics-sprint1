"use client";

import { clsx } from "clsx";
import {
  AlertTriangle, Ban, Database, Loader2, Lock, Radio,
} from "lucide-react";
import type { ReasonCode } from "./types";

const REASON_META: Record<
  ReasonCode,
  { icon: React.ElementType; accent: string; border: string }
> = {
  "no-data":       { icon: Database,      accent: "text-qa-muted",  border: "border-qa-border-strong" },
  "pipeline-off":  { icon: Radio,         accent: "text-terminal-accent", border: "border-terminal-accent/40" },
  permissions:     { icon: Lock,          accent: "text-terminal-accent", border: "border-terminal-accent/40" },
  error:           { icon: AlertTriangle, accent: "text-terminal-down",   border: "border-terminal-down/40" },
  loading:         { icon: Loader2,       accent: "text-qa-muted",  border: "border-qa-border-strong" },
  "no-symbol":     { icon: Ban,           accent: "text-qa-muted",  border: "border-qa-border-strong" },
};

interface ReasonStatePanelProps {
  code: ReasonCode;
  title: string;
  detail?: string;
  action?: React.ReactNode;
  compact?: boolean;
  className?: string;
}

export function ReasonState({
  code,
  title,
  detail,
  action,
  compact = false,
  className,
}: ReasonStatePanelProps) {
  const meta = REASON_META[code];
  const Icon = meta.icon;
  const spinning = code === "loading";

  return (
    <div
      className={clsx(
        "flex flex-col items-center justify-center text-center border border-dashed rounded-lg",
        meta.border,
        compact ? "py-6 px-4 gap-2" : "py-10 px-6 gap-3",
        className,
      )}
    >
      <div className={clsx(
        "rounded-lg bg-cockpit-panel flex items-center justify-center",
        compact ? "w-8 h-8" : "w-10 h-10",
      )}>
        <Icon
          size={compact ? 16 : 20}
          className={clsx(meta.accent, spinning && "animate-spin")}
        />
      </div>
      <div>
        <p className={clsx("font-semibold text-qa-text", compact ? "text-xs" : "text-sm")}>
          {title}
        </p>
        {detail && (
          <p className={clsx("text-qa-muted mt-1 max-w-xs", compact ? "text-[10px]" : "text-xs")}>
            {detail}
          </p>
        )}
      </div>
      {action}
    </div>
  );
}
