"use client";

import { AssetCockpitView } from "@/components/cockpit/AssetCockpitView";

interface ResearchCockpitPageProps {
  params: { symbol: string };
}

/** Research-mode alias for Asset Cockpit (Prompt 9). */
export default function ResearchCockpitPage({ params }: ResearchCockpitPageProps) {
  return <AssetCockpitView symbol={params.symbol} />;
}
