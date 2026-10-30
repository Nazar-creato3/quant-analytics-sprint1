"use client";

import { NavBar } from "@/components/layout/NavBar";
import { AppPageShell } from "@/components/layout/AppPageShell";
import { PageErrorBoundary } from "@/components/layout/PageErrorBoundary";
import { BotsPanel } from "@/components/bots/BotsPanel";
import { CrossActions } from "@/components/shared/CrossActions";
import { useProductContext } from "@/contexts/ProductContext";

export default function BotsPage() {
  const { activeTicker } = useProductContext();
  return (
    <div className="min-h-screen bg-cockpit-bg text-qa-text flex flex-col operator-shell">
      <NavBar activeTab="bots" />
      <AppPageShell title="Боты" width="xl">
        <CrossActions ticker={activeTicker} />
        <PageErrorBoundary>
          <BotsPanel />
        </PageErrorBoundary>
      </AppPageShell>
    </div>
  );
}
