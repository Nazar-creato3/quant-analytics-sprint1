"use client";

import { NavBar } from "@/components/layout/NavBar";
import { AppPageShell } from "@/components/layout/AppPageShell";
import { PageErrorBoundary } from "@/components/layout/PageErrorBoundary";
import { ScreenerView } from "@/components/screener/ScreenerView";

export default function ScreenerPage() {
  return (
    <div className="min-h-screen bg-cockpit-bg text-qa-text flex flex-col operator-shell">
      <NavBar activeTab="screener" />
      <AppPageShell
        title="Скринер"
        description="Подберите бумаги по рынку, отрасли и размеру — таблица обновляется сразу. Нажмите на строку, чтобы открыть бумагу."
        width="full"
        fillViewport
        className="flex-1 min-h-0 overflow-hidden"
      >
        <PageErrorBoundary title="Скринер">
          <ScreenerView />
        </PageErrorBoundary>
      </AppPageShell>
    </div>
  );
}
