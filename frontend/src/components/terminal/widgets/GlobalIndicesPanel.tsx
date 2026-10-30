"use client";

import { clsx } from "clsx";
import type { TerminalIndexRow, TerminalSessionStatus } from "@/types/terminal";
import { EmptyHint, changeClass, fmtNum, fmtPct } from "../TermPanel";
import { fmtPrice } from "@/lib/formatPrice";

function sessionBadge(s?: string | null) {
  const v = (s || "").toLowerCase() as TerminalSessionStatus | string;
  if (v === "open") return { label: "OPEN", cls: "term-up" };
  if (v === "pre") return { label: "PRE", cls: "text-terminal-accent" };
  if (v === "post") return { label: "POST", cls: "text-terminal-accent" };
  if (v === "closed") return { label: "CLOSED", cls: "term-down" };
  if (v === "holiday") return { label: "HOL", cls: "term-flat" };
  return null;
}

export function GlobalIndicesPanel({
  rows,
  focusSymbol,
  onFocus,
}: {
  rows: TerminalIndexRow[];
  focusSymbol?: string | null;
  onFocus?: (symbol: string) => void;
}) {
  if (!rows.length) {
    return <EmptyHint text="Индексы пока недоступны." />;
  }

  return (
    <div>
      <div className="term-row grid-cols-[minmax(48px,1.4fr)_70px_56px_52px_44px] text-terminal-muted text-[9px] uppercase tracking-wide sticky top-0 bg-terminal-panel z-[1]">
        <span>Инструмент</span>
        <span className="text-right">Цена</span>
        <span className="text-right">Изм.</span>
        <span className="text-right">%</span>
        <span className="text-right">Сессия</span>
      </div>
      {rows.map((r) => {
        const sess = sessionBadge(r.session);
        const missing = r.price == null;
        const missingReason = missing ? "нет данных" : null;
        return (
          <button
            key={r.symbol}
            type="button"
            data-sym={r.symbol}
            onClick={() => onFocus?.(r.symbol)}
            className={clsx(
              "term-row grid-cols-[minmax(48px,1.4fr)_70px_56px_52px_44px] w-full text-left",
              focusSymbol === r.symbol && "bg-terminal-accent-muted",
            )}
            title={r.name || r.symbol}
          >
            <span className="text-terminal-text truncate min-w-[48px] font-medium">
              {r.symbol || "—"}
              {missingReason ? (
                <span className="text-terminal-down ml-1 text-[8px] uppercase">нет данных</span>
              ) : r.name ? (
                <span className="text-terminal-muted ml-1 hidden xl:inline text-[9px]">{r.name}</span>
              ) : null}
            </span>
            <span className="text-right">{missing ? "—" : fmtPrice(r.price, r.currency)}</span>
            <span className={`text-right ${changeClass(r.change)}`}>
              {missing ? "—" : fmtNum(r.change)}
            </span>
            <span className={`text-right ${changeClass(r.change_pct)}`}>
              {missing || r.change_pct == null ? "—" : fmtPct(r.change_pct)}
            </span>
            <span className={`text-right text-[8px] font-bold ${sess?.cls ?? "term-flat"}`}>
              {sess?.label ?? "—"}
            </span>
          </button>
        );
      })}
      {rows.some((r) => r.price == null) && (
        <p className="px-2 py-1 text-[8px] text-terminal-muted border-t border-terminal-border leading-snug">
          N/A = no quote — hover row for provider reason (not faked as 0%)
        </p>
      )}
    </div>
  );
}
