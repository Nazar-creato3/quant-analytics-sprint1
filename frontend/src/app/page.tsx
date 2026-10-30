"use client";

import { OperatorDashboard } from "@/components/operator/OperatorDashboard";
import { NavBar } from "@/components/layout/NavBar";
import { PageErrorBoundary } from "@/components/layout/PageErrorBoundary";
import { HOME_USER_COPY } from "@/app/homeUserCopy";

/** Operator cockpit only — Research mode removed from product nav. */
export default function DashboardPage() {
  return (
    <PageErrorBoundary title={HOME_USER_COPY.errorTitle}>
      <div className="h-[calc(100dvh-3.5rem)] md:h-screen overflow-y-auto md:overflow-hidden bg-cockpit-bg text-qa-text flex flex-col operator-shell">
        <NavBar activeTab="dashboard" />
        <OperatorDashboard />
      </div>
    </PageErrorBoundary>
  );
}
