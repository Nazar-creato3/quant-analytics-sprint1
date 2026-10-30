"use client";

import { clsx } from "clsx";

interface MachineTranslationBadgeProps {
  className?: string;
}

export function MachineTranslationBadge({ className }: MachineTranslationBadgeProps) {
  return (
    <span
      className={clsx(
        "text-[9px] uppercase shrink-0 px-1.5 py-0.5 rounded border font-medium",
        "text-qa-muted bg-qa-panel-secondary/60 border-qa-border-strong/60",
        className,
      )}
      title="Текст переведён автоматически"
    >
      Автоперевод
    </span>
  );
}
