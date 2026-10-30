"use client";

import { DirectDealsOrderBookPanel } from "@/components/direct-deals/DirectDealsOrderBookPanel";

export function TerminalOrderBookPanel({ symbol }: { symbol: string }) {
  return (
    <div className="h-full min-h-[280px]">
      <DirectDealsOrderBookPanel ticker={symbol} side="buy" />
    </div>
  );
}
