"use client";

import { OperatorDetailShell } from "@/components/operator/OperatorDetailShell";
import { DecisionFeed } from "@/components/operator/DecisionFeed";

/** Alias route — same Decision Feed as /operator/decisions */
export default function OperatorDecisionFeedPage() {
  return (
    <OperatorDetailShell
      title="Decision Feed"
      description="Полная лента сигналов, рисков, исполнения и системных событий pipeline."
      fillViewport
    >
      <DecisionFeed enabled className="flex-1 min-h-0 h-full w-full" />
    </OperatorDetailShell>
  );
}
