"use client";

import { clsx } from "clsx";
import type { TerminalTapeItem } from "@/types/terminal";
import { changeClass, fmtNum, fmtPct } from "../TermPanel";

export function RunningTape({
  items,
  focusSymbol,
  onFocus,
}: {
  items: TerminalTapeItem[];
  focusSymbol?: string | null;
  onFocus?: (symbol: string) => void;
}) {
  const quoteItems = items.filter((item) => item.kind !== "headline");
  if (!quoteItems.length) {
    return (
      <div className="term-tape border-b border-terminal-border px-2 py-1 text-[10px] text-terminal-muted">
        Tape idle — waiting for indices / movers
      </div>
    );
  }

  const doubled = [...quoteItems, ...quoteItems];

  return (
    <div className="term-tape border-b border-terminal-border bg-terminal-surface overflow-hidden relative">
      <div className="term-tape-track flex items-center gap-6 whitespace-nowrap py-1 will-change-transform">
        {doubled.map((item, idx) => {
          const clickable = Boolean(item.symbol && onFocus);
          return (
            <button
              key={`${item.id}-${idx}`}
              type="button"
              disabled={!clickable}
              onClick={() => item.symbol && onFocus?.(item.symbol)}
              className={clsx(
                "inline-flex items-center gap-1.5 text-[10px] font-mono shrink-0 px-1",
                clickable && "hover:text-terminal-accent cursor-pointer",
                !clickable && "cursor-default",
                focusSymbol && item.symbol === focusSymbol && "text-terminal-accent",
              )}
            >
              <>
                <span className="text-terminal-text font-semibold">{item.label}</span>
                {item.value != null && (
                  <span className="text-terminal-muted">{fmtNum(item.value, item.label === "VIX" ? 2 : 2)}</span>
                )}
                <span className={changeClass(item.change_pct)}>{fmtPct(item.change_pct)}</span>
              </>
              <span className="text-terminal-border">|</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
