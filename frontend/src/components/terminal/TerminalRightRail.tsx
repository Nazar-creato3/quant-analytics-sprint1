"use client";

import type { RefObject } from "react";
import { TermPanel, fmtMskDateTime, relativeTime } from "./TermPanel";
import { WatchlistDensePanel } from "./widgets/WatchlistDensePanel";
import { TerminalTickerNews } from "./panels/TerminalTickerNews";
import type { TerminalAlert, TerminalNewsItem, TerminalWatchItem } from "@/types/terminal";
import { clsx } from "clsx";

function severityClass(s: TerminalAlert["severity"]): string {
  if (s === "critical") return "term-down";
  if (s === "warn") return "text-terminal-accent";
  return "text-terminal-muted";
}

export function TerminalRightRail({
  watchlist,
  news,
  alerts,
  watchInputRef,
  focusSymbol,
  onFocusSymbol,
}: {
  watchlist: TerminalWatchItem[];
  news: TerminalNewsItem[];
  alerts: TerminalAlert[];
  watchInputRef: RefObject<HTMLInputElement | null>;
  focusSymbol?: string | null;
  onFocusSymbol?: (symbol: string) => void;
}) {
  return (
    <aside className="w-full lg:w-[320px] shrink-0 border-t lg:border-t-0 lg:border-l border-terminal-border bg-terminal-surface flex flex-col min-h-0 gap-1 p-1 max-h-[40vh] lg:max-h-none overflow-y-auto">
      <TermPanel title="Все бумаги" className="flex-[1.4] min-h-[220px] max-h-[42vh]">
        <WatchlistDensePanel
          rows={watchlist}
          focusSymbol={focusSymbol}
          onFocus={onFocusSymbol}
          filterRef={watchInputRef}
        />
      </TermPanel>

      <TermPanel title={focusSymbol ? `News · ${focusSymbol}` : "Market News"} className="flex-1 min-h-[160px] max-h-[32vh]">
        {focusSymbol ? (
          <TerminalTickerNews symbol={focusSymbol} snapshotNews={news} />
        ) : (
          <>
            {news.map((n) => (
              <div key={n.id} className="term-row !block space-y-0.5 !py-1">
                {n.url ? (
                  <a
                    href={n.url}
                    target="_blank"
                    rel="noreferrer"
                    className="text-[10px] text-terminal-text hover:text-terminal-accent leading-snug block"
                  >
                    {n.headline}
                  </a>
                ) : (
                  <p className="text-[10px] text-terminal-text leading-snug">{n.headline}</p>
                )}
                <p className="text-[8px] text-terminal-muted">
                  {n.source} · {fmtMskDateTime(n.published_at)} MSK · {relativeTime(n.published_at)} ago
                </p>
              </div>
            ))}
            {news.length === 0 && (
              <p className="p-2 text-[10px] text-terminal-muted">Нет новостей</p>
            )}
          </>
        )}
      </TermPanel>

      <TermPanel title="Alerts" className="flex-[0.7] min-h-[100px] max-h-[18vh]">
        {alerts.map((a) => (
          <div key={a.id} className="term-row !block space-y-0.5">
            <div className="flex items-center justify-between gap-2">
              <span className={clsx("text-[10px] font-semibold", severityClass(a.severity))}>
                {a.title}
              </span>
              <span className="text-[8px] text-terminal-muted">{fmtMskDateTime(a.ts)} MSK</span>
            </div>
            {a.body ? <p className="text-[9px] text-terminal-muted leading-snug">{a.body}</p> : null}
          </div>
        ))}
        {alerts.length === 0 && (
          <p className="p-2 text-[10px] text-terminal-muted">Нет оповещений</p>
        )}
      </TermPanel>
    </aside>
  );
}
