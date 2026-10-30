"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import { useActiveTicker } from "@/contexts/ActiveTickerContext";
import { NavBar } from "@/components/layout/NavBar";
import { TerminalWorkspace } from "./TerminalWorkspace";
import { TerminalRightRail } from "./TerminalRightRail";
import { TerminalCompanionDock } from "./TerminalCompanionDock";
import { RunningTape } from "./widgets/RunningTape";
import { useTerminalClock, useTerminalRealtime } from "./useTerminalRealtime";
import {
  TERMINAL_SHORTCUT_HELP,
  useTerminalShortcuts,
} from "./useTerminalShortcuts";
import type { TerminalDensity } from "@/types/terminal";
import { clsx } from "clsx";
import Link from "next/link";
import { HelpCircle, RefreshCw, X } from "lucide-react";
import { TickerForecastDesk } from "@/components/forecasting/TickerForecastDesk";
import { TerminalManeuversPanel } from "./panels/TerminalManeuversPanel";
import { FeedFreshnessIndicators } from "./FeedFreshnessIndicators";
import { LiveDataBadge } from "@/components/shared/LiveDataBadge";
import { CrossActions } from "@/components/shared/CrossActions";
import { fmtMskTime } from "./TermPanel";
import { formatFreshnessAge } from "@/hooks/useLiveFreshness";

