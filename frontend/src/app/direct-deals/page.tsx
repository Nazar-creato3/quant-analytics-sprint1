"use client";

import { Suspense } from "react";
import { NavBar } from "@/components/layout/NavBar";
import { PageErrorBoundary } from "@/components/layout/PageErrorBoundary";
import { DirectDealsView } from "@/components/direct-deals/DirectDealsView";
import { CrossActions } from "@/components/shared/CrossActions";

function DirectDealsFallback() {
  return (
    <div className="flex-1 flex items-center justify-center text-sm text-qa-muted">
      Загрузка…
    </div>
  );
}

export default function DirectDealsPage() {
  return (
    <div className="min-h-screen bg-qa-bg text-qa-text flex flex-col">
      <NavBar activeTab="direct-deals" />
      <div className="px-4 py-2">
        <CrossActions />
      </div>
      <PageErrorBoundary title="Сделки">
        <Suspense fallback={<DirectDealsFallback />}>
          <DirectDealsView />
        </Suspense>
      </PageErrorBoundary>
    </div>
  );
}
