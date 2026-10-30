"use client";



import { clsx } from "clsx";

import { ThemeLogo } from "@/components/shared/ThemeLogo";

import { Loader2, Inbox } from "lucide-react";



// ── Skeleton ──────────────────────────────────────────────────────────────────



interface SkeletonProps {

  className?: string;

  lines?: number;

}



export function Skeleton({ className, lines = 1 }: SkeletonProps) {

  return (

    <div className="space-y-2">

      {Array.from({ length: lines }).map((_, i) => (

        <div

          key={i}

          className={clsx(

            "skeleton rounded",

            i === lines - 1 && lines > 1 ? "w-3/4" : "w-full",

            className ?? "h-4"

          )}

        />

      ))}

    </div>

  );

}



export function TableSkeleton({ rows = 5, cols = 6 }: { rows?: number; cols?: number }) {

  return (

    <>

      {Array.from({ length: rows }).map((_, i) => (

        <tr key={i} className="border-b border-qa-border/60">

          {Array.from({ length: cols }).map((_, j) => (

            <td key={j} className="px-3 py-3">

              <Skeleton className={clsx("h-3", j === 0 ? "w-8" : j === 1 ? "w-20" : "w-16")} />

            </td>

          ))}

        </tr>

      ))}

    </>

  );

}



// ── Spinner ───────────────────────────────────────────────────────────────────



export function Spinner({ size = 16, className }: { size?: number; className?: string }) {

  return (

    <Loader2

      size={size}

      className={clsx("animate-spin text-terminal-accent", className)}

    />

  );

}



export function FullPageSpinner() {

  return (

    <div className="fixed inset-0 bg-qa-bg flex items-center justify-center z-50">

      <div className="flex flex-col items-center gap-4">

        <ThemeLogo width={40} height={40} priority className="opacity-90" />

        <Spinner size={24} />

        <span className="text-xs text-qa-muted">Загрузка…</span>

      </div>

    </div>

  );

}



// ── Empty state ───────────────────────────────────────────────────────────────



interface EmptyStateProps {

  title: string;

  description?: string;

  icon?: React.ReactNode;

  action?: React.ReactNode;

}



export function EmptyState({ title, description, icon, action }: EmptyStateProps) {

  return (

    <div className="flex flex-col items-center justify-center py-16 text-center">

      <div className="w-12 h-12 rounded-lg bg-qa-panel-secondary border border-qa-border flex items-center justify-center mb-4">

        {icon ?? <Inbox size={20} className="text-qa-muted" />}

      </div>

      <h3 className="text-sm font-semibold text-qa-muted mb-1">{title}</h3>

      {description && (

        <p className="text-xs text-qa-muted max-w-xs mb-4">{description}</p>

      )}

      {action}

    </div>

  );

}



// ── Badge ─────────────────────────────────────────────────────────────────────



type BadgeVariant = "default" | "success" | "warning" | "danger" | "info" | "accent";



const BADGE_VARIANTS: Record<BadgeVariant, string> = {

  default: "text-qa-muted bg-qa-panel-secondary border-qa-border",

  success: "text-terminal-up badge-success",

  warning: "text-terminal-accent badge-accent",

  danger:  "text-terminal-down badge-danger",

  info:    "text-terminal-accent badge-accent",

  accent:  "text-terminal-accent badge-accent",

};



export function Badge({

  children,

  variant = "default",

  className,

}: {

  children: React.ReactNode;

  variant?: BadgeVariant;

  className?: string;

}) {

  return (

    <span className={clsx("badge", BADGE_VARIANTS[variant], className)}>

      {children}

    </span>

  );

}



// ── Stat card ─────────────────────────────────────────────────────────────────



export function StatCard({

  label,

  value,

  sub,

  trend,

  className,

}: {

  label: string;

  value: React.ReactNode;

  sub?: string;

  trend?: "up" | "down" | "neutral";

  className?: string;

}) {

  const trendColor =

    trend === "up" ? "text-terminal-up"

    : trend === "down" ? "text-terminal-down"

    : "text-qa-muted";



  return (

    <div className={clsx("stat-card", className)}>

      <div className="stat-label">{label}</div>

      <div className={clsx("stat-value mt-1", trendColor)}>{value}</div>

      {sub && <div className="text-xs text-qa-muted mt-0.5">{sub}</div>}

    </div>

  );

}



// ── Divider ───────────────────────────────────────────────────────────────────



export function Divider({ label }: { label?: string }) {

  if (!label) return <hr className="border-qa-border my-4" />;

  return (

    <div className="relative my-6">

      <hr className="border-qa-border" />

      <span className="absolute left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 bg-qa-bg px-3 text-xs text-qa-muted">

        {label}

      </span>

    </div>

  );

}



// ── Tooltip wrapper ───────────────────────────────────────────────────────────



export function Tooltip({ children, tip }: { children: React.ReactNode; tip: string }) {

  return (

    <div className="relative group inline-block">

      {children}

      <div className="qa-tooltip bottom-full left-1/2 -translate-x-1/2 mb-2">

        {tip}

      </div>

    </div>

  );

}

