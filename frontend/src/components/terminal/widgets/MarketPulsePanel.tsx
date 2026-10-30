"use client";

import type { TerminalPulse } from "@/types/terminal";
import { EmptyHint, changeClass, fmtNum, fmtPct, fmtVol, ruLabel } from "../TermPanel";

function fearGradientStyle() {
  return {
    background: "var(--qa-fear-gradient)",
  } as const;
}

export function MarketPulsePanel({
  pulse,
  onFocus,
}: {
  pulse: TerminalPulse;
  onFocus?: (symbol: string) => void;
}) {
  const fg = pulse.fear_greed;

  return (
    <div className="px-2 py-1.5 space-y-2">
      <div>
        <p className="text-[9px] text-terminal-muted uppercase tracking-wider mb-1">
          Индекс настроения
        </p>
        {fg == null ? (
          <EmptyHint text="Нет данных об индексе настроения." />
        ) : (
          <div className="flex items-end justify-between gap-2">
            <div className="flex items-baseline gap-1">
              <span className="text-2xl font-bold text-terminal-accent tabular leading-none">{fg}</span>
              <span className="text-[10px] text-terminal-muted">/100</span>
            </div>
            <span className="text-[11px] font-bold uppercase text-terminal-accent tracking-wide">
              {ruLabel(pulse.label)}
            </span>
          </div>
        )}
        {fg != null && (
          <div className="mt-1.5 relative">
            <div className="h-1.5 rounded-sm overflow-hidden" style={fearGradientStyle()} />
            <div
              className="absolute top-1/2 -translate-y-1/2 w-0 h-0 border-l-[4px] border-r-[4px] border-b-[6px] border-l-transparent border-r-transparent border-b-terminal-text"
              style={{ left: `calc(${Math.min(100, Math.max(0, fg))}% - 4px)` }}
              aria-hidden
            />
          </div>
        )}
      </div>

      <div>
        <p className="text-[9px] text-terminal-muted uppercase tracking-wider mb-1">Ширина рынка: растут / падают</p>
        {pulse.breadth.length === 0 ? (
          <EmptyHint text="Ширина рынка пока не посчитана." />
        ) : (
          pulse.breadth.map((b) => {
            const total = b.advancers + b.decliners;
            if (total <= 0) {
              return (
                <div key={b.exchange} className="mb-1 flex justify-between text-[9px] text-terminal-muted">
                  <span className="uppercase tracking-wide">{b.exchange}</span>
                  <span>пока нет данных</span>
                </div>
              );
            }
            const advPct = (b.advancers / total) * 100;
            return (
              <div key={b.exchange} className="mb-1">
                <div className="flex justify-between text-[9px] text-terminal-muted mb-0.5">
                  <span className="uppercase tracking-wide">{b.exchange}</span>
                  <span>
                    <span className="term-up">{b.advancers}</span>
                    {" / "}
                    <span className="term-down">{b.decliners}</span>
                  </span>
                </div>
                <div className="term-gauge-track flex h-[5px]">
                  <div
                    className="h-full"
                    style={{ width: `${advPct}%`, backgroundColor: "var(--terminal-up)" }}
                  />
                  <div
                    className="h-full flex-1"
                    style={{ backgroundColor: "var(--terminal-down)" }}
                  />
                </div>
              </div>
            );
          })
        )}
      </div>

      <div className="grid grid-cols-2 gap-2">
        <div>
          <p className="text-[9px] term-up uppercase tracking-wider mb-0.5">▲ Лидеры роста</p>
          {pulse.gainers.length === 0 ? (
            <p className="text-[9px] text-terminal-muted">Нет лидеров роста</p>
          ) : (
            pulse.gainers.map((g) => (
              <button
                key={g.symbol}
                type="button"
                className="flex justify-between items-baseline gap-1 w-full text-[10px] font-mono py-0.5 hover:text-terminal-accent"
                onClick={() => onFocus?.(g.symbol)}
              >
                <span className="text-terminal-text">{g.symbol}</span>
                <span className="term-up">{fmtPct(g.change_pct)}</span>
                <span className="text-terminal-muted text-[8px]">
                  объём: {g.volume_label || fmtVol(g.volume)}
                </span>
              </button>
            ))
          )}
        </div>
        <div>
          <p className="text-[9px] term-down uppercase tracking-wider mb-0.5">▼ Лидеры падения</p>
          {pulse.losers.length === 0 ? (
            <p className="text-[9px] text-terminal-muted">Нет лидеров падения</p>
          ) : (
            pulse.losers.map((g) => (
              <button
                key={g.symbol}
                type="button"
                className="flex justify-between items-baseline gap-1 w-full text-[10px] font-mono py-0.5 hover:text-terminal-accent"
                onClick={() => onFocus?.(g.symbol)}
              >
                <span className="text-terminal-text">{g.symbol}</span>
                <span className="term-down">{fmtPct(g.change_pct)}</span>
                <span className="text-terminal-muted text-[8px]">
                  объём: {g.volume_label || fmtVol(g.volume)}
                </span>
              </button>
            ))
          )}
        </div>
      </div>

      <div>
        <div className="flex items-center justify-between mb-0.5">
          <p className="text-[9px] text-terminal-muted uppercase tracking-wider">Мировые рынки</p>
          {pulse.vol_regime ? (
            <span className="term-pill on text-[8px]">Волатильность: {ruLabel(pulse.vol_regime)}</span>
          ) : null}
        </div>
        {(pulse.global_snapshot ?? []).map((s) => (
          <div key={s.symbol} className="term-row grid-cols-[1fr_72px_52px] !px-0">
            <span className="text-terminal-muted uppercase text-[9px]">{s.label || s.symbol}</span>
            <span className="text-right text-terminal-accent">{fmtNum(s.value, s.symbol === "BTC" || s.symbol === "GOLD" ? 0 : 2)}</span>
            <span className={`text-right ${changeClass(s.change_pct)}`}>{fmtPct(s.change_pct)}</span>
          </div>
        ))}
        {!(pulse.global_snapshot ?? []).length && (
          <EmptyHint text="Сводка рынка пока недоступна." />
        )}
      </div>
    </div>
  );
}
