"use client";

import type { TerminalPerformanceRow } from "@/types/terminal";
import { EmptyHint, changeClass, fmtNum, fmtPct } from "../TermPanel";

const PERF_LABEL_RU: Record<string, string> = {
  "NASDAQ Daily": "Nasdaq",
  "DOW Daily": "Dow Jones",
  "S&P 500 Daily": "S&P 500",
  "S&P vs DOW Spread": "S&P 500 минус Dow",
  "NASDAQ vs S&P Spread": "Nasdaq минус S&P 500",
  "GOLD (XAU)": "Золото",
  "Gold (XAU)": "Золото",
};

export function PerformancePanel({ rows }: { rows: TerminalPerformanceRow[] }) {
  if (!rows.length) {
    return <EmptyHint text="Пока нет данных о результате." />;
  }

  return (
    <div>
      {rows.map((r) => {
        const missing = r.value == null;
        return (
          <div
            key={`${r.label}-${r.period}`}
            className="term-row grid-cols-[1fr_44px_64px]"
            title={r.reason || undefined}
          >
            <span className="truncate text-terminal-text">{PERF_LABEL_RU[r.label] ?? r.label}</span>
            <span className="text-terminal-muted text-[9px] uppercase">{r.period === "LEVEL" ? "уровень" : r.period === "TODAY" ? "день" : r.period}</span>
            <span
              className={`text-right ${
                missing ? "term-flat" : changeClass(r.unit === "level" ? 0 : r.value)
              }`}
            >
              {missing
                ? "нет данных"
                : r.unit === "level"
                  ? fmtNum(r.value, 1)
                  : fmtPct(r.value)}
            </span>
          </div>
        );
      })}
      {rows.some((r) => r.value == null) && (
        <p className="px-2 py-1 text-[9px] text-terminal-muted border-t border-terminal-border">
          «нет данных» — котировка не пришла или изменение не опубликовано; нули не подставляем
        </p>
      )}
    </div>
  );
}
