"use client";

import { useEffect, useMemo, useState, type RefObject } from "react";
import { DEFAULT_ACTIVE_TICKER } from "@/lib/active-ticker";
import { TermPanel, changeClass, fmtNum, fmtPct, fmtMskDateTime } from "./TermPanel";
import { GlobalIndicesPanel } from "./widgets/GlobalIndicesPanel";
import { PerformancePanel } from "./widgets/PerformancePanel";
import { MarketPulsePanel } from "./widgets/MarketPulsePanel";
import { MarketHoursPanel } from "./widgets/MarketHoursPanel";
import { PortfolioPanel } from "./widgets/PortfolioPanel";
import { useTerminalChart } from "./useTerminalRealtime";
import type {
  TerminalCalendarEvent,
  TerminalChatMessage,
  TerminalChartBar,
  TerminalChartSeries,
  TerminalSnapshot,
} from "@/types/terminal";
import { terminalApi } from "@/lib/terminal-api";
import { Send } from "lucide-react";
import { TerminalRiskDesk } from "./panels/TerminalRiskDesk";
import { TerminalOrderBookPanel } from "./panels/TerminalOrderBookPanel";
import { TerminalFundamentalsSnapshot } from "./panels/TerminalFundamentalsSnapshot";

function MiniCandleChart({ series, loading }: { series: TerminalChartSeries; loading?: boolean }) {
  const bars = series.bars ?? [];
  const points = series.points;

  const layout = useMemo(() => {
    const src: TerminalChartBar[] =
      bars.length > 0
        ? bars
        : points.map((p) => ({ t: p.t, o: p.v, h: p.v, l: p.v, c: p.v }));
    if (!src.length) return null;
    const w = 320;
    const h = 110;
    const padL = 36;
    const padB = 16;
    const plotW = w - padL;
    const plotH = h - padB;
    const minY = Math.min(...src.map((b) => b.l));
    const maxY = Math.max(...src.map((b) => b.h));
    const spanY = Math.max(1e-6, maxY - minY);
    const step = plotW / Math.max(1, src.length);
    const candleW = Math.max(2, Math.min(7, step - 1));
    const mapped = src.map((b, i) => {
      const x = padL + i * step;
      const yHigh = ((b.h - minY) / spanY) * plotH;
      const yLow = ((b.l - minY) / spanY) * plotH;
      const yOpen = ((b.o - minY) / spanY) * plotH;
      const yClose = ((b.c - minY) / spanY) * plotH;
      const invert = (y: number) => plotH - y;
      const up = b.c >= b.o;
      return {
        x,
        yHigh: invert(yHigh),
        yLow: invert(yLow),
        yOpen: invert(yOpen),
        yClose: invert(yClose),
        up,
        bodyTop: invert(Math.max(yOpen, yClose)),
        bodyBot: invert(Math.min(yOpen, yClose)),
        t: b.t,
      };
    });
    const avgBody =
      mapped.reduce((acc, c) => acc + Math.max(1, c.bodyBot - c.bodyTop), 0) / Math.max(1, mapped.length);
    const lineOnly = spanY / plotH < 0.02 || avgBody < 1.5;
    return {
      mapped,
      w,
      h,
      padL,
      plotW,
      plotH,
      candleW,
      last: src[src.length - 1]?.c,
      first: src[0]?.c,
      lineOnly,
      src,
      minY,
      maxY,
    };
  }, [bars, points]);

  if (!layout) {
    return (
      <div className="p-2 text-[10px] text-terminal-muted font-mono">
        {loading ? `Загрузка ${series.symbol}…` : "График ждёт котировки."}
      </div>
    );
  }

  const { mapped, w, h, padL, plotH, candleW, last, first, lineOnly, src, minY, maxY } = layout;
  const chg = last != null && first != null && first !== 0 ? ((last - first) / first) * 100 : null;
  const fmtAxisT = (ms: number) => {
    const d = new Date(ms);
    return Number.isNaN(d.getTime()) ? "" : `${d.getDate().toString().padStart(2, "0")}.${(d.getMonth() + 1).toString().padStart(2, "0")}`;
  };
  const midY = (minY + maxY) / 2;
  const ticksX = [0, Math.floor(src.length / 2), src.length - 1].filter((i, idx, arr) => arr.indexOf(i) === idx && i >= 0);

  return (
    <div className="p-2">
      <div className="flex items-baseline justify-between mb-1">
        <span className="text-[11px] font-mono text-terminal-text">{series.symbol}</span>
        <span className={`text-[11px] font-mono ${changeClass(chg)}`}>
          {last != null ? fmtNum(last, 1) : "—"} ({fmtPct(chg)})
        </span>
      </div>
      <svg viewBox={`0 0 ${w} ${h}`} className="w-full min-h-[110px] h-[140px]" preserveAspectRatio="xMidYMid meet" aria-hidden>
        {[0, 0.5, 1].map((p) => (
          <line
            key={p}
            x1={padL}
            x2={w}
            y1={plotH * p}
            y2={plotH * p}
            stroke="var(--terminal-border)"
            strokeWidth="0.6"
          />
        ))}
        <text x={2} y={8} fill="var(--terminal-muted)" fontSize="7">{fmtNum(maxY, 1)}</text>
        <text x={2} y={plotH / 2} fill="var(--terminal-muted)" fontSize="7">{fmtNum(midY, 1)}</text>
        <text x={2} y={plotH - 1} fill="var(--terminal-muted)" fontSize="7">{fmtNum(minY, 1)}</text>
        {lineOnly ? (
          <polyline
            fill="none"
            stroke="var(--terminal-accent)"
            strokeWidth="1.5"
            points={mapped.map((c, i) => `${c.x + candleW / 2},${plotH - ((src[i].c - minY) / Math.max(1e-6, maxY - minY)) * plotH}`).join(" ")}
          />
        ) : (
          mapped.map((c, i) => (
            <g key={i}>
              <line
                x1={c.x + candleW / 2}
                y1={c.yHigh}
                x2={c.x + candleW / 2}
                y2={c.yLow}
                stroke={c.up ? "var(--terminal-up)" : "var(--terminal-down)"}
                strokeWidth="1"
              />
              <rect
                x={c.x}
                y={c.bodyTop}
                width={candleW}
                height={Math.max(1, c.bodyBot - c.bodyTop)}
                fill={c.up ? "var(--terminal-up)" : "var(--terminal-down)"}
              />
            </g>
          ))
        )}
        {ticksX.map((i) => (
          <text
            key={i}
            x={mapped[i]?.x ?? padL}
            y={h - 2}
            fill="var(--terminal-muted)"
            fontSize="7"
          >
            {fmtAxisT(src[i].t)}
          </text>
        ))}
      </svg>
    </div>
  );
}