export function TerminalShell() {
  const [density, setDensity] = useState<TerminalDensity>("compact");
  const [helpOpen, setHelpOpen] = useState(false);
  const [companionOpen, setCompanionOpen] = useState(false);
  const [deskOverlay, setDeskOverlay] = useState<"forecast" | "maneuvers" | null>(null);
  const { activeTicker, setActiveTicker } = useActiveTicker();
  const chatInputRef = useRef<HTMLInputElement>(null);
  const watchInputRef = useRef<HTMLInputElement>(null);

  const {
    snapshot,
    isLoading,
    isFetching,
    source,
    wsConnected,
    dataFreshness,
    lastUpdateAt,
    refresh,
  } = useTerminalRealtime();
  const now = useTerminalClock(1000);

  const onFocusSymbol = useCallback((symbol: string) => {
    setActiveTicker(symbol);
  }, [setActiveTicker]);

  const shortcutHandlers = useMemo(
    () => ({
      toggleDensity: () =>
        setDensity((d) => (d === "compact" ? "comfortable" : "compact")),
      setDensity,
      refresh,
      focusWatch: () => {
        watchInputRef.current?.focus();
        watchInputRef.current?.select();
      },
      focusChat: () => {
        chatInputRef.current?.focus();
      },
      toggleHelp: () => setHelpOpen((v) => !v),
      closeOverlays: () => {
        setHelpOpen(false);
        setCompanionOpen(false);
        setDeskOverlay(null);
      },
      toggleCompanion: () => setCompanionOpen((v) => !v),
    }),
    [refresh],
  );

  useTerminalShortcuts(shortcutHandlers, true);

  const closeHelp = useCallback(() => setHelpOpen(false), []);

  return (
    <div className="h-[calc(100dvh-3.5rem)] md:h-[100dvh] max-h-[calc(100dvh-3.5rem)] md:max-h-[100dvh] overflow-hidden bg-terminal-bg text-terminal-text flex flex-col">
      <NavBar activeTab="terminal" />
      <div
        className={clsx(
          "qa-terminal flex-1 flex flex-col min-h-0 overflow-hidden",
          density === "compact" ? "density-compact" : "density-comfortable",
        )}
      >
        <div className="flex items-center gap-2 px-2 py-0.5 border-b border-terminal-border bg-terminal-surface shrink-0 text-[10px] overflow-x-auto">
          <span className="font-bold tracking-[0.12em] uppercase text-terminal-accent shrink-0">
            Терминал
          </span>
          <FeedFreshnessIndicators compact />
          <LiveDataBadge
            state={dataFreshness}
            ageLabel={formatFreshnessAge(lastUpdateAt, now.getTime())}
            wsConnected={wsConnected}
            className={clsx(
              "term-pill shrink-0 px-1.5 py-0.5 rounded border border-terminal-border",
              dataFreshness === "live" && "on border-terminal-up/40",
            )}
          />
          <span className={clsx("term-pill shrink-0", (source === "live" || source === "partial") && "on")}>
            {source === "live" ? "онлайн" : source === "partial" ? "частично" : "пример"}
          </span>
          <span className="term-pill on shrink-0" title="Текущий инструмент для графика, стакана, прогноза, риска и новостей">
            {activeTicker}
          </span>
          <CrossActions ticker={activeTicker} />
          <Link
            href="/screener"
            className="term-btn shrink-0 hidden sm:inline-flex"
            title="FMP screener — row opens this Terminal"
          >
            Скринер
          </Link>
          <button
            type="button"
            className="term-btn shrink-0 inline-flex"
            onClick={() => setDeskOverlay("forecast")}
          >
            Прогноз {activeTicker}
          </button>
          <button
            type="button"
            className="term-btn shrink-0 inline-flex"
            onClick={() => setDeskOverlay("maneuvers")}
          >
            Манёвры {activeTicker}
          </button>
          <span className="text-terminal-muted font-mono ml-auto shrink-0 hidden sm:inline" title="Moscow time">
            {fmtMskTime(now)} MSK
          </span>
          <button
            type="button"
            className="term-btn shrink-0"
            onClick={() => refresh()}
            disabled={isFetching}
            title="Refresh (R)"
          >
            <RefreshCw size={11} className={isFetching ? "animate-spin" : undefined} />
            <span className="hidden sm:inline">Обновить</span>
          </button>
          <button
            type="button"
            className="term-btn shrink-0 hidden md:inline-flex"
            onClick={() => setDensity((d) => (d === "compact" ? "comfortable" : "compact"))}
            title="Density (D)"
          >
            {density}
          </button>
          <button
            type="button"
            className="term-btn shrink-0 hidden lg:inline-flex"
            onClick={() => setCompanionOpen((v) => !v)}
            title="Companion (C)"
          >
            Помощник
          </button>
          <button
            type="button"
            className="term-btn shrink-0 hidden sm:inline-flex"
            onClick={() => setHelpOpen(true)}
            title="Shortcuts (?)"
          >
            <HelpCircle size={11} />
          </button>
        </div>

        <RunningTape
          items={snapshot?.tape ?? []}
          focusSymbol={activeTicker}
          onFocus={onFocusSymbol}
        />

        <div className="flex-1 flex flex-col lg:flex-row min-h-0 overflow-hidden">
          <TerminalWorkspace
            snapshot={snapshot}
            chatInputRef={chatInputRef}
            focusSymbol={activeTicker}
            onFocusSymbol={onFocusSymbol}
          />
          <TerminalRightRail
            watchlist={snapshot?.watchlist ?? []}
            news={snapshot?.news ?? []}
            alerts={snapshot?.alerts ?? []}
            watchInputRef={watchInputRef}
            focusSymbol={activeTicker}
            onFocusSymbol={onFocusSymbol}
          />
        </div>

        <TerminalCompanionDock
          open={companionOpen}
          onClose={() => setCompanionOpen(false)}
        />
      </div>

      {deskOverlay && (
        <div
          className="fixed inset-0 z-[70] bg-black/75 flex items-start justify-center p-3 pt-[8vh]"
          role="dialog"
          aria-modal
          aria-label={deskOverlay === "forecast" ? `Forecast ${activeTicker}` : `Maneuvers ${activeTicker}`}
          onClick={() => setDeskOverlay(null)}
        >
          <div
            className="w-full max-w-6xl max-h-[86vh] overflow-y-auto rounded border border-terminal-border bg-terminal-bg"
            onClick={(e) => e.stopPropagation()}
          >
            <header className="sticky top-0 z-[1] flex items-center justify-between gap-2 px-3 py-2 border-b border-terminal-border bg-terminal-surface">
              <span className="text-[11px] uppercase tracking-wide text-terminal-accent">
                {deskOverlay === "forecast" ? `Forecast ${activeTicker}` : `Maneuvers ${activeTicker}`}
              </span>
              <button type="button" className="term-btn" onClick={() => setDeskOverlay(null)}>
                <X size={12} aria-hidden /> Закрыть
              </button>
            </header>
            <div className="p-3">
              {deskOverlay === "forecast" ? (
                <TickerForecastDesk symbol={activeTicker} />
              ) : (
                <TerminalManeuversPanel symbol={activeTicker} />
              )}
            </div>
          </div>
        </div>
      )}

      {helpOpen && (
        <div
          className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4"
          role="dialog"
          aria-modal
          aria-label="Keyboard shortcuts"
          onClick={closeHelp}
        >
          <div
            className="term-panel w-full max-w-md"
            onClick={(e) => e.stopPropagation()}
          >
            <header className="term-panel-header">
              <span>Горячие клавиши</span>
              <button type="button" className="term-btn" onClick={closeHelp}>
                Esc
              </button>
            </header>
            <ul className="p-3 space-y-1.5">
              {TERMINAL_SHORTCUT_HELP.map((row) => (
                <li
                  key={row.keys}
                  className="flex justify-between gap-4 text-[11px] font-mono border-b border-terminal-border pb-1"
                >
                  <kbd className="text-terminal-accent">{row.keys}</kbd>
                  <span className="text-terminal-muted text-right">{row.action}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {isLoading && !snapshot && (
        <div className="sr-only" aria-live="polite">
          Загрузка терминала
        </div>
      )}
    </div>
  );
}
