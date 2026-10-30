"use client";

import { ReactNode } from "react";

interface MobileDashboardStackProps {
  watchlist: ReactNode;
  maneuvers: ReactNode;
  positions?: ReactNode;
  chart: ReactNode;
  news?: ReactNode;
  secondary?: ReactNode;
}

export function MobileDashboardStack({
  watchlist,
  maneuvers,
  positions,
  chart,
  news,
  secondary,
}: MobileDashboardStackProps) {
  return (
    <div
      className="md:hidden flex flex-col gap-3 p-2 pb-4 overflow-y-auto min-h-0 flex-1"
      data-tour="dashboard-desk"
    >
      <section className="cockpit-panel p-3 shrink-0">{watchlist}</section>
      <section className="cockpit-panel p-3 shrink-0">{maneuvers}</section>
      {positions && <section className="cockpit-panel p-3 shrink-0">{positions}</section>}
      <section className="cockpit-panel p-3 shrink-0 overflow-visible">{chart}</section>
      {news && <section className="cockpit-panel p-3 shrink-0">{news}</section>}
      {secondary && (
        <details className="cockpit-panel p-3 shrink-0">
          <summary className="text-sm font-medium text-terminal-accent cursor-pointer min-h-[44px] flex items-center">
            Ещё
          </summary>
          <div className="mt-3 space-y-3 max-h-[min(50vh,24rem)] overflow-y-auto overscroll-contain">
            {secondary}
          </div>
        </details>
      )}
    </div>
  );
}
