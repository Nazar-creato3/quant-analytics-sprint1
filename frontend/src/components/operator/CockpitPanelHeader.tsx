"use client";

import Link from "next/link";
import { ChevronRight } from "lucide-react";
import { clsx } from "clsx";

interface CockpitPanelHeaderProps {
  title: React.ReactNode;
  badge?: string | number;
  href?: string;
  subtitle?: string;
  action?: React.ReactNode;
  className?: string;
}

export function CockpitPanelHeader({
  title,
  badge,
  href,
  subtitle,
  action,
  className,
}: CockpitPanelHeaderProps) {
  const titleBlock = (
    <div className="flex items-center gap-2 min-w-0">
      <span className="min-w-0">{title}</span>
      {badge != null && (
        <span className="text-[10px] text-terminal-accent font-normal tabular-nums shrink-0">
          {badge}
        </span>
      )}
      {subtitle && (
        <span className="text-[10px] text-qa-muted font-normal truncate">
          {subtitle}
        </span>
      )}
    </div>
  );

  const actionBlock = (
    <div
      className="flex items-center gap-2 shrink-0"
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => e.stopPropagation()}
    >
      {action}
      {href && (
        <span className="text-[10px] text-qa-muted hover:text-qa-text flex items-center gap-0.5 font-normal">
          <ChevronRight size={12} />
        </span>
      )}
    </div>
  );

  if (href) {
    return (
      <div className={clsx("cockpit-panel-header", className)}>
        <Link
          href={href}
          className="flex items-center gap-2 min-w-0 flex-1 hover:bg-cockpit-panel/60 -m-1 p-1 rounded transition-colors"
        >
          {titleBlock}
        </Link>
        {actionBlock}
      </div>
    );
  }

  return (
    <div className={clsx("cockpit-panel-header", className)}>
      {titleBlock}
      {actionBlock}
    </div>
  );
}
