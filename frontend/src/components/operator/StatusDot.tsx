"use client";

import { useEffect, useRef, useState } from "react";
import { clsx } from "clsx";
import type { StatusLevel } from "./types";

const LEVEL_STYLES: Record<StatusLevel, string> = {
  ok:      "bg-status-ok",
  caution: "bg-status-caution",
  block:   "bg-status-block",
  none:    "bg-status-none",
};

interface StatusDotProps {
  level: StatusLevel;
  label?: string;
  pulse?: boolean;
  className?: string;
  /** When set, dot becomes clickable and shows a popover with risk explanation. */
  explanation?: string;
  contributingFactors?: string[];
}

export function StatusDot({
  level,
  label,
  pulse,
  className,
  explanation,
  contributingFactors,
}: StatusDotProps) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLSpanElement>(null);
  const hasDetail = Boolean(explanation);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  const dot = (
    <span
      className={clsx(
        "w-2 h-2 rounded-full shrink-0",
        LEVEL_STYLES[level],
        pulse && level === "ok" && "animate-pulse",
        hasDetail && "cursor-pointer ring-1 ring-transparent hover:ring-qa-border-strong",
      )}
      aria-hidden={!hasDetail}
    />
  );

  return (
    <span ref={rootRef} className={clsx("relative inline-flex items-center gap-1.5", className)}>
      {hasDetail ? (
        <button
          type="button"
          className="inline-flex items-center justify-center gap-1.5 bg-transparent border-0 min-h-6 min-w-6 px-1 cursor-pointer text-left"
          aria-label={label ? `${label}: подробнее о риске` : "Подробнее о риске"}
          aria-expanded={open}
          onClick={() => setOpen((v) => !v)}
        >
          {dot}
          {label && <span className="text-[10px] text-qa-muted underline decoration-dotted underline-offset-2">{label}</span>}
        </button>
      ) : (
        <>
          {dot}
          {label && <span className="text-[10px] text-qa-muted">{label}</span>}
        </>
      )}

      {hasDetail && open && (
        <div
          role="dialog"
          aria-label="Объяснение риска"
          className="absolute left-0 top-full z-50 mt-2 w-72 rounded-md border border-cockpit-border bg-cockpit-panel-raised p-3"
        >
          <p className="text-[11px] leading-relaxed text-qa-text">{explanation}</p>
          {contributingFactors && contributingFactors.length > 0 && (
            <ul className="mt-2 space-y-1 border-t border-cockpit-border pt-2">
              {contributingFactors.map((factor) => (
                <li key={factor} className="text-[10px] leading-snug text-qa-muted before:content-['•'] before:mr-1.5">
                  {factor}
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </span>
  );
}
