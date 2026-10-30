"use client";

import { OperatorDetailShell } from "@/components/operator/OperatorDetailShell";
import { DecisionFeed } from "@/components/operator/DecisionFeed";

export default function OperatorDecisionsPage() {
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
