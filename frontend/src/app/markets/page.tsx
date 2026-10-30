"use client";

import { NavBar } from "@/components/layout/NavBar";
import { AppPageShell } from "@/components/layout/AppPageShell";
import { PageErrorBoundary } from "@/components/layout/PageErrorBoundary";
import { MarketsOverview } from "@/components/markets/MarketsOverview";
import { CrossActions } from "@/components/shared/CrossActions";

export default function MarketsPage() {
  return (
    <div className="min-h-screen bg-cockpit-bg text-qa-text flex flex-col operator-shell">
      <NavBar activeTab="markets" />
      <AppPageShell
        title="Рынки сегодня"
        description="Индексы, сектора, облигации, валюты, сырьё и новости на одном экране."
        width="full"
        fillViewport
        className="flex-1 min-h-0 overflow-auto"
      >
        <PageErrorBoundary title="Рынки">
          <CrossActions />
          <MarketsOverview />
        </PageErrorBoundary>
      </AppPageShell>
    </div>
  );
}
