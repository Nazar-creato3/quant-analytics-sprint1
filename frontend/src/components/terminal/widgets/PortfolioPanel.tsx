"use client";

import type { TerminalPortfolio } from "@/types/terminal";
import { EmptyHint, changeClass, fmtNum, fmtPct } from "../TermPanel";

export function PortfolioPanel({ portfolio }: { portfolio: TerminalPortfolio | null | undefined }) {
  if (!portfolio) {
    return (
      <EmptyHint text="Портфелей пока нет. Подключите счёт." />
    );
  }

  const empty = portfolio.positions.length === 0 && portfolio.holdings === 0;

  return (
    <div>
      <div className="grid grid-cols-2 xl:grid-cols-4 gap-px bg-terminal-border border-b border-terminal-border">
        {[
          { label: "Стоимость", value: portfolio.total_value != null ? fmtNum(portfolio.total_value, 0) : "—" },
          {
            label: "За день",
            value:
              portfolio.day_pnl != null
                ? `${fmtNum(portfolio.day_pnl, 0)} (${fmtPct(portfolio.day_pnl_pct)})`
                : "—",
            cls: changeClass(portfolio.day_pnl),
          },
          {
            label: "Всего",
            value:
              portfolio.total_pnl != null
                ? `${fmtNum(portfolio.total_pnl, 0)} (${fmtPct(portfolio.total_pnl_pct)})`
                : "—",
            cls: changeClass(portfolio.total_pnl),
          },
          { label: "Бумаг", value: String(portfolio.holdings) },
        ].map((m) => (
          <div key={m.label} className="bg-terminal-panel px-2 py-1.5">
            <p className="text-[8px] text-terminal-muted uppercase tracking-wider">{m.label}</p>
            <p className={`text-[11px] font-mono font-semibold ${m.cls ?? "text-terminal-text"}`}>
              {m.value}
            </p>
          </div>
        ))}
      </div>

      {(portfolio.drawdown != null || portfolio.concentration || (portfolio.exposures?.length ?? 0) > 0) && (
        <div className="px-2 py-1 border-b border-terminal-border text-[9px] text-terminal-muted flex flex-wrap gap-x-3 gap-y-0.5">
          {portfolio.drawdown != null && (
            <span>
              DD <span className="term-down font-mono">{fmtPct(portfolio.drawdown)}</span>
            </span>
          )}
          {portfolio.concentration && <span>Conc. {portfolio.concentration}</span>}
          {(portfolio.exposures ?? []).slice(0, 4).map((e) => (
            <span key={e.label}>
              {e.label}{" "}
              <span className="text-terminal-text font-mono">
                {e.value == null ? "—" : e.unit === "pct" ? fmtPct(e.value) : fmtNum(e.value)}
              </span>
            </span>
          ))}
        </div>
      )}

      {(portfolio.allocations?.length ?? 0) > 0 && (
        <div className="px-2 py-1 border-b border-terminal-border space-y-0.5">
          <p className="text-[8px] text-terminal-muted uppercase">Распределение</p>
          {(portfolio.allocations ?? []).slice(0, 6).map((a) => (
            <div key={a.label} className="flex justify-between text-[9px] font-mono">
              <span>{a.label}</span>
              <span>{fmtPct(a.weight != null ? a.weight * (Math.abs(a.weight) <= 1.5 ? 100 : 1) : null, 1)}</span>
            </div>
          ))}
        </div>
      )}

      {empty ? (
        <EmptyHint text="Портфелей пока нет. Подключите счёт." />
      ) : (
        <>
          <div className="term-row grid-cols-[1fr_48px_56px_56px_56px] text-terminal-muted text-[9px] uppercase sticky top-0 bg-terminal-panel">
            <span>Инструмент</span>
            <span className="text-right">Шт.</span>
            <span className="text-right">Цена</span>
            <span className="text-right">Стоимость</span>
            <span className="text-right">Результат</span>
          </div>
          {portfolio.positions.map((p) => (
            <div key={p.symbol} className="term-row grid-cols-[1fr_48px_56px_56px_56px]">
              <span className="truncate">{p.symbol}</span>
              <span className="text-right">{p.shares != null ? fmtNum(p.shares, 0) : "—"}</span>
              <span className="text-right">{fmtNum(p.price)}</span>
              <span className="text-right">{fmtNum(p.value, 0)}</span>
              <span className={`text-right ${changeClass(p.pnl)}`}>{fmtNum(p.pnl, 0)}</span>
            </div>
          ))}
        </>
      )}
    </div>
  );
}
