import { StrategyComposerView } from "@/components/strategy-composer";
import { PageErrorBoundary } from "@/components/layout/PageErrorBoundary";

export default function StrategyComposerPage() {
  return (
    <PageErrorBoundary title="Strategy Composer">
      <StrategyComposerView />
    </PageErrorBoundary>
  );
}