function SparkChart({ series, loading }: { series: TerminalChartSeries; loading?: boolean }) {
  return <MiniCandleChart series={series} loading={loading} />;
}

function CalendarList({ rows }: { rows: TerminalCalendarEvent[] }) {
  return (
    <div>
      <div className="term-row grid-cols-[36px_1fr_44px_44px_44px_36px] text-terminal-muted text-[8px] uppercase sticky top-0 bg-terminal-panel">
        <span>Страна</span>
        <span>Событие</span>
        <span className="text-right">Факт</span>
        <span className="text-right">Прогноз</span>
        <span className="text-right">Было</span>
        <span className="text-right">Важно</span>
      </div>
      {rows.map((e) => (
        <div key={e.id} className="term-row grid-cols-[36px_1fr_44px_44px_44px_36px]">
          <span className="text-terminal-muted truncate">{e.region ?? "—"}</span>
          <div className="min-w-0">
            <p className="text-terminal-text truncate">{e.title}</p>
            <p className="text-[8px] text-terminal-muted">
              {fmtMskDateTime(e.when)} мск
            </p>
          </div>
          <span className="text-right text-terminal-accent truncate">{e.actual ?? "—"}</span>
          <span className="text-right truncate">{e.forecast ?? e.expected ?? "—"}</span>
          <span className="text-right truncate">{e.previous ?? "—"}</span>
          <span className="text-right uppercase text-[8px] text-terminal-muted">
            {e.importance === "high" ? "выс." : e.importance === "low" ? "низ." : "ср."}
          </span>
        </div>
      ))}
      {rows.length === 0 && (
        <p className="p-2 text-[10px] text-terminal-muted">Календарь пуст.</p>
      )}
    </div>
  );
}

