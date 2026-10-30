"use client";

import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";
import { usePathname } from "next/navigation";
import { useAuth } from "@/hooks";
import { OnboardingContext } from "@/hooks/useOnboarding";
import {
  completeOnboarding,
  shouldAutoStartOnboarding,
} from "@/lib/onboarding/storage";
import { stepsForAudience } from "@/lib/onboarding/tourCatalog";
import { OnboardingTour } from "./OnboardingTour";

const PUBLIC_PREFIXES = [
  "/login",
  "/signup",
  "/apply",
  "/legal",
  "/verify-email",
  "/recover",
  "/reset",
  "/wasnt-me",
];

function isPublicPath(pathname: string): boolean {
  return PUBLIC_PREFIXES.some((p) => pathname === p || pathname.startsWith(`${p}/`));
}

export function OnboardingProvider({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { user, isAuthenticated, isStaff, isAdmin, isLoading } = useAuth();
  const steps = useMemo(
    () => stepsForAudience(isStaff, isAdmin),
    [isStaff, isAdmin],
  );
  const [active, setActive] = useState(false);
  const [stepIndex, setStepIndex] = useState(0);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const t = window.setTimeout(() => setReady(true), 350);
    return () => window.clearTimeout(t);
  }, []);

  useEffect(() => {
    if (!ready || isLoading || !isAuthenticated || !user) return;
    if (isPublicPath(pathname)) return;
    if (shouldAutoStartOnboarding()) {
      setStepIndex(0);
      setActive(true);
    }
  }, [ready, isLoading, isAuthenticated, user, pathname]);

  const dismiss = useCallback(() => {
    completeOnboarding();
    setActive(false);
  }, []);

  const startReplay = useCallback(() => {
    setStepIndex(0);
    setActive(true);
  }, []);

  const next = useCallback(() => {
    setStepIndex((i) => {
      if (i >= steps.length - 1) {
        completeOnboarding();
        setActive(false);
        return i;
      }
      return i + 1;
    });
  }, [steps.length]);

  const back = useCallback(() => {
    setStepIndex((i) => Math.max(0, i - 1));
  }, []);

  const hidden = !isAuthenticated || isPublicPath(pathname);

  const value = useMemo(
    () => ({
      active: active && !hidden,
      stepIndex,
      steps,
      step: steps[stepIndex] ?? null,
      startReplay,
      next,
      back,
      dismiss,
    }),
    [active, hidden, stepIndex, steps, startReplay, next, back, dismiss],
  );

  return (
    <OnboardingContext.Provider value={value}>
      {children}
      <OnboardingTour />
    </OnboardingContext.Provider>
  );
}
