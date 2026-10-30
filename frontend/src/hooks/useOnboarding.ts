"use client";

import { createContext, useContext } from "react";
import type { TourStep } from "@/lib/onboarding/tourCatalog";

export type OnboardingState = {
  active: boolean;
  stepIndex: number;
  steps: TourStep[];
  step: TourStep | null;
  startReplay: () => void;
  next: () => void;
  back: () => void;
  dismiss: () => void;
};

export const OnboardingContext = createContext<OnboardingState | null>(null);

export function useOnboarding(): OnboardingState {
  const ctx = useContext(OnboardingContext);
  if (!ctx) {
    throw new Error("useOnboarding must be used within OnboardingProvider");
  }
  return ctx;
}