function AiChatWidget({
  inputRef,
  symbol,
}: {
  inputRef: RefObject<HTMLInputElement | null>;
  symbol: string;
}) {
  const [messages, setMessages] = useState<TerminalChatMessage[]>([
    {
      id: "sys",
      role: "system",
      body: `Спросите про прогноз, риск, стакан или новости по ${symbol}.`,
      ts: new Date().toISOString(),
    },
  ]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setMessages((prev) => {
      const rest = prev.filter((m) => m.id !== "sys");
      return [
        {
          id: "sys",
          role: "system",
          body: `Спросите про прогноз, риск, стакан или новости по ${symbol}.`,
          ts: new Date().toISOString(),
        },
        ...rest,
      ];
    });
  }, [symbol]);

  const send = async () => {
    const body = text.trim();
    if (!body || busy) return;
    const userMsg: TerminalChatMessage = {
      id: `u-${Date.now()}`,
      role: "user",
      body,
      ts: new Date().toISOString(),
    };
    setMessages((m) => [...m, userMsg]);
    setText("");
    setBusy(true);
    try {
      const reply = await terminalApi.chat(body, symbol);
      setMessages((m) => [...m, reply]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col h-full min-h-[140px]">
      <div className="flex-1 overflow-auto p-2 space-y-1.5">
        {messages.map((m) => (
          <div
            key={m.id}
            className={
              m.role === "user"
                ? "text-right"
                : m.role === "system"
                  ? "text-terminal-muted"
                  : "text-terminal-text"
            }
          >
            <p
              className={
                m.role === "user"
                  ? "term-chat-user inline-block text-left text-[11px] px-2 py-1 border border-terminal-accent-dim max-w-[90%]"
                  : "text-[11px] leading-snug"
              }
            >
              {m.body}
            </p>
          </div>
        ))}
      </div>
      <form
        className="flex gap-1 p-2 border-t border-terminal-border"
        onSubmit={(e) => {
          e.preventDefault();
          void send();
        }}
      >
        <input
          ref={inputRef}
          className="term-input"
          placeholder={`Спросить про ${symbol}…`}
          value={text}
          onChange={(e) => setText(e.target.value)}
          disabled={busy}
        />
        <button type="submit" className="term-btn term-btn-primary" disabled={busy || !text.trim()}>
          <Send size={12} aria-hidden />
        </button>
      </form>
    </div>
  );
}

export function TerminalWorkspace({
  snapshot,
  chatInputRef,
  focusSymbol,
  onFocusSymbol,
}: {
  snapshot: TerminalSnapshot | null;
  chatInputRef: RefObject<HTMLInputElement | null>;
  focusSymbol?: string | null;
  onFocusSymbol?: (symbol: string) => void;
}) {
  const deskSymbol = focusSymbol?.trim() || DEFAULT_ACTIVE_TICKER;
  const chartQ = useTerminalChart(deskSymbol, snapshot?.chart);

  if (!snapshot) {
    return (
      <div className="flex-1 grid place-items-center text-terminal-muted text-xs">
        Загрузка…
      </div>
    );
  }

  const hours = snapshot.market_hours ?? [];
  const snapshotChart =
    snapshot.chart?.symbol &&
    snapshot.chart.symbol.replace(/[-/]/g, "").toUpperCase() ===
      deskSymbol.replace(/[-/]/g, "").toUpperCase()
      ? snapshot.chart
      : null;
  const chartSeries =
    chartQ.data ??
    snapshotChart ??
    ({ symbol: deskSymbol, points: [], bars: [] } as TerminalChartSeries);

  return (
    <div className="flex-1 min-w-0 min-h-[240px] lg:min-h-0 overflow-y-auto p-1">
      <div className="grid gap-1 grid-cols-1 md:grid-cols-2 xl:grid-cols-3 auto-rows-min">
        <TermPanel title="Мировые индексы" className="term-h-indices">
          <GlobalIndicesPanel
            rows={snapshot.indices}
            focusSymbol={focusSymbol}
            onFocus={onFocusSymbol}
          />
        </TermPanel>
        <TermPanel title="Результат" className="term-h-perf">
          <PerformancePanel rows={snapshot.performance} />
        </TermPanel>
        <TermPanel title="Пульс рынка" className="term-h-pulse row-span-2 xl:row-span-2">
          <MarketPulsePanel pulse={snapshot.pulse} onFocus={onFocusSymbol} />
        </TermPanel>
        <TermPanel title="Портфель" className="term-h-portfolio">
          <PortfolioPanel portfolio={snapshot.portfolio} />
        </TermPanel>
        <TermPanel
          title={`График · ${deskSymbol}`}
          className="term-h-chart"
        >
          <SparkChart series={chartSeries} loading={chartQ.isFetching && !chartSeries.points?.length} />
        </TermPanel>
        <TermPanel title={`Стакан · ${deskSymbol}`} className="term-h-book">
          <TerminalOrderBookPanel symbol={deskSymbol} />
        </TermPanel>
        <TermPanel title="Часы торгов" className="term-h-hours">
          <MarketHoursPanel rows={hours} />
        </TermPanel>
        <TermPanel title="Календарь" className="term-h-calendar">
          <CalendarList rows={snapshot.calendar} />
        </TermPanel>
        <TermPanel title="Вопросы" className="term-h-chat md:col-span-2 xl:col-span-2">
          <AiChatWidget inputRef={chatInputRef} symbol={deskSymbol} />
        </TermPanel>
      </div>
      <div className="mt-2 space-y-2">
        <TermPanel title={`Показатели · ${deskSymbol}`} className="term-h-fundamentals">
          <TerminalFundamentalsSnapshot />
        </TermPanel>
        <TermPanel title={`Риск · ${deskSymbol}`} className="term-h-risk-desk">
          <TerminalRiskDesk symbol={deskSymbol} portfolioRisk={snapshot.risk} />
        </TermPanel>
      </div>
      <p className="text-[9px] text-terminal-muted px-1 pt-1 flex flex-wrap gap-x-2">
        <span>на {fmtMskDateTime(snapshot.as_of)} мск</span>
      </p>
    </div>
  );
}
