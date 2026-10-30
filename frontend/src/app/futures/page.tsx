"use client";

import { NavBar } from "@/components/layout/NavBar";
import { AppPageShell } from "@/components/layout/AppPageShell";
import { PageErrorBoundary } from "@/components/layout/PageErrorBoundary";
import { FuturesDeskView } from "@/components/futures/FuturesDesk";

export default function FuturesPage() {
  return (
    <div className="min-h-screen bg-cockpit-bg text-qa-text flex flex-col operator-shell">
      <NavBar activeTab="futures" />
      <AppPageShell
        title="Фьючерсы"
        description="Ваши фьючерсы и запас по обеспечению, защита портфеля от падения рынка и курса, калькулятор любого контракта Мосбиржи."
        showBack={false}
      >
        <PageErrorBoundary title="Фьючерсы">
          <FuturesDeskView />
        </PageErrorBoundary>
      </AppPageShell>
    </div>
  );
}
