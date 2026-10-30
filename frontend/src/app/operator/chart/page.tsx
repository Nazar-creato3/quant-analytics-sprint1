"use client";

import { useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { OperatorDetailShell } from "@/components/operator/OperatorDetailShell";
import { MainChartPanel } from "@/components/operator/MainChartPanel";

function ChartDetailContent() {
  const searchParams = useSearchParams();
  const symbol = (searchParams.get("symbol") || "AAPL").toUpperCase();
  const showDesk = searchParams.get("desk") !== "0";

  return (
    <OperatorDetailShell
      title={`График — ${symbol}`}
      description="Широкоэкранный режим: график и выписка по бумаге под ним. Прокрутите вниз к выписке."
      fillViewport={false}
    >
      <div className="flex flex-col gap-3 pb-8">
        <MainChartPanel
          ticker={symbol}
          chartEngine="lightweight"
          statementUnderChart={showDesk}
          fixedHeight={520}
          className="min-h-0"
        />
      </div>
    </OperatorDetailShell>
  );
}

export default function OperatorChartPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-cockpit-bg" />}>
      <ChartDetailContent />
    </Suspense>
  );
}
