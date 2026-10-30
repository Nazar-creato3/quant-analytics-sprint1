"use client";

import { AssetCockpitView } from "@/components/cockpit/AssetCockpitView";
import { PageErrorBoundary } from "@/components/layout/PageErrorBoundary";

interface CockpitPageProps {
  params: { symbol: string };
}

export default function CockpitSymbolPage({ params }: CockpitPageProps) {
  return (
    <PageErrorBoundary title="Asset Cockpit">
      <AssetCockpitView symbol={params.symbol} />
    </PageErrorBoundary>
  );
}
