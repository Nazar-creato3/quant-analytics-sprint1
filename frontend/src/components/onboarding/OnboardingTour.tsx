"use client";

import { useOnboarding } from "@/hooks/useOnboarding";
import { HighlightOverlay } from "./HighlightOverlay";
import { StepTooltip } from "./StepTooltip";

export function OnboardingTour() {
  const { active, step, stepIndex, steps, next, back, dismiss } = useOnboarding();
  if (!active || !step) return null;

  return (
    <>
      <HighlightOverlay target={step.target} />
      <StepTooltip
        step={step}
        index={stepIndex}
        total={steps.length}
        onNext={next}
        onBack={back}
        onDismiss={dismiss}
      />
    </>
  );
}
