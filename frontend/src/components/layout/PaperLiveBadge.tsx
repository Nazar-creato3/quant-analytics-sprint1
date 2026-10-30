"use client";

import { clsx } from "clsx";
import { useProductContext } from "@/contexts/ProductContext";

export function PaperLiveBadge() {
  const { mode, setMode } = useProductContext();
  return (
    <div
      className="flex items-center gap-1 rounded-md border border-cockpit-border px-1 py-0.5"
      data-testid="paper-live-badge"
      role="group"
      aria-label="Режим paper или live"
    >
      <button
        type="button"
        onClick={() => setMode("paper")}
        className={clsx(
          "px-1.5 py-0.5 rounded text-[10px] uppercase tracking-wide min-h-[28px]",
          mode === "paper"
            ? "bg-terminal-accent/20 text-terminal-accent border border-terminal-accent/50"
            : "text-qa-muted",
        )}
        aria-pressed={mode === "paper"}
      >
        учебный
      </button>
      <button
        type="button"
        onClick={() => setMode("live")}
        className={clsx(
          "px-1.5 py-0.5 rounded text-[10px] uppercase tracking-wide min-h-[28px]",
          mode === "live" ? "bg-red-900/40 text-red-300 border border-red-500/60" : "text-qa-muted",
        )}
        aria-pressed={mode === "live"}
      >
        боевой
      </button>
    </div>
  );
}

export function LiveConfirm({
  onConfirm,
  children,
}: {
  onConfirm: () => void;
  children: React.ReactNode;
}) {
  const { mode } = useProductContext();
  if (mode !== "live") {
    return (
      <button type="button" className="text-left" onClick={onConfirm}>
        {children}
      </button>
    );
  }
  return (
    <button
      type="button"
      className="text-left"
      onClick={() => {
        if (window.confirm("Действие в режиме live. Подтвердите ещё раз.")) {
          onConfirm();
        }
      }}
    >
      {children}
    </button>
  );
}
