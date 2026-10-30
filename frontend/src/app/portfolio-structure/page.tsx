"use client";

import { NavBar } from "@/components/layout/NavBar";
import { AppPageShell } from "@/components/layout/AppPageShell";
import { PageErrorBoundary } from "@/components/layout/PageErrorBoundary";
import { LookthroughPanel } from "@/components/portfolio/LookthroughPanel";
import { ConcentrationCard } from "@/components/market/ConcentrationCard";

export default function PortfolioStructurePage() {
  return (
    <div className="min-h-screen bg-cockpit-bg text-qa-text flex flex-col">
      <NavBar activeTab="portfolio-risk" />
      <AppPageShell title="Структура портфеля">
        <PageErrorBoundary>
          <LookthroughPanel />
          <div className="mt-4">
            <ConcentrationCard />
          </div>
        </PageErrorBoundary>
      </AppPageShell>
    </div>
  );
}
